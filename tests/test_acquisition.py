"""Acquisition mapping from saved Open Ephys datasets only."""

import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from aind_behavior_services.session import Session
from aind_data_schema.components.configs import ManipulatorConfig
from aind_data_schema.components.coordinates import CoordinateSystemLibrary
from aind_data_schema.core.acquisition import (
    Acquisition,
    AcquisitionSubjectDetails,
    StimulusEpoch,
)
from aind_physiology_openephys_data_mappers import AindAcquisitionDataMapper
from pydantic import ValidationError

# aind-data-schema 2.9 renamed the configurations' coordinate_system to local_coordinate_system
LOCAL_CS = (
    "local_coordinate_system"
    if "local_coordinate_system" in ManipulatorConfig.model_fields
    else "coordinate_system"
)


def stream(start="2026-10-22T16:00:00Z", end="2026-10-22T16:05:00Z"):
    return {
        "object_type": "Data stream",
        "stream_start_time": start,
        "stream_end_time": end,
        "modalities": [
            {"name": "Extracellular electrophysiology", "abbreviation": "ecephys"}
        ],
        "active_devices": ["manipulatorA"],
        "configurations": [
            {
                "object_type": "Manipulator config",
                "device_name": "manipulatorA",
                LOCAL_CS: CoordinateSystemLibrary.MPM_MANIP_RFB.model_dump(mode="json"),
                "local_axis_positions": {
                    "object_type": "Translation",
                    "translation": [0.0, 0.0, 0.0],
                },
            }
        ],
        "connections": [],
        "notes": "metadata from the plugin",
    }


@pytest.fixture
def metadata_dir(tmp_path):
    directory = tmp_path / "Ephys Metadata Generator 101"
    directory.mkdir()
    (directory / "ephys_datastream_1_0.json").write_text(
        json.dumps(stream()), encoding="utf-8"
    )
    return directory


@pytest.fixture
def options():
    return {
        "session": Session(
            subject="123456",
            experimenter=["Test Experimenter"],
            session_name="test-session",
            notes="session notes",
        ),
        "instrument_id": "test-instrument",
        "acquisition_type": "test acquisition",
    }


@pytest.fixture
def mapper(metadata_dir, options):
    return AindAcquisitionDataMapper(data_dir=str(metadata_dir.parent), **options)


def test_lifecycle_before_mapping(mapper):
    assert not mapper.is_mapped()
    assert mapper.session_name == "test-session"
    with pytest.raises(ValueError, match="not yet mapped"):
        _ = mapper.mapped
    with pytest.raises(ValueError, match="not yet mapped"):
        mapper.session_schema()


def test_mapping_preserves_metadata_and_filename_order(
    mapper, metadata_dir, monkeypatch
):
    later = stream("2026-10-22T17:00:00Z", "2026-10-22T17:05:00Z")
    (metadata_dir / "a.JSON").write_text(json.dumps(later), encoding="utf-8-sig")
    (metadata_dir / "notes.txt").write_text("not metadata", encoding="utf-8")
    (metadata_dir / "nested").mkdir()
    (metadata_dir / "nested" / "ignored.json").write_text("invalid", encoding="utf-8")
    (metadata_dir.parent / "unrelated.json").write_text("invalid", encoding="utf-8")
    writer = Mock(side_effect=AssertionError("mapping must not write files"))
    monkeypatch.setattr(Acquisition, "write_standard_file", writer)
    mapper.ethics_review_id = ["test-protocol"]
    mapper.coordinate_system = CoordinateSystemLibrary.BREGMA_RAS
    before = {p: p.read_bytes() for p in metadata_dir.rglob("*") if p.is_file()}

    result = mapper.run()

    assert result is mapper.mapped
    assert result is mapper.session_schema()
    assert result.subject_id == "123456"
    assert result.experimenters == ["Test Experimenter"]
    assert result.notes == "session notes"
    assert result.instrument_id == "test-instrument"
    assert result.acquisition_type == "test acquisition"
    assert result.subject_details is None
    assert result.ethics_review_id == ["test-protocol"]
    assert result.coordinate_system == CoordinateSystemLibrary.BREGMA_RAS
    assert [s.stream_start_time.hour for s in result.data_streams] == [17, 16]
    assert result.acquisition_start_time == datetime(2026, 10, 22, 16, tzinfo=UTC)
    assert result.acquisition_end_time == datetime(2026, 10, 22, 17, 5, tzinfo=UTC)
    assert result.data_streams[0].active_devices == ["manipulatorA"]
    assert result.data_streams[0].configurations[0].device_name == "manipulatorA"
    assert Acquisition.model_validate_json(result.model_dump_json()) == result
    assert {p: p.read_bytes() for p in metadata_dir.rglob("*") if p.is_file()} == before
    writer.assert_not_called()


