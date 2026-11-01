"""Map completed Open Ephys recording history to AIND acquisition metadata."""

import json
import logging
from pathlib import Path
from typing import Any, Self

from aind_behavior_services.session import Session
from aind_data_schema.components.coordinates import CoordinateSystem
from aind_data_schema.core import acquisition
from aind_physiology_openephys.app import AindBehaviorServicesOpenEphysApp
from clabe.data_mapper import aind_data_schema as ads

from ._dataset import find_metadata_directory

logger = logging.getLogger(__name__)


class AindAcquisitionDataMapper(ads.AindDataSchemaSessionDataMapper):
    """Map the recording history of a saved Open Ephys dataset to an Acquisition.

    Reads one DataStream per JSON file in the dataset's ``Ephys Metadata Generator XXX``
    directory. Never contacts the GUI or modifies the dataset.

    Args:
        data_dir: Open Ephys dataset root (the ``ecephys`` directory).
        session: Session of the recording. Defaults to the one saved in ``<data_dir>/Logs``.
        instrument_id: Defaults to the name of the rig saved in ``<data_dir>/Logs``.
        acquisition_type: Description of the acquisition.
        ethics_review_id: Applicable ethics review identifiers.
        coordinate_system: Acquisition-level coordinate system.
        stimulus_epochs: Stimulus metadata.
    """

    def __init__(
        self,
        data_dir: str | Path,
        session: Session | None = None,
        instrument_id: str | None = None,
        *,
        acquisition_type: str = "",
        ethics_review_id: list[str] | None = None,
        coordinate_system: CoordinateSystem | None = None,
        stimulus_epochs: list[acquisition.StimulusEpoch] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.session_model = (
            session if session is not None else AindBehaviorServicesOpenEphysApp.read_session(self.data_dir)
        )
        if instrument_id is None:
            instrument_id = AindBehaviorServicesOpenEphysApp.read_rig(self.data_dir).rig_name
        self.instrument_id = instrument_id
        self.acquisition_type = acquisition_type
        self.ethics_review_id = ethics_review_id
        self.coordinate_system = coordinate_system
        self.stimulus_epochs = list(stimulus_epochs) if stimulus_epochs is not None else []
        self._mapped: acquisition.Acquisition | None = None

    @classmethod
    def from_app(cls, app: AindBehaviorServicesOpenEphysApp) -> Self:
        """Maps the recording of an app, read through the path this machine reaches it by."""
        return cls(app.recording_directory, app.session, app.rig.rig_name)

    @property
    def session_name(self) -> str:
        """Return the shared session name."""
        if self.session_model.session_name is None:
            raise ValueError("Session name is not set in the session model.")
        return self.session_model.session_name

    def session_schema(self) -> acquisition.Acquisition:
        """Return the last successfully mapped acquisition."""
        return self.mapped

    def map(self) -> acquisition.Acquisition:
        """Read and validate saved recording history, replacing cached data."""
        logger.info("Mapping Open Ephys acquisition metadata.")
        # A failed refresh must not expose stale metadata as a successful result.
        self._mapped = None
        self._mapped = self._map()
        return self._mapped

    def _map(self) -> acquisition.Acquisition:
        streams = self._get_data_streams()
        return acquisition.Acquisition(
            subject_id=self.session_model.subject,
            experimenters=self.session_model.experimenter,
            notes=self.session_model.notes,
            acquisition_start_time=min(stream.stream_start_time for stream in streams),
            acquisition_end_time=max(stream.stream_end_time for stream in streams),
            acquisition_type=self.acquisition_type,
            instrument_id=self.instrument_id,
            ethics_review_id=self.ethics_review_id,
            coordinate_system=self.coordinate_system,
            stimulus_epochs=self.stimulus_epochs,
            data_streams=streams,
        )

    def _get_data_streams(self) -> list[acquisition.DataStream]:
        metadata = self._read_metadata_directory()
        streams = [acquisition.DataStream.model_validate(item) for item in metadata]
        for index, stream in enumerate(streams):
            if stream.stream_end_time < stream.stream_start_time:
                raise ValueError(f"Metadata stream {index} ends before it starts; recording may be incomplete.")
        return streams

    def _read_metadata_directory(self) -> list[dict[str, Any]]:
        metadata_dir = find_metadata_directory(self.data_dir)
        paths = sorted(path for path in metadata_dir.iterdir() if path.is_file() and path.suffix.lower() == ".json")
        if not paths:
            raise ValueError(f"No JSON metadata files found in {metadata_dir}.")
        metadata = []
        for path in paths:
            try:
                item = json.loads(path.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise ValueError(f"Invalid metadata JSON in {path}: {exc}") from exc
            if not isinstance(item, dict):
                # The file's contents are invalid, not the caller's argument type.
                raise ValueError(f"Metadata file must contain a single DataStream object: {path}")  # noqa: TRY004
            metadata.append(item)
        return metadata
