# Aind.Physiology.OpenEphys

![CI](https://github.com/AllenNeuralDynamics/Aind.Physiology.OpenEphys/actions/workflows/openephys-cicd.yml/badge.svg)
<!-- [![PyPI - Version](https://img.shields.io/pypi/v/aind-physiology-openephys)](https://pypi.org/project/aind-physiology-openephys/) -->
[![License](https://img.shields.io/badge/license-MIT-brightgreen)](LICENSE)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

A repository with a deployable version of the Open Ephys GUI, plus the Python packages that support it.

## Repository layout

| Path | Description |
| --- | --- |
| `.open-ephys/` | Scripts to download and launch the Open Ephys GUI |
| `src/example.xml` | Example Open Ephys signal chain |
| `src/packages/aind_physiology_openephys` | Top-level, publishable Python package (`aind-physiology-openephys`) |
| `src/packages/aind_physiology_openephys_data_mappers` | Internal data mappers (`aind-physiology-openephys-data-mappers`), not published |

## Deploying the Open Ephys GUI

1. Clone the repository to your local machine
2. [Follow the instructions](https://open-ephys.github.io/gui-docs/User-Manual/Installing-the-GUI.html#via-zip-file) and install necessary 3rd party dependencies
3. Run `./.open-ephys/setup.ps1` to download and launch Open Ephys GUI
4. Run your chain by passing it as an argument to `./.open-ephys/open-ephys.exe`: `./.open-ephys/open-ephys.exe ./src/example.xml`

## Acquisition metadata

`src/data_mappers/_acquisition.py` provides `AindAcquisitionDataMapper`, following
the session-mapper method interface used by VrForaging without depending on
CLABE. Both mappers read only previously saved datasets; they never contact a
running Open Ephys application.

Pass the dataset root as `data_dir`, not an individual processor directory or
XML path. Other experimental/session metadata remains caller-supplied.

`acquisition_type` defaults to `""`, allowing the behavior acquisition's type
to be used when the acquisitions are merged. `instrument_id` defaults to
`None` at construction, but the acquisition schema requires a nonempty ID for
Open Ephys data streams. Supply the shared behavior instrument ID either in
the constructor or by setting `mapper.instrument_id` before calling `map()`.
An empty or missing instrument ID is rejected during mapping, not deferred
until merge.

The ephys mapper does not accept `subject_details`; it leaves that field as
`None` so merging retains the subject details supplied by the behavior component.

Both mappers provide `map()`, `run()`, `mapped`, and `is_mapped()`. They do not
inherit from CLABE services or apply CLABE notifications, activity indicators,
or tracing; the coordinating application can wrap execution if needed.

```python
from pathlib import Path

from aind_behavior_services.session import Session
from aind_data_schema.components.coordinates import CoordinateSystemLibrary

from src.data_mappers import AindAcquisitionDataMapper

session = Session.model_validate_json(Path("session.json").read_text(encoding="utf-8"))
data_dir = Path(r"C:\Users\joshs\Documents\Open Ephys\2026-10-23_14-43-15")
mapper = AindAcquisitionDataMapper(
    data_dir=data_dir,
    session=session,
    instrument_id="EPHYS1",  # Replace with the actual instrument.
    acquisition_type="Receptive field mapping",
    coordinate_system=CoordinateSystemLibrary.BREGMA_RAS,  # Only if applicable.
    ethics_review_id=["2109"],  # Replace with applicable review identifiers.
)
acquisition = mapper.map()
acquisition.write_standard_file(prefix="ephys")
```

## Instrument metadata

`src/data_mappers/_instrument.py` provides `AindInstrumentDataMapper`, using the
same `map()`/`run()`, `mapped`, `is_mapped()`, and `rig_schema()` method interface
as the VrForaging instrument mapper.

Pass the same dataset root as `data_dir`. The mapper checks immediate
`Record Node XXX` directories in lexicographic name order and reads the first
available `settings.xml`. Nodes without that exact file are skipped;
`settings_2.xml`, root-level settings, and nested experiment files are not used.
A malformed selected settings file raises an error rather than falling through
to a different snapshot. The old `app` and `xml_path` arguments are removed.
Discovery and reads happen during mapping, not construction.

Probe names come from ordered `STREAM` entries in each Neuropixels processor,
not `NP_PROBE.custom_probe_name`. Each physical probe consumes four streams
for Quad Base, one for Neuropixels 2.0 single- or multishank, and two for other
supported models. Repeated Quad Base `NP_PROBE` shank entries do not consume
additional groups. The mapper removes `-1` through `-4` or `-AP`/`-LFP` suffixes
from grouped streams and preserves single-stream names unchanged. Missing,
extra, or inconsistently named streams are rejected rather than guessed.

```python
from datetime import date
from pathlib import Path

from aind_data_schema.components.coordinates import CoordinateSystemLibrary
from aind_data_schema.core.acquisition import Acquisition
from src.data_mappers import AindInstrumentDataMapper

# Or reuse the Acquisition returned by AindAcquisitionDataMapper.map().
acquisition = Acquisition.model_validate_json(
    Path("acquisition.json").read_text(encoding="utf-8")
)
mapper = AindInstrumentDataMapper(
    data_dir=Path(r"C:\Users\joshs\Documents\Open Ephys\2026-10-23_14-43-15"),
    instrument_id="EPHYS1",  # Supply the actual instrument identifier.
    modification_date=date(2026, 10, 23),  # Actual hardware modification date.
    coordinate_system=CoordinateSystemLibrary.BREGMA_ARI,  # Only if applicable.
    acquisition=acquisition,
    location="323",  # Optional; supply the actual location.
)
instrument = mapper.map()
instrument.write_standard_file(prefix="ephys")
```

## Python development

This repository is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/).

```powershell
uv sync --all-packages
uv run pytest
uv run ruff format --check; uv run ruff check; uv run codespell
```

Install the top-level package with `pip install aind-physiology-openephys`. The data mappers can be installed from GitHub, see the [package README](src/packages/aind_physiology_openephys_data_mappers/README.md).

### Recorded-fixture regression tests

Run `uv run pytest tests/test_example_dataset.py` to validate the JSON recording
history and saved signal-chain XML in `tests/example_data_directory` against the
installed AIND schema. Tests cover acquisition bounds, hardware mapping,
quad-base deduplication, file serialization/revalidation, input immutability,
and rejection of timezone-less timestamps. Both XML snapshots are exercised;
normal dataset discovery still selects only `settings.xml`.

The supplied JSON files include manipulator names and probe labels matching
the ordered XML stream groups. Instrument tests map these files directly,
without rewriting probe or manipulator identities. All destructive test cases
operate on temporary copies; the original files remain unchanged.

## Releasing

Publishing a GitHub release tagged `vX.Y.Z` sets the version of `aind-physiology-openephys`, builds it, and publishes it to PyPI. The data-mappers package is never published.

