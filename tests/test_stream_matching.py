"""Physical probe identity comes from ordered streams, not hardware labels."""

from xml.etree import ElementTree as ET

import pytest

from data_mappers._instrument import _stream_probe_names


def processor(models, stream_names):
    result = ET.Element("PROCESSOR", name="Neuropix-PXI")
    for name in stream_names:
        ET.SubElement(result, "STREAM", name=name)
    parameters = ET.SubElement(ET.SubElement(result, "EDITOR"), "CUSTOM_PARAMETERS")
    for index, model in enumerate(models):
        # Quad Base exports one hardware entry for each shank.
        for _ in range(4 if model == "Neuropixels 2.0 Quad Base" else 1):
            ET.SubElement(
                parameters,
                "NP_PROBE",
                probe_name=model,
                probe_serial_number=str(index + 100),
                custom_probe_name="unrelated hardware label",
            )
    return result


@pytest.mark.parametrize(
    ("model", "names"),
    [
        ("Neuropixels 2.0 Quad Base", ["Rig-Probe-1", "Rig-Probe-2", "Rig-Probe-3", "Rig-Probe-4"]),
        ("Neuropixels 2.0 - Single Shank", ["Rig-Probe"]),
        ("Neuropixels 2.0 Single Shank", ["Rig-Probe"]),
        ("Neuropixels 2.0 - Multishank", ["Rig-Probe"]),
        ("Neuropixels 2.0 Multishank", ["Rig-Probe"]),
        ("Neuropixels 1.0", ["Rig-Probe-AP", "Rig-Probe-LFP"]),
        ("Neuropixels Opto", ["Rig-Probe-AP", "Rig-Probe-LFP"]),
        ("Neuropixels Ultra", ["Rig-Probe-AP", "Rig-Probe-LFP"]),
        ("Neuropixels Ultra (Switchable)", ["Rig-Probe-AP", "Rig-Probe-LFP"]),
    ],
)
def test_model_specific_stream_counts(model, names):
    result = _stream_probe_names(processor([model], names))
    assert set(result.values()) == {"Rig-Probe"}
    assert len(result) == (4 if model == "Neuropixels 2.0 Quad Base" else 1)


def test_mixed_models_advance_once_per_physical_probe():
    root = processor(
        [
            "Neuropixels Opto",
            "Neuropixels 2.0 Quad Base",
            "Neuropixels 2.0 Quad Base",
            "Neuropixels 2.0 - Multishank",
            "Neuropixels 2.0 - Single Shank",
            "Neuropixels 1.0",
        ],
        [
            "A-AP",
            "A-LFP",
            "B-1",
            "B-2",
            "B-3",
            "B-4",
            "C-1",
            "C-2",
            "C-3",
            "C-4",
            "D",
            "E",
            "F-AP",
            "F-LFP",
        ],
    )
    names = _stream_probe_names(root)
    assert [(entry.get("probe_serial_number"), name) for entry, name in names.items()] == [
        ("100", "A"),
        *[("101", "B")] * 4,
        *[("102", "C")] * 4,
        ("103", "D"),
        ("104", "E"),
        ("105", "F"),
    ]


@pytest.mark.parametrize("name", ["Probe-1", "Probe-AP", "Probe-with-hyphens"])
def test_single_stream_name_is_not_truncated(name):
    result = _stream_probe_names(processor(["Neuropixels 2.0 - Single Shank"], [name]))
    assert list(result.values()) == [name]


def test_stream_offsets_are_local_to_each_processor():
    first = processor(["Neuropixels Opto"], ["First-AP", "First-LFP"])
    second = processor(["Neuropixels 2.0 Quad Base"], ["Second-1", "Second-2", "Second-3", "Second-4"])
    assert set(_stream_probe_names(first).values()) == {"First"}
    assert set(_stream_probe_names(second).values()) == {"Second"}
    unrelated = ET.Element("PROCESSOR", name="Unrelated")
    ET.SubElement(unrelated, "STREAM", name="Not a probe")
    assert _stream_probe_names(unrelated) == {}


@pytest.mark.parametrize(
    ("model", "names"),
    [
        ("Neuropixels 2.0 - Single Shank", []),
        ("Neuropixels Opto", ["Probe-AP"]),
        ("Neuropixels 2.0 Quad Base", ["Probe-1", "Probe-2", "Probe-3"]),
    ],
)
def test_incomplete_stream_groups_are_rejected(model, names):
    with pytest.raises(ValueError, match="Expected .* streams for probe"):
        _stream_probe_names(processor([model], names))


def test_unmatched_streams_are_rejected():
    with pytest.raises(ValueError, match="Unmatched streams"):
        _stream_probe_names(processor(["Neuropixels 2.0 - Single Shank"], ["Probe", "Unexpected"]))


@pytest.mark.parametrize(
    ("model", "names"),
    [
        ("Neuropixels Opto", ["A-AP", "B-LFP"]),
        ("Neuropixels Opto", ["A-LFP", "A-AP"]),
        ("Neuropixels Opto", ["A", "A-LFP"]),
        ("Neuropixels 2.0 Quad Base", ["A-1", "A-2", "B-3", "A-4"]),
        ("Neuropixels 2.0 Quad Base", ["A-1", "A-2", "A-3", "A-3"]),
    ],
)
def test_inconsistent_stream_group_names_are_rejected(model, names):
    with pytest.raises(ValueError, match="Inconsistent probe stream names"):
        _stream_probe_names(processor([model], names))


@pytest.mark.parametrize("name", ["", " "])
def test_blank_stream_name_is_rejected(name):
    with pytest.raises(ValueError, match="missing required attribute 'name'"):
        _stream_probe_names(processor(["Neuropixels 2.0 - Single Shank"], [name]))
