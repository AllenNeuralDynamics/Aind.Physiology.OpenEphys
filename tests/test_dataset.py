"""Saved dataset discovery must be deterministic and bounded to the dataset."""

import pytest
from aind_physiology_openephys_data_mappers._dataset import (
    find_metadata_directory,
    find_settings_xml,
)


@pytest.mark.parametrize("finder", [find_metadata_directory, find_settings_xml])
def test_invalid_dataset_root(finder, tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        finder(tmp_path / "missing")
    path = tmp_path / "not-a-directory"
    path.write_text("file", encoding="utf-8")
    with pytest.raises(NotADirectoryError, match="not a directory"):
        finder(path)


def test_settings_first_available_in_sorted_record_nodes(tmp_path):
    first = tmp_path / "Record Node 100"
    first.mkdir()
    (first / "settings_2.xml").write_text("not the settings", encoding="utf-8")
    later = tmp_path / "Record Node 103"
    later.mkdir()
    (later / "settings.xml").write_text("saved settings", encoding="utf-8")
    last = tmp_path / "Record Node 104"
    last.mkdir()
    (last / "settings.xml").write_text("different settings", encoding="utf-8")
    (tmp_path / "settings.xml").write_text("unrelated settings", encoding="utf-8")
    assert find_settings_xml(tmp_path) == later / "settings.xml"


def test_missing_settings_rejects_root_and_nested_snapshots(tmp_path):
    (tmp_path / "settings.xml").write_text("wrong location", encoding="utf-8")
    nested = tmp_path / "Record Node 103" / "experiment1"
    nested.mkdir(parents=True)
    (nested / "settings.xml").write_text("wrong location", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match=r"Record Node/settings\.xml"):
        find_settings_xml(tmp_path)


def test_metadata_generator_discovery(tmp_path):
    directory = tmp_path / "Ephys Metadata Generator 101"
    directory.mkdir()
    (tmp_path / "Ephys Metadata Generator backup").mkdir()
    assert find_metadata_directory(tmp_path) == directory


def test_missing_generator_is_not_a_recursive_search(tmp_path):
    (tmp_path / "nested" / "Ephys Metadata Generator 101").mkdir(parents=True)
    (tmp_path / "Ephys Metadata Generator backup").mkdir()
    with pytest.raises(FileNotFoundError, match="No Ephys Metadata Generator"):
        find_metadata_directory(tmp_path)


def test_multiple_metadata_generators_are_ambiguous(tmp_path):
    (tmp_path / "Ephys Metadata Generator 101").mkdir()
    (tmp_path / "Ephys Metadata Generator 102").mkdir()
    with pytest.raises(ValueError, match="Multiple Ephys Metadata Generator"):
        find_metadata_directory(tmp_path)
