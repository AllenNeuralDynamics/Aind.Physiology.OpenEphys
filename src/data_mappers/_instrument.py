"""Map Open Ephys Neuropixels configuration to AIND Instrument metadata."""

import logging
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from aind_data_schema.base import GenericModel
from aind_data_schema.components.connections import Connection
from aind_data_schema.components.coordinates import CoordinateSystem
from aind_data_schema.components.devices import (
    Computer,
    EphysAssembly,
    EphysProbe,
    Manipulator,
    NeuropixelsBasestation,
    ProbePort,
)
from aind_data_schema.core.instrument import Instrument
from aind_data_schema_models.devices import ProbeModel
from aind_data_schema_models.modalities import Modality
from clabe.apps.open_ephys import OpenEphysGuiClient
from clabe.data_mapper import aind_data_schema as ads

logger = logging.getLogger(__name__)

_PROBE_MODELS = {
    "Neuropixels 1.0": ProbeModel.NP1,
    "Neuropixels 2.0 - Single Shank": ProbeModel.NP2_SINGLE_SHANK,
    "Neuropixels 2.0 - Multishank": ProbeModel.NP2_MULTI_SHANK,
    "Neuropixels 2.0 Quad Base": ProbeModel.NP2_QUAD_BASE,
    "Neuropixels Ultra" : ProbeModel.NP_UHD_FIXED,
    "Neuropixels Ultra (Phase 1)": ProbeModel.NP_UHD_FIXED,
    "Neuropixels Ultra (Phase 3, Type 1)": ProbeModel.NP_UHD_FIXED,
    "Neuropixels Ultra (Phase 3, Type 2)": ProbeModel.NP_UHD_FIXED,
    "Neuropixels Ultra (Phase 3, Type 3)": ProbeModel.NP_UHD_FIXED,
    "Neuropixels Ultra (Switchable)": ProbeModel.NP_UHD_SWITCHABLE,
    "Neuropixels Opto": ProbeModel.NP_OPTO_DEMONSTRATOR
}


def _required(element: ET.Element, attribute: str) -> str:
    value = element.get(attribute, "").strip()
    if not value:
        raise ValueError(f"{element.tag} is missing required attribute '{attribute}'.")
    return value


def _positive_int(element: ET.Element, attribute: str) -> int:
    value = int(_required(element, attribute))
    if value < 1:
        raise ValueError(f"{element.tag} attribute '{attribute}' must be positive.")
    return value


