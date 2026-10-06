"""Native input reads its exact modal field before the irreversible Enter."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "app/test/e2e/orca-guest.py"
spec = importlib.util.spec_from_file_location("orca_native_input", SOURCE)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class Node:
    def __init__(self, text=None, children=()):
        self.text, self.children = text, children

    def GetState(self, **kwargs):  # noqa: N802 - mirrors the AT-SPI D-Bus interface
        return [(1 << 12) | (1 << 7) if self.text is not None else 0, 0]

    def GetRole(self, **kwargs):  # noqa: N802
        return 79

    def GetChildren(self, **kwargs):  # noqa: N802 - mirrors the AT-SPI D-Bus interface
        return self.children

    def GetText(self, start, end, **kwargs):  # noqa: N802 - mirrors the AT-SPI D-Bus interface
        assert (start, end) == (0, len(self.text))
        return self.text

    def Get(self, interface, name, **kwargs):  # noqa: N802
        assert (interface, name) == ("org.a11y.atspi.Text", "CharacterCount")
        return len(self.text)


def binding(text):
    child = Node(text)
    root = Node(children=[(":1.2", "/field")])
    return SimpleNamespace(
        record={"peer": ":1.2", "path": "/modal"},
        bus=SimpleNamespace(get_object=lambda peer, path: child),
        atspi=SimpleNamespace(
            StateType=SimpleNamespace(FOCUSED=12, EDITABLE=7),
            Role=SimpleNamespace(ENTRY=79, TEXT=60),
        ),
        revalidate=lambda title: root,
    )


def test_native_field_exact_readback(capsys):
    result = helper.verify_native_text(
        binding("/private/file.txt"), "Attach files", "/private/file.txt"
    )
    assert result["text"] == "/private/file.txt"
    assert "native_field_readback" in capsys.readouterr().out


def test_describe_revalidates_modal_without_creating_input_device(monkeypatch):
    calls = []
    monkeypatch.setattr(helper, "active_dialog", lambda title: SimpleNamespace(
        revalidate=lambda current: calls.append(current)
    ))
    helper.native("Save file", "describe")
    assert calls == ["Save file"]


def test_native_field_mismatch_stops_submission():
    with pytest.raises(RuntimeError, match="no submission"):
        helper.verify_native_text(binding("wrong.txt"), "Attach files", "/private/file.txt")


def test_native_field_uses_explicit_count_for_gtk4_not_negative_end():
    result = helper.focused_native_text(binding("GTK4 location"), "Attach files")
    assert result["text"] == "GTK4 location"


def test_native_field_length_is_bounded():
    with pytest.raises(RuntimeError, match="outside bounds"):
        helper.focused_native_text(binding("x" * 4097), "Attach files")


def test_foreign_child_never_used():
    root = Node(children=[(":1.99", "/field")])
    b = binding("foreign")
    b.revalidate = lambda title: root
    b.bus.get_object = lambda *args: pytest.fail("foreign native child queried")
    with pytest.raises(RuntimeError, match="No focused"):
        helper.focused_native_text(b, "Attach files")


def test_focused_noneditable_container_never_supplies_native_field():
    b = binding("location")
    container = Node("")
    container.GetState = lambda **kwargs: [1 << 12, 0]
    root = Node(children=[(":1.2", "/container"), (":1.2", "/field")])
    b.revalidate = lambda title: root
    b.bus.get_object = lambda peer, path: container if path == "/container" else Node("location")
    assert helper.focused_native_text(b, "Attach files")["text"] == "location"


def test_evidence_prefix_is_constrained(monkeypatch):
    monkeypatch.setenv("ODIN_ORCA_NATIVE_EVIDENCE_PREFIX", "../escape")
    with pytest.raises(RuntimeError, match="Unknown native evidence"):
        helper.verify_native_text(binding("file.txt"), "Save file", "file.txt")


def test_evidence_records_observation_not_acceptance(monkeypatch, tmp_path):
    import json

    monkeypatch.setenv("ODIN_ORCA_NATIVE_EVIDENCE_PREFIX", "probe-native-attach")
    monkeypatch.setenv("ODIN_ORCA_EVIDENCE", str(tmp_path))
    calls = []
    monkeypatch.setattr(helper.subprocess, "run", lambda args, **kwargs: calls.append(args))
    helper.verify_native_text(binding("file.txt"), "Attach files", "file.txt")
    data = json.loads((tmp_path / "probe-native-attach-before-enter.json").read_text())
    assert data["focused_field"]["text"] == "file.txt"
    assert data["matches"] is True and data["acceptance_proven"] is False
    assert calls[0][-1].endswith("probe-native-attach-before-enter.png")


def test_modal_changes_during_readback_are_not_submitted():
    b = binding("file.txt")
    original = b.revalidate
    calls = []

    def revalidate(title):
        calls.append(title)
        if len(calls) == 2:
            raise RuntimeError("Native target changed")
        return original(title)

    b.revalidate = revalidate
    with pytest.raises(RuntimeError, match="target changed"):
        helper.verify_native_text(b, "Attach files", "file.txt")


def test_cycles_and_unfocused_fields_fail_bounded():
    b = binding("file.txt")
    root = Node(children=[(":1.2", "/modal")])
    b.revalidate = lambda title: root
    b.bus.get_object = lambda peer, path: root
    with pytest.raises(RuntimeError, match="No focused"):
        helper.focused_native_text(b, "Attach files")
