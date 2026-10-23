# Aind.Physiology.OpenEphys

A repository with a deployable version of the Open Ephys GUI.

## Instructions

1. Clone the repository to your local machine
2. [Follow the instructions](https://open-ephys.github.io/gui-docs/User-Manual/Installing-the-GUI.html#via-zip-file) and install necessary 3rd party dependencies
3. Run `./.open-ephys/setup.ps1` to download and launch Open Ephys GUI
4. Run your chain by passing it as an argument to `./.open-ephys/open-ephys.exe`: `./.open-ephys/open-ephys.exe ./src/example.xml`
## Acquisition metadata

`src/data_mappers/_acquisition.py` provides `AindAcquisitionDataMapper`, following
the CLABE session-mapper interface used by VrForaging. It retrieves recording
history from an **Ephys Metadata Generator** processor via CLABE's Open Ephys
HTTP client and validates each entry as an AIND `DataStream`.

Use Python 3.11 or newer and the sibling CLABE checkout supporting
`app.client.get_processor_metadata`. The acquisition mapper accepts the public
`OpenEphysApp`, not its private HTTP client class. From this repository's root,
in your chosen environment:

```powershell
python -m pip install -e ../clabe "aind-data-schema>=2,<3"
```

The tests were validated with `aind-data-schema==2.9.2`. The plugin's exported
configuration fields must match the installed schema version; the mapper
reports validation errors rather than silently migrating incompatible schemas.
This repository is not yet a packaged Python distribution, so the example below
uses a repository-relative import when run from its root.

After recording has stopped, leave the GUI open and idle. Supply your actual
session file, metadata processor ID, instrument ID, and experiment details:

```python
from pathlib import Path

from aind_behavior_services.session import Session
from aind_data_schema.components.coordinates import CoordinateSystemLibrary
from aind_data_schema.core.acquisition import AcquisitionSubjectDetails
from clabe.apps.open_ephys import OpenEphysApp, OpenEphysAppSettings

from src.data_mappers import AindAcquisitionDataMapper

session = Session.model_validate_json(Path("session.json").read_text(encoding="utf-8"))
app = OpenEphysApp(
    OpenEphysAppSettings(
        signal_chain=Path("src/example.xml"),
        executable=Path(".open-ephys/open-ephys.exe"),
        address="localhost",
        port=37497,
    )
)
# Prefer reusing the OpenEphysApp already configured by your experiment.
# Constructing this object does not launch the GUI; mapping requires it running.
mapper = AindAcquisitionDataMapper(
    app=app,
    processor_id=101,  # Replace with the metadata generator ID in your signal chain.
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

The mapper supports `map()` (or CLABE's inherited `run()`), `is_mapped()`,
`mapped`, `session_schema()`, and `session_name`. Before successful mapping,
`is_mapped()` returns false and accessing `mapped`/`session_schema()` raises
`ValueError`. Each mapping fetches fresh history; a failed refresh invalidates
the previous result.

Acquisition start/end bounds are the earliest start and latest end across all
returned streams; stream order and device configurations are preserved.
Empty history, non-idle GUI state, missing/timezone-naive timestamps, reversed
stream bounds, and invalid schema fields are rejected. HTTP errors propagate.
Optional `stimulus_epochs` can be supplied by the experiment; no behavior-specific
stimulus metadata is fabricated.

**Lifecycle:** the caller must clear the metadata processor's history before
starting a new session, coordinate recording, stop acquisition, and then map
before closing the GUI. The mapper never clears history, starts/stops acquisition,
or writes files. It cannot detect whether the processor history includes an
earlier subject/session. The original `exampleMapper.py` remains a live
acquisition demonstration, not an offline test.

## Instrument metadata

`src/data_mappers/_instrument.py` provides `AindInstrumentDataMapper`, using the
same CLABE `map()`/`run()`, `mapped`, `is_mapped()`, and `rig_schema()` contract
as the VrForaging instrument mapper.

Supply exactly one configuration source: `xml_path` for offline mapping or
`app=app` with a configured `OpenEphysApp` to fetch the running GUI's
configuration through `app.client` using `GET /api/config`. Neither mapper
requires importing the private HTTP client class. Construction performs no HTTP
requests. Mapping does not launch the GUI, change recording state, or write files.

The XML provides computer name/OS and Neuropixels probes, slots, ports, part
numbers, and firmware. The mapper deduplicates repeated physical probe serials,
so the four quad-base entries in `src/example.xml` become one probe/assembly.
Disabled probes remain in the Instrument because it describes configured
hardware, not only the devices recorded in a particular acquisition.

The XML does **not** provide manipulator identities. Supply actual `Manipulator`
objects keyed by physical probe serial number, plus the instrument ID,
modification date, and coordinate system. Do not copy the example's identities
into real rig metadata.

```python
from datetime import date
from pathlib import Path

from aind_data_schema.components.coordinates import CoordinateSystemLibrary
from aind_data_schema.components.devices import Manipulator
from src.data_mappers import AindInstrumentDataMapper

# A rig-specific JSON object keyed by physical probe serial number.
import json
manipulators = {
    serial: Manipulator.model_validate(settings)
    for serial, settings in json.loads(
        Path("manipulators.json").read_text(encoding="utf-8")
    ).items()
}
mapper = AindInstrumentDataMapper(
    xml_path=Path("src/example.xml"),  # Or replace with app=app.
    instrument_id="EPHYS1",  # Supply the actual instrument identifier.
    modification_date=date(2026, 10, 23),  # Actual hardware modification date.
    coordinate_system=CoordinateSystemLibrary.BREGMA_ARI,  # Only if applicable.
    manipulators=manipulators,
    location="323",  # Optional; supply the actual location.
)
instrument = mapper.map()
instrument.write_standard_file(prefix="ephys")
```

One ephys assembly contains each probe and its supplied manipulator. Basestation
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

Tests mock all GUI HTTP requests and require no hardware. Run the corresponding
client tests from the CLABE root with `python -m pytest tests/apps/test_open_ephys.py`
in an environment with CLABE's test dependencies.
