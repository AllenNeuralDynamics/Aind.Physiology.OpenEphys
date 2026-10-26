# Aind.Physiology.OpenEphys

A repository with a deployable version of the Open Ephys GUI.

## Instructions

1. Clone the repository to your local machine
2. [Follow the instructions](https://open-ephys.github.io/gui-docs/User-Manual/Installing-the-GUI.html#via-zip-file) and install necessary 3rd party dependencies
3. Run `./.open-ephys/setup.ps1` to download and launch Open Ephys GUI
4. Run your chain by passing it as an argument to `./.open-ephys/open-ephys.exe`: `./.open-ephys/open-ephys.exe ./src/example.xml`
## Acquisition metadata

`src/data_mappers/_acquisition.py` provides `AindAcquisitionDataMapper`, following
the CLABE session-mapper interface used by VrForaging. Both mappers read only
previously saved datasets; they never contact a running Open Ephys application.
Pass the dataset root as `data_dir`, not an individual processor directory or
XML path. Other experimental/session metadata remains caller-supplied.

Use Python 3.11 or newer, CLABE's mapper base classes, and AIND schema v2.
From this repository's root, in your chosen environment:

```powershell
python -m pip install -e ../clabe "aind-data-schema>=2,<3"
```

The tests were validated with `aind-data-schema==2.9.2`. The plugin's exported
configuration fields must match the installed schema version; the mapper
reports validation errors rather than silently migrating incompatible schemas.
This repository is not yet a packaged Python distribution, so the example below
uses a repository-relative import when run from its root.

After recording is complete and all metadata files have been saved, supply
the dataset root, actual session file, instrument ID, and experiment details.
The GUI can be closed:

```python
from pathlib import Path

from aind_behavior_services.session import Session
from aind_data_schema.components.coordinates import CoordinateSystemLibrary
from aind_data_schema.core.acquisition import AcquisitionSubjectDetails

from src.data_mappers import AindAcquisitionDataMapper

session = Session.model_validate_json(Path("session.json").read_text(encoding="utf-8"))
data_dir = Path(r"C:\Users\joshs\Documents\Open Ephys\2026-10-23_14-43-15")
mapper = AindAcquisitionDataMapper(
    data_dir=data_dir,
    session=session,
    instrument_id="EPHYS1",  # Replace with the actual instrument.
    acquisition_type="Receptive field mapping",
    subject_details=AcquisitionSubjectDetails(mouse_platform_name="Running Wheel"),
    coordinate_system=CoordinateSystemLibrary.BREGMA_RAS,  # Only if applicable.
    ethics_review_id=["2109"],  # Replace with applicable review identifiers.
)
acquisition = mapper.map()
acquisition.write_standard_file(prefix="ephys")
```

The acquisition mapper finds the immediate `Ephys Metadata Generator XXX`
directory under `data_dir`, where `XXX` is a numeric processor ID. Multiple
matching directories are rejected as ambiguous rather than silently combined.
It reads all top-level `.json` files there (case-insensitive extension) in
filename order, one DataStream object per file. Other dataset folders,
subdirectories, and non-JSON files are ignored. Missing/empty directories,
malformed JSON, and invalid streams are rejected; files are never silently
skipped. The old `app`, `processor_id`, and `metadata_dir` arguments are removed.

### Acquisition validation and lifecycle

The mapper supports `map()` (or CLABE's inherited `run()`), `is_mapped()`,
`mapped`, `session_schema()`, and `session_name`. Before successful mapping,
`is_mapped()` returns false and accessing `mapped`/`session_schema()` raises
`ValueError`. Each mapping rereads saved history; a failed refresh invalidates
the previous result.

Acquisition start/end bounds are the earliest start and latest end across all
returned streams; stream order and device configurations are preserved.
Empty history, missing/timezone-naive timestamps, reversed stream bounds, and
invalid schema fields are rejected. File-access errors propagate.
Optional `stimulus_epochs` can be supplied by the experiment; no behavior-specific
stimulus metadata is fabricated.

**Lifecycle:** map only completed datasets after their metadata files have
finished being written. Neither mapper controls recording, clears history, or
writes files. The caller must ensure the chosen dataset belongs to the supplied
session. The original `exampleMapper.py` remains a separate live acquisition
demonstration, not an offline test.

## Instrument metadata

`src/data_mappers/_instrument.py` provides `AindInstrumentDataMapper`, using the
same CLABE `map()`/`run()`, `mapped`, `is_mapped()`, and `rig_schema()` contract
as the VrForaging instrument mapper.

Pass the same dataset root as `data_dir`. The mapper checks immediate
`Record Node XXX` directories in lexicographic name order and reads the first
available `settings.xml`. Nodes without that exact file are skipped;
`settings_2.xml`, root-level settings, and nested experiment files are not used.
A malformed selected settings file raises an error rather than falling through
to a different snapshot. The old `app` and `xml_path` arguments are removed.
Discovery and reads happen during mapping, not construction.

The XML provides computer name/OS and Neuropixels probes, slots, ports, part
numbers, and firmware. The mapper deduplicates repeated physical probe serials,
so the four quad-base entries in `src/example.xml` become one probe/assembly.
Disabled probes remain in the Instrument because it describes configured
hardware, not only the devices recorded in a particular acquisition.

Pass an `aind_data_schema.core.acquisition.Acquisition` object as `acquisition`
(for example, the result of the acquisition mapper above). The instrument mapper
uses each stream's `EphysAssemblyConfig` to associate `probes[].device_name`
with `manipulator.device_name`, preserving the assembly's `device_name`.
Probe names must match XML `custom_probe_name` (or the probe serial number when
the XML name is empty). Every configured XML probe needs an association, even
if disabled for acquisition. Repeated associations across recordings are
deduplicated; conflicting associations and blank device names are rejected.

Acquisition configurations do not supply manipulator manufacturer, model, or
serial number. Generated manipulators use the recorded device name, manufacturer
`Unknown`, and unset model/serial rather than fabricated hardware details.
Instrument ID, modification date, and coordinate system remain explicit inputs.

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

Ephys assemblies group probes with their acquisition-associated manipulator. Basestation
ports refer to probe names, and basestations connect to the computer described
in the XML, not the machine running the mapper. Carrier serial values of `0` or
`UNKNOWN` are left unset; raw carrier/connect-board identifiers are preserved in
the basestation's `additional_settings`.

Currently supported probe models are the example's Neuropixels 2.0 single-shank
and quad-base variants. Unsupported models, missing manipulators, conflicting
hardware entries, duplicate probe names, and incomplete XML are errors rather
than silently guessed metadata. Headstages and other signal-chain hardware
are not yet mapped. `session_name` may be supplied if a caller needs a session
association; accessing that property without supplying it raises `ValueError`.
As with the acquisition mapper, a failed mapping invalidates any cached result.

## Offline tests

From this repository root:

```powershell
python -m pip install pytest
python -m pytest
```

Tests build temporary saved-dataset layouts and fail any attempted HTTP request.
They require no GUI or hardware.
