"""Instrument mapper tests; no live hardware is contacted."""

from datetime import date
from pathlib import Path
from unittest.mock import Mock
from xml.etree import ElementTree as ET

import pytest
from aind_behavior_services.session import Session
from aind_data_schema.components.coordinates import CoordinateSystemLibrary
from aind_data_schema.components.devices import (
    Computer,
    EphysAssembly,
    NeuropixelsBasestation,
)
from aind_data_schema.core.acquisition import (
    Acquisition,
    AcquisitionSubjectDetails,
    DataStream,
)
from aind_data_schema.core.instrument import Instrument
from aind_data_schema_models.devices import ProbeModel
from aind_data_schema_models.organizations import Organization
from aind_physiology_openephys_data_mappers import (
    AindAcquisitionDataMapper,
    AindInstrumentDataMapper,
)

EXAMPLE = Path(__file__).parents[1] / "src" / "example.xml"


@pytest.fixture
def root():
    return ET.parse(EXAMPLE).getroot()


@pytest.fixture
def data_dir(tmp_path):
    node = tmp_path / "Record Node 103"
    node.mkdir()
    (node / "settings.xml").write_bytes(EXAMPLE.read_bytes())
    return tmp_path


def assembly_config(probe_name):
    coordinate_system = CoordinateSystemLibrary.MPM_MANIP_RFB.model_dump(mode="json")
    return {
        "object_type": "Ephys assembly config",
        "device_name": f"Recorded assembly {probe_name}",
        "manipulator": {
            "device_name": f"Manipulator {probe_name}",
            "local_coordinate_system": coordinate_system,
            "local_axis_positions": {
                "object_type": "Translation",
                "translation": [0.0, 0.0, 0.0],
            },
        },
        "probes": [
            {
                "device_name": probe_name,
                "primary_targeted_structure": {
                    "atlas": "CCFv3",
                    "name": "root",
                    "acronym": "root",
                    "id": "997",
                },
                "local_coordinate_system": coordinate_system,
                "transform": [
                    {"object_type": "Translation", "translation": [0.0, 0.0, 0.0]}
                ],
            }
        ],
    }


@pytest.fixture
def acquisition(root):
    probe_names = dict.fromkeys(
        entry.get("custom_probe_name") for entry in root.iter("NP_PROBE")
    )
    stream = DataStream(
        stream_start_time="2026-10-23T14:43:15-07:00",
        stream_end_time="2026-10-23T14:44:09-07:00",
        modalities=[
            {"name": "Extracellular electrophysiology", "abbreviation": "ecephys"}
        ],
        active_devices=[f"Recorded assembly {name}" for name in probe_names],
        configurations=[assembly_config(name) for name in probe_names],
    )
    return Acquisition(
        subject_id="123456",
        experimenters=["Test Experimenter"],
        acquisition_start_time=stream.stream_start_time,
        acquisition_end_time=stream.stream_end_time,
        acquisition_type="test acquisition",
        instrument_id="EPHYS-test",
        subject_details=AcquisitionSubjectDetails(mouse_platform_name="Running Wheel"),
        data_streams=[stream],
    )


@pytest.fixture
def options(acquisition, data_dir):
    return {
        "data_dir": data_dir,
        "instrument_id": "EPHYS-test",
        "modification_date": date(2026, 10, 23),
        "coordinate_system": CoordinateSystemLibrary.BREGMA_ARI,
        "location": "test room",
        "session_name": "test-session",
        "acquisition": acquisition,
    }


