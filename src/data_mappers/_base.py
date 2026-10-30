"""Shared mapper lifecycle without orchestration-framework dependencies."""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")


class DataMapper(ABC, Generic[T]):
    """Provide execution and cached-result access for metadata mappers."""

    _mapped: T | None = None

    @abstractmethod
    def map(self) -> T:
        """Map fresh source data, clearing stale results before each attempt."""

    def run(self) -> T:
        """Execute mapping and return the cached result."""
        self._mapped = self.map()
        return self._mapped

    def is_mapped(self) -> bool:
        """Return whether a successful mapping result is available."""
        return self._mapped is not None

    @property
    def mapped(self) -> T:
        """Return the cached result, raising if mapping has not succeeded."""
        if self._mapped is None:
            raise ValueError("Data not yet mapped")
        return self._mapped
