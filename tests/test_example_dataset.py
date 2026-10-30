"""Schema regressions using recorded metadata and its saved signal chain.

The source fixtures are never changed. Stream names and hardware entries are
matched in processor order, including AP/LFP and Quad Base stream groups.
"""

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from aind_behavior_services.session import Session
from aind_data_schema.components.configs import EphysAssemblyConfig
from aind_data_schema.components.coordinates import CoordinateSystemLibrary
from aind_data_schema.components.devices import (
    Computer,
    EphysAssembly,
    NeuropixelsBasestation,
)
from aind_data_schema.core.acquisition import Acquisition, DataStream
from aind_data_schema.core.instrument import Instrument
from aind_data_schema_models.devices import ProbeModel
from aind_physiology_openephys_data_mappers import (
    AindAcquisitionDataMapper,
    AindInstrumentDataMapper,
)
from aind_physiology_openephys_data_mappers._dataset import find_settings_xml
from pydantic import ValidationError

EXAMPLE = Path(__file__).parent / "example_data_directory"
METADATA = "Ephys Metadata Generator 101"
RECORD_NODE = "Record Node 103"
# Expected physical associations from the ordered XML streams and hardware.
PROBES = {
    "22112107091": ("ProbeA", ProbeModel.NP_OPTO_DEMONSTRATOR),
    "22053112121": ("ProbeB", ProbeModel.NP2_QUAD_BASE),
    "23328404312": ("ProbeC", ProbeModel.NP2_QUAD_BASE),
    "12345601013": ("ProbeD", ProbeModel.NP2_MULTI_SHANK),
    "20403311554": ("ProbeE", ProbeModel.NP2_SINGLE_SHANK),
    "23299119981": ("ProbeF", ProbeModel.NP2_MULTI_SHANK),
}


def acquisition_mapper(data_dir):
    return AindAcquisitionDataMapper(
        data_dir,
        session=Session(
            subject="123456",
            experimenter=["Test Experimenter"],
            session_name="fixture-session",
        ),
        instrument_id="EPHYS-test",
    )


def instrument_mapper(data_dir, acquisition):
    return AindInstrumentDataMapper(
        data_dir,
        instrument_id="EPHYS-test",
        modification_date=date(2026, 10, 23),
        coordinate_system=CoordinateSystemLibrary.BREGMA_ARI,
        acquisition=acquisition,
    )


def snapshot(data_dir):
    return {
        p.relative_to(data_dir): p.read_bytes()
        for p in data_dir.rglob("*")
        if p.is_file()
    }


@pytest.fixture
def dataset(tmp_path):
    return Path(shutil.copytree(EXAMPLE, tmp_path / "dataset"))


@pytest.mark.parametrize(
    "filename", ["ephys_datastream_1_0.json", "ephys_datastream_2_0.json"]
)
def test_recorded_stream_schema_compatibility(filename):
    stream = DataStream.model_validate_json(
        (EXAMPLE / METADATA / filename).read_text(encoding="utf-8")
    )
    assert len(stream.configurations) == 6
    assert stream.active_devices == [
        f"Ephys_assemblyProbe{letter}" for letter in "ABCDEF"
    ]
    assert all(
        isinstance(config, EphysAssemblyConfig) for config in stream.configurations
    )
    assert DataStream.model_validate_json(stream.model_dump_json()) == stream
    for config in stream.configurations:
        assert (
            config.manipulator.local_coordinate_system
            == CoordinateSystemLibrary.MPM_MANIP_RFB
        )
        assert config.probes[0].dye == "CM-DiI"
        assert config.probes[0].transform[0].translation == [0.0, 0.0, 0.0, 0.0]


def test_recorded_acquisition_preserves_streams_and_bounds(dataset, tmp_path):
    before = snapshot(dataset)
    mapper = acquisition_mapper(dataset)
    result = mapper.run()
    expected = [
        DataStream.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted((dataset / METADATA).glob("*.json"))
    ]
    assert result.data_streams == expected
    assert result.acquisition_start_time == datetime.fromisoformat(
        "2026-10-23T14:43:15.004-07:00"
    )
    assert result.acquisition_end_time == datetime.fromisoformat(
        "2026-10-23T14:44:09.762-07:00"
    )
    assert result.subject_details is None
    assert result.acquisition_type == ""
    assert mapper.mapped is result
    assert snapshot(dataset) == before
    output = tmp_path / "output"
    output.mkdir()
    result.write_standard_file(output_directory=output)
    assert (
        Acquisition.model_validate_json(
            (output / "acquisition.json").read_text(encoding="utf-8")
        )
        == result
    )