def test_example_hardware_and_roundtrip(options):
    mapper = AindInstrumentDataMapper(**options)
    assert not mapper.is_mapped()
    assert mapper.session_name == "test-session"
    with pytest.raises(ValueError, match="not yet mapped"):
        mapper.rig_schema()

    result = mapper.map()
    assert mapper.is_mapped()
    assert mapper.mapped is result
    assert mapper.rig_schema() is result
    assert result.instrument_id == "EPHYS-test"
    assert result.location == "test room"
    assert result.modification_date == date(2026, 10, 23)
    assemblies = [c for c in result.components if isinstance(c, EphysAssembly)]
    stations = [c for c in result.components if isinstance(c, NeuropixelsBasestation)]
    computers = [c for c in result.components if isinstance(c, Computer)]
    assert len(assemblies) == 7
    assert [s.slot for s in stations] == [3, 4, 7]
    assert len(computers) == 1
    assert computers[0].name == "W10DT713882"
    assert computers[0].operating_system == "Windows 11"
    assert assemblies[0].name == "Recorded assembly 50198"
    assert assemblies[0].probes[0].serial_number == "20403319764"
    assert assemblies[0].probes[0].model == "NP2000"
    assert assemblies[0].manipulator.name == "Manipulator 50198"
    assert assemblies[0].manipulator.manufacturer == Organization.UNKNOWN
    assert assemblies[0].manipulator.serial_number is None
    quad = next(a for a in assemblies if a.probes[0].serial_number == "23207205101")
    assert quad.probes[0].probe_model == ProbeModel.NP2_QUAD_BASE
    assert stations[-1].ports[0].probes == ["50213"]
    assert stations[0].basestation_firmware_version == "3.0226"
    assert stations[0].bsc_firmware_version == "4.0233"
    assert stations[0].serial_number is None
    assert (
        stations[0].additional_settings.model_dump()["bsc_serial_number"] == "23131294"
    )
    assert len(result.connections) == 3
    assert all(c.target_device == computers[0].name for c in result.connections)
    assert Instrument.model_validate_json(result.model_dump_json()) == result


def test_saved_settings_refresh_and_invalidate_cache(options, monkeypatch):
    writer = Mock(side_effect=AssertionError("must not write metadata"))
    monkeypatch.setattr(Instrument, "write_standard_file", writer)
    mapper = AindInstrumentDataMapper(**options)
    assert mapper.run() is mapper.mapped
    path = options["data_dir"] / "Record Node 103" / "settings.xml"
    root = ET.parse(path).getroot()
    root.find("INFO/MACHINE").set("name", "Saved computer")
    ET.ElementTree(root).write(path)
    result = mapper.map()
    assert any(
        isinstance(c, Computer) and c.name == "Saved computer"
        for c in result.components
    )
    path.write_text("<SETTINGS", encoding="utf-8")
    with pytest.raises(ET.ParseError):
        mapper.map()
    assert not mapper.is_mapped()
    writer.assert_not_called()


@pytest.mark.parametrize("argument", ["app", "xml_path"])
def test_old_source_arguments_are_rejected(options, argument):
    with pytest.raises(TypeError, match=argument):
        AindInstrumentDataMapper(**options, **{argument: EXAMPLE})


def test_missing_session_name(options):
    options.pop("session_name")
    mapper = AindInstrumentDataMapper(**options)
    with pytest.raises(ValueError, match="Session name"):
        _ = mapper.session_name
    mapper.map()


def test_missing_manipulator_association(options):
    options["acquisition"].data_streams[0].configurations.pop(0)
    with pytest.raises(ValueError, match="No acquisition manipulator association"):
        AindInstrumentDataMapper(**options).map()


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [
        ("probe_serial_number", "", "required attribute"),
        ("probe_serial_number", "0", "known, nonzero"),
        ("probe_name", "new unsupported model", "Unsupported probe model"),
        ("slot", "0", "must be positive"),
        ("port", "not an int", "invalid literal"),
        ("probe_part_number", "", "required attribute"),
    ],
)
def test_invalid_probe(root, options, tmp_path, attribute, value, message):
    next(root.iter("NP_PROBE")).set(attribute, value)
    path = options["data_dir"] / "Record Node 103" / "settings.xml"
    ET.ElementTree(root).write(path)
    with pytest.raises(ValueError, match=message):
        AindInstrumentDataMapper(**options).map()