def test_optional_metadata_defaults(mapper):
    result = mapper.map()
    assert result.coordinate_system is None
    assert result.ethics_review_id is None
    assert result.stimulus_epochs == []


def test_acquisition_type_defaults_to_empty(metadata_dir, options):
    options.pop("acquisition_type")
    mapper = AindAcquisitionDataMapper(metadata_dir.parent, **options)
    assert mapper.acquisition_type == ""
    assert mapper.map().acquisition_type == ""


@pytest.mark.skipif(
    "global_coordinate_system" not in Acquisition.model_fields,
    reason="merging only fills an empty acquisition_type from aind-data-schema 2.9",
)
@pytest.mark.parametrize("behavior_first", [False, True])
def test_empty_acquisition_type_inherits_from_behavior(
    metadata_dir, options, behavior_first
):
    options.pop("acquisition_type")
    ephys = AindAcquisitionDataMapper(metadata_dir.parent, **options).map()
    behavior_data = ephys.model_dump()
    behavior_data.update(
        acquisition_type="VrForaging",
        subject_details=AcquisitionSubjectDetails(mouse_platform_name="Running Wheel"),
        data_streams=[],
    )
    behavior = Acquisition.model_validate(behavior_data)

    merged = behavior + ephys if behavior_first else ephys + behavior

    assert merged.acquisition_type == "VrForaging"
    assert merged.instrument_id == options["instrument_id"]
    assert ephys.subject_details is None
    assert merged.subject_details == behavior.subject_details
    assert merged.subject_details.mouse_platform_name == "Running Wheel"


def test_subject_details_input_is_rejected(metadata_dir, options):
    with pytest.raises(TypeError, match="subject_details"):
        AindAcquisitionDataMapper(
            metadata_dir.parent,
            **options,
            subject_details=AcquisitionSubjectDetails(
                mouse_platform_name="Running Wheel"
            ),
        )


def test_instrument_id_can_be_supplied_positionally(metadata_dir, options):
    session = options.pop("session")
    instrument_id = options.pop("instrument_id")
    options.pop("acquisition_type")
    mapper = AindAcquisitionDataMapper(
        metadata_dir.parent, session, instrument_id, **options
    )
    assert mapper.instrument_id == instrument_id
    assert mapper.acquisition_type == ""

    result = mapper.map()
    assert result.instrument_id == instrument_id
    assert result.acquisition_type == ""


def test_instrument_id_defaults_to_the_saved_rig(metadata_dir, options):
    options.pop("instrument_id")
    with pytest.raises(FileNotFoundError, match="rig_input.json"):
        AindAcquisitionDataMapper(metadata_dir.parent, **options)


def test_empty_instrument_id_is_rejected_during_mapping(metadata_dir, options):
    options["instrument_id"] = ""
    mapper = AindAcquisitionDataMapper(metadata_dir.parent, **options)
    with pytest.raises(ValidationError, match="instrument_id is required"):
        mapper.map()
    assert not mapper.is_mapped()


