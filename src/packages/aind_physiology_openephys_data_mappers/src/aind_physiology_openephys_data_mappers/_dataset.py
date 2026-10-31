"""Discover metadata in a saved Open Ephys dataset without scanning recordings."""

import re
from pathlib import Path


def _node_directories(data_dir: Path, prefix: str) -> list[Path]:
    if not data_dir.exists():
        raise FileNotFoundError(f"Open Ephys data directory not found: {data_dir}")
    if not data_dir.is_dir():
        raise NotADirectoryError(f"Open Ephys data path is not a directory: {data_dir}")
    return sorted(
        path for path in data_dir.iterdir() if path.is_dir() and re.fullmatch(rf"{re.escape(prefix)} \d+", path.name)
    )


def find_settings_xml(data_dir: Path) -> Path:
    """Return the first settings.xml in filename-sorted Record Node directories."""
    for directory in _node_directories(data_dir, "Record Node"):
        path = directory / "settings.xml"
        if path.is_file():
            return path
    raise FileNotFoundError(f"No Record Node/settings.xml found in {data_dir}")


def find_metadata_directory(data_dir: Path) -> Path:
    """Find the unique saved Ephys Metadata Generator directory."""
    directories = _node_directories(data_dir, "Ephys Metadata Generator")
    if not directories:
        raise FileNotFoundError(f"No Ephys Metadata Generator directory found in {data_dir}")
    if len(directories) > 1:
        names = ", ".join(path.name for path in directories)
        raise ValueError(f"Multiple Ephys Metadata Generator directories found in {data_dir}: {names}")
    return directories[0]