def test_conflicting_duplicate(root, options, tmp_path):
    quad_entries = [
        p
        for p in root.iter("NP_PROBE")
        if p.get("probe_serial_number") == "23207205101"
    ]
    quad_entries[-1].set("probe_part_number", "conflicting")
    path = options["data_dir"] / "Record Node 103" / "settings.xml"
    ET.ElementTree(root).write(path)
    with pytest.raises(ValueError, match="Conflicting hardware"):
        AindInstrumentDataMapper(**options).map()


def test_conflicting_basestation(root, options, tmp_path):
    list(root.iter("NP_PROBE"))[1].set("bs_firmware_version", "different")
    path = options["data_dir"] / "Record Node 103" / "settings.xml"
    ET.ElementTree(root).write(path)
    with pytest.raises(ValueError, match="Conflicting basestation"):
        AindInstrumentDataMapper(**options).map()


def test_two_probes_on_same_port_different_docks(root, options, tmp_path):
    entries = list(root.iter("NP_PROBE"))
    entries[1].set("port", entries[0].get("port"))
    entries[1].set("dock", "2")
    path = options["data_dir"] / "Record Node 103" / "settings.xml"
    ET.ElementTree(root).write(path)
    result = AindInstrumentDataMapper(**options).map()
    station = next(
        c for c in result.components if isinstance(c, NeuropixelsBasestation)
    )
    assert station.ports[0].probes == ["50198", "50210"]


def test_disabled_hardware_is_included(root, options, tmp_path):
    next(root.iter("NP_PROBE")).set("isEnabled", "0")
    path = options["data_dir"] / "Record Node 103" / "settings.xml"
    ET.ElementTree(root).write(path)
    result = AindInstrumentDataMapper(**options).map()
    assert len([c for c in result.components if isinstance(c, EphysAssembly)]) == 7


@pytest.mark.parametrize(
    "xml",
    [
        "<WRONG/>",
        "<SETTINGS/>",
        "<SETTINGS><INFO><MACHINE name='pc'/></INFO></SETTINGS>",
    ],
)
def test_missing_xml_structure(xml, options, tmp_path):
    path = options["data_dir"] / "Record Node 103" / "settings.xml"
    path.write_text(xml)
    with pytest.raises(ValueError):
        AindInstrumentDataMapper(**options).map()


def test_malformed_xml(options, tmp_path):
    path = options["data_dir"] / "Record Node 103" / "settings.xml"
    path.write_text("<SETTINGS")
    with pytest.raises(ET.ParseError):
        AindInstrumentDataMapper(**options).map()


def test_duplicate_probe_name(root, options, tmp_path):
    streams = root.findall("./SIGNALCHAIN/PROCESSOR/STREAM")
    streams[1].set("name", streams[0].get("name"))
    path = options["data_dir"] / "Record Node 103" / "settings.xml"
    ET.ElementTree(root).write(path)
    with pytest.raises(ValueError, match="Duplicate hardware name"):
        AindInstrumentDataMapper(**options).map()


def test_repeated_stream_configs_and_changed_positions(options):
    acquisition = options["acquisition"]
    repeated = acquisition.data_streams[0].model_copy(deep=True)
    repeated.configurations[0].manipulator.local_axis_positions.translation[0] = 1.0
    acquisition.data_streams.append(repeated)
    before = acquisition.model_dump_json()
    result = AindInstrumentDataMapper(**options).map()
    assert len([c for c in result.components if isinstance(c, EphysAssembly)]) == 7
    assert acquisition.model_dump_json() == before


def test_multiple_probes_share_acquisition_assembly(options):
    configs = options["acquisition"].data_streams[0].configurations
    configs[0].probes.extend(configs[1].probes)
    configs.pop(1)
    result = AindInstrumentDataMapper(**options).map()
    assemblies = [c for c in result.components if isinstance(c, EphysAssembly)]
    assert len(assemblies) == 6
    assert [p.name for p in assemblies[0].probes] == ["50198", "50210"]
    assert assemblies[0].manipulator.name == "Manipulator 50198"
    assert Instrument.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("field", ["manipulator", "assembly"])
