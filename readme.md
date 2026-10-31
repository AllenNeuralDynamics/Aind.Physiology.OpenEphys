# Aind.Physiology.OpenEphys

![CI](https://github.com/AllenNeuralDynamics/Aind.Physiology.OpenEphys/actions/workflows/openephys-cicd.yml/badge.svg)
<!-- [![PyPI - Version](https://img.shields.io/pypi/v/aind-physiology-openephys)](https://pypi.org/project/aind-physiology-openephys/) -->
[![License](https://img.shields.io/badge/license-MIT-brightgreen)](LICENSE)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

A repository with a deployable version of the Open Ephys GUI, plus the Python packages that support it.

---

## 📋 General instructions

This repository follows the project structure laid out in the [Aind.Behavior.Services repository](https://github.com/AllenNeuralDynamics/Aind.Behavior.Services).

| Path | Description |
| --- | --- |
| `.open-ephys/` | Scripts to download and launch the Open Ephys GUI |
| `src/example.xml` | Example Open Ephys signal chain |
| `src/packages/aind_physiology_openephys` | Publishable package: rig schema and session directory layout |
| `src/packages/aind_physiology_openephys_data_mappers` | Internal data mappers, not published |

---

## 🔧 Prerequisites

[Pre-requisites for running the project can be found here](https://allenneuraldynamics.github.io/Aind.Behavior.Services/articles/requirements.html), plus the [third-party dependencies](https://open-ephys.github.io/gui-docs/User-Manual/Installing-the-GUI.html#via-zip-file) of the Open Ephys GUI.

---

## 🚀 Deployment

Once the dependencies are installed, download and launch the Open Ephys GUI from the root of the repository:

```powershell
./.open-ephys/setup.ps1
```

Run a signal chain by passing it to the GUI:

```powershell
./.open-ephys/open-ephys.exe ./src/example.xml
```


## 🌉 Mapping to aind-data-schema

Data mapping is provided by the internal `aind-physiology-openephys-data-mappers` workspace package. Once a session is collected, run:

```powershell
uv run open-ephys-data-mapper --data-path <path-to-session-dir>
```

This reads the saved rig and session and writes `ecephys_acquisition.json` and `ecephys_instrument.json` to the session directory. The instrument ID defaults to the rig name and can be overridden with `--instrument-id`.

The mappers can also be used from Python. Only `data_dir` is required; everything else is read from `ecephys/Logs` or defaulted:

```python
from aind_physiology_openephys_data_mappers import (
    AindAcquisitionDataMapper,
    AindInstrumentDataMapper,
)

acquisition = AindAcquisitionDataMapper(data_dir).map()
instrument = AindInstrumentDataMapper(data_dir, acquisition=acquisition).map()
```

See the [data mapper package README](src/packages/aind_physiology_openephys_data_mappers/README.md) for installation details.

## 🧪 Tests

```powershell
uv sync --all-packages
uv run pytest
```

`tests/test_example_dataset.py` maps the recorded dataset in `tests/example_data_directory`.

## ✨ Linting

```powershell
uv run ruff format --check; uv run ruff check; uv run codespell
```

## 📦 Releasing

Publishing a GitHub release tagged `vX.Y.Z` sets the version of `aind-physiology-openephys`, builds it, and publishes it to PyPI. The data-mappers package is never published.