def test_supplied_stimulus_epochs(mapper):
    epoch = StimulusEpoch(
        stimulus_start_time="2026-10-22T16:00:00Z",
        stimulus_end_time="2026-10-22T16:05:00Z",
        stimulus_name="visual stimulus",
        stimulus_modalities=["Visual"],
    )
    mapper.stimulus_epochs = [epoch]
    assert mapper.map().stimulus_epochs == [epoch]


def test_missing_session_name(mapper):
    mapper.session_model.session_name = None
    with pytest.raises(ValueError, match="Session name"):
        _ = mapper.session_name


@pytest.mark.parametrize("argument", ["app", "processor_id", "metadata_dir"])
def test_old_source_arguments_are_rejected(metadata_dir, options, argument):
    with pytest.raises(TypeError, match=argument):
        AindAcquisitionDataMapper(
            data_dir=metadata_dir.parent, **options, **{argument: metadata_dir}
        )


def test_empty_metadata_directory(tmp_path, options):
    (tmp_path / "Ephys Metadata Generator 101").mkdir()
    mapper = AindAcquisitionDataMapper(tmp_path, **options)
    with pytest.raises(ValueError, match="No JSON metadata files"):
        mapper.map()
    assert not mapper.is_mapped()


@pytest.mark.parametrize("content", ["{", "[]", "null", "1", '"text"'])
def test_invalid_json_file(mapper, metadata_dir, content):
    (metadata_dir / "bad.json").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="bad.json"):
        mapper.map()
    assert not mapper.is_mapped()


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        stream(end=None),
        stream(end="not a datetime"),
        {**stream(), "configurations": []},
    ],
)
def test_invalid_stream_schema(mapper, metadata_dir, metadata):
    (metadata_dir / "ephys_datastream_1_0.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    with pytest.raises(ValidationError):
        mapper.map()
    assert not mapper.is_mapped()


def test_naive_timestamps_use_schema_timezone(mapper, metadata_dir):
    (metadata_dir / "ephys_datastream_1_0.json").write_text(
        json.dumps(stream(start="2026-10-22T16:00:00", end="2026-10-22T16:05:00")),
        encoding="utf-8",
    )

    result = mapper.map()

    assert result.acquisition_start_time.replace(tzinfo=None) == datetime(
        2026, 10, 22, 16
    )
    assert result.acquisition_end_time.replace(tzinfo=None) == datetime(
        2026, 10, 22, 16, 5
    )
    assert result.acquisition_start_time.utcoffset() is not None
    assert result.acquisition_end_time.utcoffset() is not None


def test_reversed_time_bounds_are_rejected(mapper, metadata_dir):
    path = metadata_dir / "ephys_datastream_1_0.json"
    path.write_text(
        json.dumps(stream(end="1969-12-31T16:00:00-08:00")), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="ends before it starts"):
        mapper.map()


@pytest.mark.skipif(
    LOCAL_CS == "coordinate_system",
    reason="the field is only renamed from aind-data-schema 2.9",
)
def test_plugin_coordinate_system_field(mapper, metadata_dir):
    metadata = stream()
    config = metadata["configurations"][0]
    config["coordinate_system"] = config.pop("local_coordinate_system")
    (metadata_dir / "ephys_datastream_1_0.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    result = mapper.map()
    assert (
        result.data_streams[0].configurations[0].local_coordinate_system
        == CoordinateSystemLibrary.MPM_MANIP_RFB
    )


def test_directory_refresh_and_cache_invalidation(mapper, metadata_dir):
    path = metadata_dir / "ephys_datastream_1_0.json"
    first = mapper.map()
    path.write_text(json.dumps(stream(end="2026-10-22T16:10:00Z")), encoding="utf-8")
    second = mapper.map()
    assert second is not first
    assert second.acquisition_end_time.minute == 10
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="ephys_datastream_1_0.json"):
        mapper.map()
    assert not mapper.is_mapped()
    with pytest.raises(ValueError, match="not yet mapped"):
        _ = mapper.mapped