def test_conflicting_acquisition_associations(options, field):
    acquisition = options["acquisition"]
    repeated = acquisition.data_streams[0].model_copy(deep=True)
    if field == "manipulator":
        repeated.configurations[0].manipulator.device_name = "Another manipulator"
    else:
        repeated.configurations[0].device_name = "Another assembly"
    acquisition.data_streams.append(repeated)
    with pytest.raises(ValueError, match="Conflicting acquisition"):
        AindInstrumentDataMapper(**options).map()


@pytest.mark.parametrize("field", ["manipulator", "assembly", "probe"])
def test_blank_acquisition_device_names(options, field):
    config = options["acquisition"].data_streams[0].configurations[0]
    if field == "manipulator":
        config.manipulator.device_name = " "
    elif field == "assembly":
        config.device_name = " "
    else:
        config.probes[0].device_name = " "
    with pytest.raises(ValueError, match="must not be blank"):
        AindInstrumentDataMapper(**options).map()


def test_unrelated_configurations_are_ignored(options):
    configs = options["acquisition"].data_streams[0].configurations
    configs.append(configs[0].manipulator.model_copy(deep=True))
    result = AindInstrumentDataMapper(**options).map()
    assert len([c for c in result.components if isinstance(c, EphysAssembly)]) == 7


def test_acquisition_probe_names_must_match_xml(options):
    options["acquisition"].data_streams[0].configurations[0].probes[
        0
    ].device_name = "Not the XML name"
    with pytest.raises(ValueError, match="No acquisition manipulator association"):
        AindInstrumentDataMapper(**options).map()


def test_stream_name_is_used_when_custom_probe_name_is_empty(root, options, tmp_path):
    entry = next(root.iter("NP_PROBE"))
    entry.set("custom_probe_name", "")
    path = options["data_dir"] / "Record Node 103" / "settings.xml"
    ET.ElementTree(root).write(path)
    result = AindInstrumentDataMapper(**options).map()
    assembly = next(c for c in result.components if isinstance(c, EphysAssembly))
    assert assembly.probes[0].name == "50198"
    assert assembly.manipulator.name == "Manipulator 50198"


def test_acquisition_associations_refresh_and_invalidate_cache(options):
    mapper = AindInstrumentDataMapper(**options)
    mapper.map()
    config = options["acquisition"].data_streams[0].configurations[0]
    config.manipulator.device_name = "Updated manipulator"
    result = mapper.map()
    assembly = next(c for c in result.components if isinstance(c, EphysAssembly))
    assert assembly.manipulator.name == "Updated manipulator"
    config.manipulator.device_name = ""
    with pytest.raises(ValueError, match="must not be blank"):
        mapper.map()
    assert not mapper.is_mapped()
    with pytest.raises(ValueError, match="not yet mapped"):
        mapper.rig_schema()


def test_both_mappers_use_saved_dataset(options):
    data_dir = options["data_dir"]
    metadata_dir = data_dir / "Ephys Metadata Generator 101"
    metadata_dir.mkdir()
    stream = options["acquisition"].data_streams[0]
    (metadata_dir / "ephys_datastream_1_0.json").write_text(
        stream.model_dump_json(), encoding="utf-8"
    )
    acquisition = AindAcquisitionDataMapper(
        data_dir,
        session=Session(subject="123456", experimenter=["Test Experimenter"]),
        instrument_id="EPHYS-test",
        acquisition_type="test acquisition",
    ).map()
    options["acquisition"] = acquisition
    result = AindInstrumentDataMapper(**options).map()
    assemblies = [c for c in result.components if isinstance(c, EphysAssembly)]
    assert len(assemblies) == 7
    assert assemblies[0].manipulator.name == "Manipulator 50198"


def test_malformed_first_settings_does_not_fall_through(options):
    node = options["data_dir"] / "Record Node 100"
    node.mkdir()
    (node / "settings.xml").write_text("<SETTINGS", encoding="utf-8")
    with pytest.raises(ET.ParseError):
        AindInstrumentDataMapper(**options).map()
