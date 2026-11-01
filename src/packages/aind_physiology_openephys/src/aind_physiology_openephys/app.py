"""Runs the Open Ephys GUI for an AIND behavior services session, locally or on another machine."""

import logging
import os
from pathlib import Path, PureWindowsPath

from aind_behavior_services.session import Session
from clabe.apps.open_ephys import OpenEphysApp, OpenEphysAppSettings, Status, _OpenEphysGuiClient
from clabe.xml_rpc import RemoteRepository

from .rig import AindPhysioOpenEphysRig

logger = logging.getLogger(__name__)


class AindBehaviorServicesOpenEphysApp(OpenEphysApp):
    """Open Ephys GUI configured from an Open Ephys rig and a session.

    The counterpart of clabe's ``AindBehaviorServicesBonsaiApp``. It records the session to
    ``<rig.data_directory>/<session name>/ecephys``, and saves the rig and session to ``ecephys/Logs`` once recording
    starts, so the recording can later be mapped from its files alone (see :meth:`read_rig` and :meth:`read_session`).
    It works the same whether the GUI runs on this machine or, through a ``RemoteRepository``, on another one.

    Example:
        ```python
        app = AindBehaviorServicesOpenEphysApp(rig, session)
        await app.launch(executor=remote)  # or no executor to run it on this machine
        try:
            app.start()
            await behavior_app.run_async()
            app.stop()
        finally:
            await app.close()
        acquisition = AindAcquisitionDataMapper.from_app(app).map()
        ```
    """

    MODALITY = "ecephys"
    """Directory the session is recorded to, named after the modality so it can be transferred as-is."""
    LOGS = "Logs"
    RIG_INPUT = "rig_input.json"
    SESSION_INPUT = "session_input.json"

    def __init__(
        self,
        rig: AindPhysioOpenEphysRig,
        session: Session,
        *,
        executable: os.PathLike = Path("./.open-ephys/open-ephys.exe"),
        headless: bool = False,
        skip_validation: bool = False,
    ) -> None:
        """
        Initializes the app.

        Args:
            rig: The Open Ephys rig. Its ``data_directory`` is on the machine running the GUI.
            session: The session being recorded. Must have a ``session_name``.
            executable: Path to the Open Ephys GUI executable.
            headless: Whether to run the GUI without a window.
            skip_validation: Whether to skip checking that the executable and signal chain exist.
        """
        if session.session_name is None:
            raise ValueError("session.session_name is not set.")
        self.rig = rig
        self.session = session
        self._remote: RemoteRepository | None = None
        super().__init__(
            OpenEphysAppSettings(
                signal_chain=rig.signal_chain, executable=executable, port=rig.port, headless=headless
            ),
            skip_validation=skip_validation,
        )

    @property
    def gui_session_directory(self) -> PureWindowsPath:
        """The session directory, as the machine running the GUI sees it.

        Only meaningful on that machine, e.g. to configure the GUI. Use :attr:`session_directory` to read it here.
        """
        assert self.session.session_name is not None
        return PureWindowsPath(self.rig.data_directory) / self.session.session_name

    @property
    def gui_recording_directory(self) -> PureWindowsPath:
        """The directory the GUI records to, as the machine running it sees it."""
        return self.gui_session_directory / self.MODALITY

    @property
    def session_directory(self) -> Path:
        """The session directory, as this machine reaches it: the path itself, or its share for a remote GUI.

        Use it for anything that runs here, such as the data mappers or the data transfer.
        """
        if self._remote is None:
            return Path(self.gui_session_directory)
        return Path(self._remote.to_unc(self.gui_session_directory))

    @property
    def recording_directory(self) -> Path:
        """The directory the GUI records to, as this machine reaches it."""
        return self.session_directory / self.MODALITY

    @classmethod
    def read_rig(cls, recording_directory: os.PathLike) -> AindPhysioOpenEphysRig:
        """Reads the rig a recording was made with, from the ``Logs`` saved in its ``recording_directory``."""
        path = Path(recording_directory) / cls.LOGS / cls.RIG_INPUT
        return AindPhysioOpenEphysRig.model_validate_json(path.read_text(encoding="utf-8"))

    @classmethod
    def read_session(cls, recording_directory: os.PathLike) -> Session:
        """Reads the session a recording was made for, from the ``Logs`` saved in its ``recording_directory``."""
        path = Path(recording_directory) / cls.LOGS / cls.SESSION_INPUT
        return Session.model_validate_json(path.read_text(encoding="utf-8"))

    async def launch(  # type: ignore[override]
        self,
        executor: RemoteRepository | None = None,
        *,
        timeout: float = 180.0,
        poll_interval: float = 0.5,
    ) -> _OpenEphysGuiClient:
        """Creates the session directory, starts the GUI, and points it at :attr:`gui_recording_directory`.

        Args:
            executor: The repository on the machine to run the GUI on, or None to run it on this machine.
            timeout: Seconds to wait for the GUI's API to respond after starting it.
            poll_interval: Seconds between attempts to reach the API.

        Returns:
            The client connected to the running GUI.
        """
        if executor is not None and not isinstance(executor, RemoteRepository):
            raise TypeError(f"Expected a RemoteRepository, or None to run locally, not {type(executor).__name__}")
        self._remote = executor
        # The GUI ignores a recording directory whose parent does not exist
        self._mkdir(self.gui_session_directory)
        client = await super().launch(executor, timeout=timeout, poll_interval=poll_interval)
        try:
            self.set_recording_directory(self.gui_recording_directory)
        except BaseException:
            await self.close()
            raise
        return client

    def start(self, record: bool = True) -> Status:
        """Starts recording, or only acquisition when ``record`` is False.

        When recording, saves the rig and session to ``ecephys/Logs``. This happens after recording starts, because
        the GUI does not reuse a recording directory that already exists.
        """
        status = super().start(record)
        if record:
            logs = self.gui_recording_directory / self.LOGS
            self._write(logs / self.RIG_INPUT, self.rig.model_dump_json(indent=2))
            self._write(logs / self.SESSION_INPUT, self.session.model_dump_json(indent=2))
        return status

    def _mkdir(self, path: PureWindowsPath) -> None:
        if self._remote is None:
            Path(path).mkdir(parents=True, exist_ok=True)
        else:
            self._remote.mkdir(path)

    def _write(self, path: PureWindowsPath, content: str) -> None:
        if self._remote is None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding="utf-8")
        else:
            self._remote.write_file(path, content)
