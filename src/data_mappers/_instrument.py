"""Map Open Ephys Neuropixels configuration to AIND Instrument metadata."""

import logging
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from aind_data_schema.base import GenericModel
from aind_data_schema.components.configs import EphysAssemblyConfig
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
from aind_data_schema.core.acquisition import Acquisition
from aind_data_schema.core.instrument import Instrument
from aind_data_schema_models.devices import ProbeModel
from aind_data_schema_models.modalities import Modality
from aind_data_schema_models.organizations import Organization

from ._base import DataMapper
from ._dataset import find_settings_xml

logger = logging.getLogger(__name__)

_PROBE_MODELS = {
    "Neuropixels 1.0": ProbeModel.NP1,
    "Neuropixels 2.0 - Single Shank": ProbeModel.NP2_SINGLE_SHANK,
    "Neuropixels 2.0 Single Shank": ProbeModel.NP2_SINGLE_SHANK,
    "Neuropixels 2.0 - Multishank": ProbeModel.NP2_MULTI_SHANK,
    "Neuropixels 2.0 Multishank": ProbeModel.NP2_MULTI_SHANK,
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


def _stream_group_name(streams: list[ET.Element], count: int) -> str:
    """Read a probe's name while checking its band/shank stream suffixes."""
    names = [_required(stream, "name") for stream in streams]
    if count == 1:
        return names[0]
    suffixes = ["-1", "-2", "-3", "-4"] if count == 4 else ["-AP", "-LFP"]
    name = names[0].removesuffix(suffixes[0])
    if not name or names != [name + suffix for suffix in suffixes]:
        raise ValueError(f"Inconsistent probe stream names: {names}; expected common name with suffixes {suffixes}.")
    return name


def _stream_probe_names(processor: ET.Element) -> dict[ET.Element, str]:
    """Match streams to physical probes in saved processor order."""
    entries = processor.findall("./EDITOR/CUSTOM_PARAMETERS/NP_PROBE")
    if not entries:
        return {}
    streams = processor.findall("STREAM")
    offset = 0
    physical_names: dict[str, str] = {}
    names: dict[ET.Element, str] = {}
    for entry in entries:
        serial = _required(entry, "probe_serial_number")
        if serial in {"0", "UNKNOWN"}:
            raise ValueError("A physical probe must have a known, nonzero serial number.")
        if serial not in physical_names:
            model_name = _required(entry, "probe_name")
            if model_name not in _PROBE_MODELS:
                raise ValueError(f"Unsupported probe model '{model_name}' for probe {serial}.")
            model = _PROBE_MODELS[model_name]
            if model == ProbeModel.NP2_QUAD_BASE:
                count = 4
            elif model in {ProbeModel.NP2_SINGLE_SHANK, ProbeModel.NP2_MULTI_SHANK}:
                count = 1
            else:
                count = 2
            group = streams[offset : offset + count]
            if len(group) != count:
                raise ValueError(f"Expected {count} streams for probe {serial}, found {len(group)}.")
            physical_names[serial] = _stream_group_name(group, count)
            offset += count
        names[entry] = physical_names[serial]
    if offset != len(streams):
        raise ValueError(f"Unmatched streams in processor {_required(processor, 'name')}: {len(streams) - offset}.")
    return names


class AindInstrumentDataMapper(DataMapper[Instrument]):
    """Build ephys hardware metadata from a saved Open Ephys dataset.

    Read the first settings.xml in sorted ``Record Node XXX`` directories
    under ``data_dir``, never the live GUI configuration. Probe-to-manipulator
    associations come from the supplied Acquisition's EphysAssemblyConfig
    objects, matched to names derived from ordered XML STREAM groups. Each
    physical probe consumes four streams for Quad Base, one for NP2 single-
    or multishank, and two for other supported models. AP/LFP and numbered
    shank suffixes are removed; custom_probe_name is not used.
    Manufacturer is explicitly unknown;
    acquisition configurations do not describe manipulator hardware details.
    Instrument identity, modification date, and coordinate system are explicit
    caller inputs, not inferred from the computer or XML save date.

    All configured probes are included, even when disabled for acquisition.
    Repeated shank entries are deduplicated by physical probe serial number.
    Mapping only reads configuration; it never controls recording or writes files.
    """

    def __init__(
        self,
        data_dir: str | Path,
        *,
        instrument_id: str,
        modification_date: date,
        coordinate_system: CoordinateSystem,
        acquisition: Acquisition,
        location: str | None = None,
        session_name: str | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.instrument_id = instrument_id
        self.modification_date = modification_date
        self.coordinate_system = coordinate_system
        self.acquisition = acquisition
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
        root = ET.parse(find_settings_xml(self.data_dir)).getroot()
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
        stream_names = {}
        for processor in root.findall("./SIGNALCHAIN/PROCESSOR"):
            stream_names.update(_stream_probe_names(processor))
        probes: dict[str, tuple[ET.Element, tuple[int, int, int]]] = {}
        basestations: dict[int, dict[str, str]] = {}
        occupied: dict[tuple[int, int, int], str] = {}
        ports: dict[int, dict[int, list[str]]] = {}
        associations = self._probe_associations()
        assemblies: dict[str, EphysAssembly] = {}
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
                keys = ("probe_name", "probe_part_number")
                if address != previous_address or any(entry.get(k) != previous.get(k) for k in keys):
                    raise ValueError(f"Conflicting hardware entries for probe {serial}.")
                if stream_names[entry] != stream_names[previous]:
                    raise ValueError(f"Conflicting stream names for probe {serial}.")
                continue
            probes[serial] = (entry, address)
            probe_name = stream_names[entry]
            model_name = _required(entry, "probe_name")
            if probe_name in names:
                raise ValueError(f"Duplicate hardware name '{probe_name}'.")
            names.add(probe_name)
            if probe_name not in associations:
                raise ValueError(f"No acquisition manipulator association for probe '{probe_name}' (serial {serial}).")
            assembly_name, manipulator_name = associations[probe_name]
            probe = EphysProbe(
                name=probe_name,
                serial_number=serial,
                model=_required(entry, "probe_part_number"),
                probe_model=_PROBE_MODELS[model_name],
            )
            self._add_probe(assemblies, names, assembly_name, manipulator_name, probe)
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
            components=[*assemblies.values(), *stations, computer],
            connections=[Connection(source_device=station.name, target_device=computer.name) for station in stations],
        )

    @staticmethod
    def _add_probe(
        assemblies: dict[str, EphysAssembly],
        names: set[str],
        assembly_name: str,
        manipulator_name: str,
        probe: EphysProbe,
    ) -> None:
        if assembly_name in assemblies:
            assemblies[assembly_name].probes.append(probe)
            return
        if assembly_name in names:
            raise ValueError(f"Duplicate hardware name '{assembly_name}'.")
        names.add(assembly_name)
        assemblies[assembly_name] = EphysAssembly(
            name=assembly_name,
            manipulator=Manipulator(name=manipulator_name, manufacturer=Organization.UNKNOWN),
            probes=[probe],
        )

    def _probe_associations(self) -> dict[str, tuple[str, str]]:
        associations: dict[str, tuple[str, str]] = {}
        manipulators: dict[str, str] = {}
        for stream in self.acquisition.data_streams:
            for config in stream.configurations:
                if not isinstance(config, EphysAssemblyConfig):
                    continue
                assembly_name = config.device_name.strip()
                manipulator_name = config.manipulator.device_name.strip()
                if not assembly_name or not manipulator_name:
                    raise ValueError("Acquisition ephys assembly and manipulator device names must not be blank.")
                if assembly_name in manipulators and manipulators[assembly_name] != manipulator_name:
                    raise ValueError(f"Conflicting acquisition manipulators for assembly '{assembly_name}'.")
                manipulators[assembly_name] = manipulator_name
                for probe in config.probes:
                    probe_name = probe.device_name.strip()
                    if not probe_name:
                        raise ValueError(f"Acquisition probe device name must not be blank in '{assembly_name}'.")
                    association = (assembly_name, manipulator_name)
                    if probe_name in associations and associations[probe_name] != association:
                        raise ValueError(f"Conflicting acquisition association for probe '{probe_name}'.")
                    associations[probe_name] = association
        return associations
