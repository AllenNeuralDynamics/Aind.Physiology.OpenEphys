"""Map completed Open Ephys recording history to AIND acquisition metadata."""

import json
import logging
from pathlib import Path
from typing import Any

from aind_behavior_services.session import Session
from aind_data_schema.components.coordinates import CoordinateSystem
from aind_data_schema.core import acquisition
from pydantic import AwareDatetime, TypeAdapter

from ._base import DataMapper
from ._dataset import find_metadata_directory

logger = logging.getLogger(__name__)


class AindAcquisitionDataMapper(DataMapper[acquisition.Acquisition]):
    """Read completed metadata from a saved Open Ephys dataset.

    ``data_dir`` must contain one ``Ephys Metadata Generator XXX`` directory.
    Mapping reads one DataStream object per JSON file in that directory, in
    filename order. It never contacts the GUI or modifies the dataset.
    Write the returned Acquisition explicitly with ``write_standard_file``.
    Subject details are left unset for the behavior acquisition to provide
    when the acquisitions are merged.

    Args:
        data_dir: Saved Open Ephys dataset root, not a processor subdirectory.
        session: Shared experimental session (subject, experimenters, and name).
        instrument_id: Identifier of the recording instrument. Defaults to None;
            supply the shared behavior instrument ID before mapping, since the
            acquisition schema requires it for Open Ephys data streams.
        acquisition_type: Description of the experiment/acquisition. Defaults to
            an empty string so merging can use the behavior acquisition's type.
        ethics_review_id: Applicable ethics review identifiers, if available.
        coordinate_system: Acquisition-level coordinate system, if known.
        stimulus_epochs: Optional stimulus metadata supplied by the experiment.
    """

    def __init__(
        self,
        data_dir: str | Path,
        session: Session,
        *,
        instrument_id: str | None = None,
        acquisition_type: str = "",
        ethics_review_id: list[str] | None = None,
        coordinate_system: CoordinateSystem | None = None,
        stimulus_epochs: list[acquisition.StimulusEpoch] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.session_model = session
        self.instrument_id = instrument_id
        self.acquisition_type = acquisition_type
        self.ethics_review_id = ethics_review_id
        self.coordinate_system = coordinate_system
        self.stimulus_epochs = list(stimulus_epochs) if stimulus_epochs is not None else []
        self._mapped: acquisition.Acquisition | None = None

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
        # Validate the wire timestamps before the schema can infer a timezone.
        timestamp = TypeAdapter(AwareDatetime)
        for item in metadata:
            timestamp.validate_python(item.get("stream_start_time"))
            timestamp.validate_python(item.get("stream_end_time"))
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
