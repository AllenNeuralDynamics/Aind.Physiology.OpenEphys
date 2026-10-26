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

## Python development

This repository is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/).

```powershell
uv sync --all-packages
uv run pytest
uv run ruff format --check; uv run ruff check; uv run codespell
```

Install the top-level package with `pip install aind-physiology-openephys`. The data mappers can be installed from GitHub, see the [package README](src/packages/aind_physiology_openephys_data_mappers/README.md).

## Releasing

Publishing a GitHub release tagged `vX.Y.Z` sets the version of `aind-physiology-openephys`, builds it, and publishes it to PyPI. The data-mappers package is never published.
