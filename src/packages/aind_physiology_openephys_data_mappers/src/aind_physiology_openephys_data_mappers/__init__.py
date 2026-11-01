import logging
import os
from pathlib import Path

from aind_physiology_openephys.app import AindBehaviorServicesOpenEphysApp
from pydantic import Field
from pydantic_settings import BaseSettings, CliApp

from ._acquisition import AindAcquisitionDataMapper
from ._instrument import AindInstrumentDataMapper

logger = logging.getLogger(__name__)


class DataMapperCli(BaseSettings, cli_kebab_case=True):
    data_path: os.PathLike = Field(description="Path to the session directory, which contains the ecephys directory.")

    def cli_cmd(self):
        """Generate aind-data-schema metadata for the Open Ephys session located at the specified path.

        Reads the rig and session saved in ``ecephys/Logs``, uses the rig name as the instrument ID, and writes
        ``ecephys_acquisition.json`` and ``ecephys_instrument.json`` to the session directory.
        """
        session_directory = Path(self.data_path)
        data_dir = session_directory / AindBehaviorServicesOpenEphysApp.MODALITY

        acquisition = AindAcquisitionDataMapper(data_dir).map()
        acquisition.write_standard_file(
            output_directory=session_directory, prefix=AindBehaviorServicesOpenEphysApp.MODALITY
        )
        instrument = AindInstrumentDataMapper(data_dir, acquisition=acquisition).map()
        instrument.write_standard_file(
            output_directory=session_directory, prefix=AindBehaviorServicesOpenEphysApp.MODALITY
        )
        logger.info("Open Ephys metadata written to %s", session_directory)


def main() -> None:
    """Run the Open Ephys data mapper command-line interface."""
    CliApp().run(DataMapperCli)


__all__ = ["AindAcquisitionDataMapper", "AindInstrumentDataMapper", "DataMapperCli", "main"]
