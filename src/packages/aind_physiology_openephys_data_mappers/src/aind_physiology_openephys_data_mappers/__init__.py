import logging
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, CliApp

from ._acquisition import AindAcquisitionDataMapper
from ._instrument import AindInstrumentDataMapper

__all__ = ["AindAcquisitionDataMapper", "AindInstrumentDataMapper"]

logger = logging.getLogger(__name__)

class DataMapperCli(BaseSettings, cli_kebab_case=True):
    data_path: os.PathLike = Field(description="Path to the session data directory.")

    def cli_cmd(self):
        """Generate aind-data-schema metadata for the Open Ephys dataset located at the specified path."""
        raise NotImplementedError(f"Data mapping is not yet implemented for {Path(self.data_path)}")


def main() -> None:
    """Run the Open Ephys data mapper command-line interface."""
    CliApp().run(DataMapperCli)


__all__ = ["DataMapperCli", "main"]