def test_raw_instrument_fixture_requires_manipulator_names(dataset):
    acquisition = acquisition_mapper(dataset).map()
    acquisition.data_streams[0].configurations[0].manipulator.device_name = ""
    mapper = instrument_mapper(dataset, acquisition)
    with pytest.raises(ValueError, match="manipulator device names must not be blank"):
        mapper.run()
    assert not mapper.is_mapped()


def test_custom_probe_labels_do_not_override_stream_names(dataset):
    path = dataset / RECORD_NODE / "settings.xml"
    tree = ET.parse(path)
    for probe in tree.getroot().iter("NP_PROBE"):
        probe.set("custom_probe_name", "unrelated duplicate label")
    tree.write(path, encoding="utf-8")
    result = instrument_mapper(dataset, acquisition_mapper(dataset).map()).map()
    assert {
        probe.name
        for assembly in result.components
        if isinstance(assembly, EphysAssembly)
        for probe in assembly.probes
    } == {name for name, _ in PROBES.values()}


@pytest.mark.parametrize("settings_name", ["settings.xml", "settings_2.xml"])
def test_recorded_fixture_maps_hardware_and_roundtrips(
    dataset, tmp_path, settings_name
):
    # The mapper deliberately reads settings.xml, not later recording snapshots.
    if settings_name == "settings_2.xml":
        directory = dataset / RECORD_NODE
        shutil.copyfile(directory / settings_name, directory / "settings.xml")
    before = snapshot(dataset)
    acquisition = acquisition_mapper(dataset).map()
    mapper = instrument_mapper(dataset, acquisition)
    result = mapper.run()
    assemblies = [
        component
        for component in result.components
        if isinstance(component, EphysAssembly)
    ]
    stations = [
        component
        for component in result.components
        if isinstance(component, NeuropixelsBasestation)
    ]
    computers = [
        component for component in result.components if isinstance(component, Computer)
    ]
    assert (
        len(assemblies) == 6
    )  # Quad-base shank entries and repeated recording streams are deduplicated.
    assert len(computers) == 1
    assert computers[0].name == "W10DT713668"
    assert [station.slot for station in stations] == [2, 4, 5]
    assert result.instrument_id == acquisition.instrument_id
    assert mapper.mapped is result
    assert {
        probe.serial_number: (probe.name, probe.probe_model)
        for assembly in assemblies
        for probe in assembly.probes
    } == PROBES
    assert {assembly.name for assembly in assemblies} == set(
        acquisition.data_streams[0].active_devices
    )
    assert {assembly.manipulator.name for assembly in assemblies} == {
        "SN20190",
        "SN20189",
        "SN20188",
        "SN20187",
        "SN20192",
        "SN20191",
    }
    assert {
        probe for station in stations for port in station.ports for probe in port.probes
    } == {name for name, _ in PROBES.values()}
    assert len(result.connections) == 3
    assert all(
        connection.target_device == computers[0].name
        for connection in result.connections
    )
    assert snapshot(dataset) == before
    output = tmp_path / "output"
    output.mkdir()
    result.write_standard_file(output_directory=output)
    assert (
        Instrument.model_validate_json(
            (output / "instrument.json").read_text(encoding="utf-8")
        )
        == result
    )


def test_invalid_stream_refresh_clears_instrument_cache(dataset):
    mapper = instrument_mapper(dataset, acquisition_mapper(dataset).map())
    mapper.run()
    path = dataset / RECORD_NODE / "settings.xml"
    tree = ET.parse(path)
    processor = tree.getroot().find("./SIGNALCHAIN/PROCESSOR")
    processor.remove(processor.findall("STREAM")[-1])
    tree.write(path, encoding="utf-8")
    with pytest.raises(ValueError, match="Expected .* streams"):
        mapper.run()
    assert not mapper.is_mapped()
    with pytest.raises(ValueError, match="not yet mapped"):
        mapper.rig_schema()


def test_later_snapshot_is_not_selected(dataset):
    selected = dataset / RECORD_NODE / "settings.xml"
    assert find_settings_xml(dataset) == selected
    selected.unlink()
    assert (dataset / RECORD_NODE / "settings_2.xml").is_file()
    with pytest.raises(FileNotFoundError, match="Record Node/settings"):
        find_settings_xml(dataset)


@pytest.mark.parametrize("field", ["stream_start_time", "stream_end_time"])
def test_recorded_fixture_rejects_naive_timestamps_and_clears_cache(dataset, field):
    mapper = acquisition_mapper(dataset)
    mapper.run()
    path = dataset / METADATA / "ephys_datastream_1_0.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata[field] = (
        datetime.fromisoformat(metadata[field]).replace(tzinfo=None).isoformat()
    )
    path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValidationError):
        mapper.run()
    assert not mapper.is_mapped()
