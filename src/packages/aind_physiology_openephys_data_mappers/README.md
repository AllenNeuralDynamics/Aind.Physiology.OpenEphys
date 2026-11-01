# AIND Physiology Open Ephys data mappers

Internal data mappers that generate AIND acquisition and instrument metadata for Open Ephys sessions.

This package is not published to a package index. It can be installed from this repository's uv workspace or directly from GitHub.

## Workspace usage

From the repository root:

```powershell
uv sync
uv run open-ephys-data-mapper --help
```

## Mapping a session

`open-ephys-data-mapper` maps a session directory recorded by `AindBehaviorServicesOpenEphysApp`: the Open Ephys
recording in `ecephys/`, and the rig and session it was recorded with in `ecephys/Logs/`. In Python, the mappers
take either that recording directory or the app itself (`AindAcquisitionDataMapper.from_app(app)`).

```powershell
uv run open-ephys-data-mapper --data-path "D:\data\<session_name>"
```

It writes `ecephys_acquisition.json` and `ecephys_instrument.json` to the session directory.

## GitHub installation

```powershell
uv add "aind-physiology-openephys-data-mappers @ git+https://github.com/AllenNeuralDynamics/Aind.Physiology.OpenEphys.git#subdirectory=src/packages/aind_physiology_openephys_data_mappers"
```
