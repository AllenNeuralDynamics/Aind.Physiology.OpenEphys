"""Mapper lifecycle and independence from CLABE."""

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from data_mappers._base import DataMapper


class ExampleMapper(DataMapper[list[int]]):
    """Minimal mapper implementing the fresh-result and invalidation contract."""

    def __init__(self):
        self.value = 1
        self.fail = False

    def map(self):
        self._mapped = None
        if self.fail:
            raise ValueError("Mapping failed")
        self._mapped = [self.value]
        return self._mapped


def test_unmapped_result_and_abstract_interface():
    with pytest.raises(TypeError):
        DataMapper()
    mapper = ExampleMapper()
    assert not mapper.is_mapped()
    with pytest.raises(ValueError, match="not yet mapped"):
        _ = mapper.mapped


def test_run_refreshes_results_and_instances_are_independent():
    mapper = ExampleMapper()
    other = ExampleMapper()
    first = mapper.run()
    assert first == [1]
    assert mapper.mapped is first
    assert mapper.is_mapped()
    assert not other.is_mapped()

    mapper.value = 2
    second = mapper.run()
    assert second == [2]
    assert second is mapper.mapped
    assert second is not first


def test_run_failure_does_not_expose_stale_results():
    mapper = ExampleMapper()
    mapper.run()
    mapper.fail = True
    with pytest.raises(ValueError, match="Mapping failed"):
        mapper.run()
    assert not mapper.is_mapped()
    with pytest.raises(ValueError, match="not yet mapped"):
        _ = mapper.mapped


def test_real_mappers_run_without_clabe():
    root = Path(__file__).resolve().parents[1]
    script = dedent(
        """
        import importlib.abc
        import sys

        class BlockClabe(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "clabe" or fullname.startswith("clabe."):
                    raise AssertionError(f"Unexpected CLABE import: {fullname}")

        sys.meta_path.insert(0, BlockClabe())
        sys.path.insert(0, "src")

        import pytest

        result = pytest.main([
            "tests/test_acquisition.py::test_mapping_preserves_metadata_and_filename_order",
            "tests/test_instrument.py::test_saved_settings_refresh_and_invalidate_cache",
            "-q",
            "--disable-warnings",
        ])
        assert not any(name == "clabe" or name.startswith("clabe.") for name in sys.modules)
        sys.exit(result)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