class AindInstrumentDataMapper(ads.AindDataSchemaRigDataMapper):
    """Build ephys hardware metadata from a saved or running GUI configuration.

    Supply exactly one of ``client`` or ``xml_path``. Manipulators must be
    supplied by probe serial number: the GUI XML does not describe them.
    Instrument identity, modification date, and coordinate system are explicit
    caller inputs, not inferred from the computer or XML save date.

    All configured probes are included, even when disabled for acquisition.
    Repeated shank entries are deduplicated by physical probe serial number.
    Mapping only reads configuration; it never controls recording or writes files.
    """

    def __init__(
        self,
        *,
        instrument_id: str,
        modification_date: date,
        coordinate_system: CoordinateSystem,
        manipulators: Mapping[str, Manipulator],
        client: OpenEphysGuiClient | None = None,
        xml_path: str | Path | None = None,
        location: str | None = None,
        session_name: str | None = None,
    ) -> None:
        if (client is None) == (xml_path is None):
            raise ValueError("Supply exactly one of client or xml_path.")
        self.client = client
        self.xml_path = Path(xml_path) if xml_path is not None else None
        self.instrument_id = instrument_id
        self.modification_date = modification_date
        self.coordinate_system = coordinate_system
        self.manipulators = dict(manipulators)
        self.location = location
        self._session_name = session_name
        self._mapped: Instrument | None = None

    @property
    def session_name(self) -> str:
        """Return the optional session association."""
        if self._session_name is None:
            raise ValueError("Session name was not supplied to the instrument mapper.")
        return self._session_name

    def rig_schema(self) -> Instrument:
        """Return the last successfully mapped Instrument."""
        return self.mapped

    def map(self) -> Instrument:
        """Read fresh XML and map it, invalidating any prior cached result."""
        logger.info("Mapping Open Ephys Instrument metadata.")
        self._mapped = None
        if self.client is not None:
            root = ET.fromstring(self.client.get_config())
        else:
            assert self.xml_path is not None
            root = ET.parse(self.xml_path).getroot()
        self._mapped = self._map(root)
        return self._mapped

    def _map(self, root: ET.Element) -> Instrument:
        if root.tag != "SETTINGS":
            raise ValueError("Expected an Open Ephys SETTINGS XML document.")
        machine = root.find("INFO/MACHINE")
        if machine is None:
            raise ValueError("Configuration is missing INFO/MACHINE.")
        computer = Computer(
            name=_required(machine, "name"),
            operating_system=root.findtext("INFO/OS"),
        )
        entries = root.findall("./SIGNALCHAIN/PROCESSOR/EDITOR/CUSTOM_PARAMETERS/NP_PROBE")
        if not entries:
            raise ValueError("Configuration contains no supported NP_PROBE hardware entries.")
        probes: dict[str, tuple[ET.Element, tuple[int, int, int]]] = {}
        basestations: dict[int, dict[str, str]] = {}
        occupied: dict[tuple[int, int, int], str] = {}
        ports: dict[int, dict[int, list[str]]] = {}
        assemblies = []
        names = {computer.name}
        for entry in entries:
            serial = _required(entry, "probe_serial_number")
            if serial in {"0", "UNKNOWN"}:
                raise ValueError("A physical probe must have a known, nonzero serial number.")
            address = tuple(_positive_int(entry, key) for key in ("slot", "port", "dock"))
            slot, port, _dock = address
            hardware = {
                key: _required(entry, key)
                for key in ("bs_firmware_version", "bsc_firmware_version", "bsc_serial_number", "bs_part_number")
            }
            hardware["bs_serial_number"] = entry.get("bs_serial_number", "")
            if slot in basestations and hardware != basestations[slot]:
                raise ValueError(f"Conflicting basestation hardware for slot {slot}.")
            basestations[slot] = hardware
            if address in occupied and occupied[address] != serial:
                raise ValueError(f"Multiple physical probes assigned to slot/port/dock {address}.")
            occupied[address] = serial
            if serial in probes:
                previous, previous_address = probes[serial]
                keys = ("custom_probe_name", "probe_name", "probe_part_number")
                if address != previous_address or any(entry.get(k) != previous.get(k) for k in keys):
                    raise ValueError(f"Conflicting hardware entries for probe {serial}.")
                continue
            probes[serial] = (entry, address)
            probe_name = entry.get("custom_probe_name", "").strip() or serial
            model_name = _required(entry, "probe_name")
            if model_name not in _PROBE_MODELS:
                raise ValueError(f"Unsupported probe model '{model_name}' for probe {serial}.")
            if serial not in self.manipulators:
                raise ValueError(f"Supply a manipulator for probe serial {serial}.")
            assembly_name = f"Ephys_assembly{probe_name}"
            for name in (probe_name, assembly_name):
                if name in names:
                    raise ValueError(f"Duplicate hardware name '{name}'.")
                names.add(name)
            probe = EphysProbe(
                name=probe_name,
                serial_number=serial,
                model=_required(entry, "probe_part_number"),
                probe_model=_PROBE_MODELS[model_name],
            )
            assemblies.append(EphysAssembly(name=assembly_name, manipulator=self.manipulators[serial], probes=[probe]))
            ports.setdefault(slot, {}).setdefault(port, []).append(probe_name)
        stations = [
            NeuropixelsBasestation(
                name=f"Basestation Slot {slot}",
                slot=slot,
                basestation_firmware_version=hardware["bs_firmware_version"],
                bsc_firmware_version=hardware["bsc_firmware_version"],
                serial_number=(
                    hardware["bs_serial_number"] if hardware["bs_serial_number"] not in {"", "0", "UNKNOWN"} else None
                ),
                additional_settings=GenericModel.model_validate(hardware),
                model=hardware["bs_part_number"],
                ports=[ProbePort(index=port, probes=probe_names) for port, probe_names in ports[slot].items()],
            )
            for slot, hardware in basestations.items()
        ]
        return Instrument(
            instrument_id=self.instrument_id,
            location=self.location,
            modification_date=self.modification_date,
            global_coordinate_system=self.coordinate_system,
            modalities=[Modality.ECEPHYS],
            components=[*assemblies, *stations, computer],
            connections=[Connection(source_device=station.name, target_device=computer.name) for station in stations],
        )
