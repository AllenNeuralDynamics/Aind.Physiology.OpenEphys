"""Map completed Open Ephys recording history to AIND acquisition metadata."""

import logging

from aind_behavior_services.session import Session
from aind_data_schema.components.coordinates import CoordinateSystem
from aind_data_schema.core import acquisition
from pydantic import AwareDatetime, TypeAdapter

from clabe.apps.open_ephys import OpenEphysApp, Status
from clabe.data_mapper import aind_data_schema as ads

logger = logging.getLogger(__name__)


class AindAcquisitionDataMapper(ads.AindDataSchemaSessionDataMapper):
    """Read an Ephys Metadata Generator's history using the CLABE mapper API.

    Call after recording has stopped, while the GUI is still open and idle.
    The caller owns recording control and history clearing. Construction does
    not contact the GUI; ``map`` fetches history but never starts/stops recording,
    clears history, or writes files. Write the returned Acquisition explicitly
    with ``write_standard_file`` when ready.

    Args:
        app: Configured CLABE Open Ephys application; HTTP access uses ``app.client``.
        processor_id: Explicit ID of the Ephys Metadata Generator processor.
        session: Shared experimental session (subject, experimenters, and name).
        instrument_id: Identifier of the recording instrument.
        acquisition_type: Description of the experiment/acquisition.
        subject_details: Subject setup, such as the mouse platform.
        ethics_review_id: Applicable ethics review identifiers, if available.
        coordinate_system: Acquisition-level coordinate system, if known.
        stimulus_epochs: Optional stimulus metadata supplied by the experiment.
    """

    def __init__(
        self,
        app: OpenEphysApp,
        processor_id: int,
        session: Session,
        *,
        instrument_id: str,
        acquisition_type: str,
        subject_details: acquisition.AcquisitionSubjectDetails,
        ethics_review_id: list[str] | None = None,
        coordinate_system: CoordinateSystem | None = None,
        stimulus_epochs: list[acquisition.StimulusEpoch] | None = None,
    ) -> None:
        self.app = app
        self.processor_id = processor_id
        self.session_model = session
        self.instrument_id = instrument_id
        self.acquisition_type = acquisition_type
        self.subject_details = subject_details
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
        """Fetch and validate completed recording history, replacing cached data."""
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
            subject_details=self.subject_details,
            coordinate_system=self.coordinate_system,
            stimulus_epochs=self.stimulus_epochs,
            data_streams=streams,
        )

    def _get_data_streams(self) -> list[acquisition.DataStream]:
        if self.app.client.get_status() != Status.IDLE:
            raise ValueError("Open Ephys must be idle before mapping completed recording metadata.")
        metadata = self.app.client.get_processor_metadata(self.processor_id)
        if not metadata:
            raise ValueError("The metadata processor has no recording history to map.")
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
