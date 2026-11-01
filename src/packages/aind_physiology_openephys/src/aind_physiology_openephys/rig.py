from pathlib import Path
from typing import Literal

from aind_behavior_services import rig
from pydantic import Field

from . import __semver__


class AindPhysioOpenEphysRig(rig.Rig):
    """Rig configuration of an Open Ephys acquisition computer.

    ``computer_name`` is the network name of the computer running Open Ephys, which other computers reach it by.
    ``data_directory`` is the data directory on that computer: each session is recorded to
    ``<data_directory>/<session_name>/ecephys`` (see :class:`aind_physiology_openephys.app.AindBehaviorServicesOpenEphysApp`).
    """

    version: Literal[__semver__] = __semver__
    signal_chain: Path = Field(description="Open Ephys signal chain (XML) to load, relative to the repository root.")
    port: int = Field(default=37497, description="Port of the Open Ephys GUI HTTP server.")
