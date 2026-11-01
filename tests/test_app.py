"""AindBehaviorServicesOpenEphysApp: rig, session paths, saved inputs, local and remote file access, and mapping."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from unittest.mock import AsyncMock, Mock

import pytest
from aind_behavior_services.session import Session
from aind_physiology_openephys.app import AindBehaviorServicesOpenEphysApp
from aind_physiology_openephys.rig import AindPhysioOpenEphysRig
from aind_physiology_openephys_data_mappers import (
    AindAcquisitionDataMapper,
    AindInstrumentDataMapper,
    DataMapperCli,
)
from clabe.apps.open_ephys import OpenEphysApp, Status
from clabe.utils import get_computer_name
from clabe.xml_rpc import RemoteRepository

EXAMPLE = Path(__file__).parent / "example_data_directory"
OPEN_EPHYS = Path(__file__).parents[1] / ".open-ephys"
# Ships with the GUI download and needs no hardware
FILE_READER_CHAIN = OPEN_EPHYS / "configs" / "file_reader_config.xml"


@pytest.fixture(autouse=True)
def no_http():
    """Overrides the suite-wide guard: the real GUI test talks to the GUI over HTTP."""
    yield


def _rig(
    data_directory: Path,
    signal_chain: Path = Path("x.xml"),
    computer_name: str | None = None,
) -> AindPhysioOpenEphysRig:
    return AindPhysioOpenEphysRig(
        computer_name=computer_name
        or get_computer_name(),  # this computer, unless testing a remote one
        rig_name="EPHYS1",
        data_directory=data_directory,
        signal_chain=signal_chain,
    )


def _session() -> Session:
    return Session(
        subject="123456",
        experimenter=["someone"],
        date=datetime(2026, 10, 23, 14, 0, tzinfo=UTC),
    )


def _app(tmp_path: Path) -> AindBehaviorServicesOpenEphysApp:
    app = AindBehaviorServicesOpenEphysApp(
        _rig(tmp_path / "data"), _session(), skip_validation=True
    )
    app._client = Mock()
    return app


def _starts_recording(
    app: AindBehaviorServicesOpenEphysApp, recording_directory: Path
) -> None:
    """Makes the mocked GUI create the recording directory when recording starts, as the real one does."""

    def start_recording() -> Status:
        assert not recording_directory.exists(), (
            "the GUI would record to 'ecephys (1)' instead"
        )
        recording_directory.mkdir(parents=True)
        return Status.RECORD

    app._client.start_recording.side_effect = start_recording


def _recorded_session(tmp_path: Path) -> AindBehaviorServicesOpenEphysApp:
    """A session recorded through the app: the example dataset, with the Logs the app saves when it starts."""
    app = _app(tmp_path)
    app._client.start_recording.return_value = Status.RECORD
    app.start()
    shutil.copytree(EXAMPLE, app.recording_directory, dirs_exist_ok=True)
    return app


def test_rig_round_trip(tmp_path):
    rig = _rig(tmp_path)
    assert AindPhysioOpenEphysRig.model_validate_json(rig.model_dump_json()) == rig


def test_paths_follow_rig_and_session(tmp_path):
    app = _app(tmp_path)
    session_directory = PureWindowsPath(tmp_path / "data" / "123456_2026-10-23T140000Z")
    assert app.gui_session_directory == session_directory
    assert app.gui_recording_directory == session_directory / "ecephys"
    assert app.recording_directory == Path(session_directory / "ecephys"), (
        "local GUI: the same path"
    )
    assert app.client.base_url.endswith(":37497/api"), "port from the rig"


def test_recording_saves_inputs_after_starting_locally(tmp_path):
    app = _app(tmp_path)
    _starts_recording(app, Path(app.gui_recording_directory))
    assert app.start() == Status.RECORD
    modality = Path(app.gui_recording_directory)
    assert AindBehaviorServicesOpenEphysApp.read_rig(modality) == app.rig
    assert AindBehaviorServicesOpenEphysApp.read_session(modality) == app.session


def test_acquiring_saves_nothing(tmp_path):
    app = _app(tmp_path)
    app._client.start_acquisition.return_value = Status.ACQUIRE
    app.start(record=False)
    assert not Path(app.gui_recording_directory).exists()


@pytest.mark.asyncio
async def test_launch_rejects_other_executors(tmp_path):
    with pytest.raises(TypeError, match="RemoteRepository"):
        await _app(tmp_path).launch(executor=Mock())


@pytest.fixture
def gui_launch(monkeypatch):
    """Stands in for starting the GUI and configuring its recording directory."""
    launch = AsyncMock()
    monkeypatch.setattr(OpenEphysApp, "launch", launch)
    monkeypatch.setattr(OpenEphysApp, "set_recording_directory", Mock())
    return launch


@pytest.mark.asyncio
async def test_launch_runs_here_when_the_rig_is_this_computer(
    tmp_path, gui_launch, monkeypatch
):
    connect = Mock(side_effect=AssertionError("no server needed for this computer"))
    monkeypatch.setattr(RemoteRepository, "from_computer_name", connect)
    app = _app(tmp_path)

    await app.launch()

    assert gui_launch.await_args.args[0] is None, "launched with the local executor"
    assert Path(app.gui_session_directory).is_dir()
    assert app.session_directory == Path(app.gui_session_directory)


@pytest.mark.asyncio
async def test_launch_follows_the_rig_to_another_computer(
    tmp_path, gui_launch, monkeypatch
):
    remote = Mock(spec=RemoteRepository)
    connect = Mock(return_value=remote)
    monkeypatch.setattr(RemoteRepository, "from_computer_name", connect)
    app = AindBehaviorServicesOpenEphysApp(
        _rig(tmp_path / "data", computer_name="EPHYS-PC"),
        _session(),
        skip_validation=True,
    )

    await app.launch()

    connect.assert_called_once_with("EPHYS-PC")
    remote.ensure_running.assert_called_once_with()
    remote.verify.assert_called_once_with()
    assert gui_launch.await_args.args[0] is remote
    remote.mkdir.assert_called_once_with(app.gui_session_directory)
    assert not Path(app.gui_session_directory).exists(), (
        "nothing created on this computer"
    )


def test_remote_gui_files_go_through_the_repository(tmp_path):
    app = _app(tmp_path)
    remote = Mock(spec=RemoteRepository)
    remote.to_unc.side_effect = lambda path: (
        PureWindowsPath(r"\\EPHYS-PC\data") / PureWindowsPath(path).name
    )
    app._remote = remote
    app._client.start_recording.return_value = Status.RECORD

    app.start()

    logs = app.gui_recording_directory / "Logs"
    assert [c.args[0] for c in remote.write_file.call_args_list] == [
        logs / "rig_input.json",
        logs / "session_input.json",
    ]
    assert (
        AindPhysioOpenEphysRig.model_validate_json(
            remote.write_file.call_args_list[0].args[1]
        )
        == app.rig
    )
    assert app.session_directory == Path(r"\\EPHYS-PC\data\123456_2026-10-23T140000Z")
    assert not Path(app.gui_recording_directory).exists(), (
        "nothing written on this machine"
    )


def test_mappers_from_app(tmp_path):
    app = _app(tmp_path)
    shutil.copytree(EXAMPLE, app.recording_directory)

    acquisition = AindAcquisitionDataMapper.from_app(app).map()
    instrument = AindInstrumentDataMapper.from_app(app, acquisition=acquisition).map()

    assert acquisition.subject_id == "123456"
    assert acquisition.instrument_id == instrument.instrument_id == "EPHYS1"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not (OPEN_EPHYS / "open-ephys.exe").exists(),
    reason="Open Ephys GUI not downloaded: run .open-ephys/setup.ps1",
)
async def test_real_gui_records_session_locally(tmp_path):
    app = AindBehaviorServicesOpenEphysApp(
        _rig(tmp_path / "data", signal_chain=FILE_READER_CHAIN),
        _session(),
        executable=OPEN_EPHYS / "open-ephys.exe",
        headless=True,
    )
    await app.launch(timeout=120.0)
    try:
        assert app.start() == Status.RECORD
        app.stop()
    finally:
        await app.close()
    session_directory = app.session_directory
    assert [p.name for p in session_directory.iterdir()] == ["ecephys"], (
        "no 'ecephys (1)' next to it"
    )
    assert sorted(p.name for p in (session_directory / "ecephys").iterdir()) == [
        "Logs",
        "Record Node 101",
        "Record Node 105",
    ]
    assert (
        AindBehaviorServicesOpenEphysApp.read_rig(session_directory / "ecephys")
        == app.rig
    )


def test_cli_maps_session_from_its_files(tmp_path):
    app = _recorded_session(tmp_path)

    DataMapperCli(data_path=app.session_directory).cli_cmd()

    acquisition = json.loads(
        (app.session_directory / "ecephys_acquisition.json").read_text(encoding="utf-8")
    )
    instrument = json.loads(
        (app.session_directory / "ecephys_instrument.json").read_text(encoding="utf-8")
    )
    # The instrument ID is the name of the rig saved in Logs.
    assert acquisition["instrument_id"] == instrument["instrument_id"] == "EPHYS1"
    assert acquisition["subject_id"] == "123456"
