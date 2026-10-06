"""Rootless protocol/process models; never connect a real accessibility bus."""

import importlib.util
import json
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).parents[1] / "scripts/qualification/lab/guest/native_dialog_events.py"
spec = importlib.util.spec_from_file_location("native_dialog_events_test", SOURCE)
events = importlib.util.module_from_spec(spec)
spec.loader.exec_module(events)


class Message:
    def __init__(
        self,
        interface="Window",
        member="Activate",
        signature="siiv(so)",
        args=None,
        sender=":1.42",
        path="/org/a11y/atspi/accessible/7",
    ):
        self.interface, self.member, self.signature = interface, member, signature
        self.args = args if args is not None else ["", 0, 0, "", (":1.99", "/root")]
        self.sender, self.path = sender, path

    def get_interface(self):
        return "org.a11y.atspi.Event." + self.interface

    def get_member(self):
        return self.member

    def get_signature(self):
        return self.signature

    def get_args_list(self):
        return self.args

    def get_sender(self):
        return self.sender

    def get_path(self):
        return self.path


@pytest.mark.parametrize("signature", ["siiv(so)", "siiva{sv}"])
def test_actual_event_source_is_message_sender_and_path_not_trailer_or_variant(signature):
    reference = events.event_reference(Message(signature=signature))
    assert reference == {
        "peer": ":1.42",
        "path": "/org/a11y/atspi/accessible/7",
        "event": "window:activate",
        "signature": signature,
    }
    reference = events.event_reference(
        Message(
            interface="Object",
            member="StateChanged",
            signature=signature,
            args=["active", 1, 0, (":9.99", "/foreign"), {}],
        )
    )
    assert reference["peer"] == ":1.42"
    assert reference["event"] == "object:state-changed:active"


@pytest.mark.parametrize(
    "message",
    [
        Message(signature="siiv"),
        Message(args=[]),
        Message(sender="org.example.App"),
        Message(sender="None"),
        Message(path="/"),
    ],
)
def test_unknown_event_source_or_signature_rejected(message):
    with pytest.raises(RuntimeError):
        events.event_reference(message)


@pytest.mark.parametrize(
    "message",
    [
        Message(interface="Object", member="StateChanged", args=["showing", 1, 0, "", {}]),
        Message(member="Deactivate"),
        Message(interface="ScreenReader"),
    ],
)
def test_only_native_activation_events_supply_sources(message):
    assert events.event_reference(message) is None


@pytest.fixture
def model(monkeypatch):
    identity = {"pid": 400, "uid": 1001, "exe": "/lab/electron", "start": "987"}
    state = {
        "identity": identity.copy(),
        "bus_uid": 1001,
        "pid": 400,
        "name": "Attach files",
        "role": 43,
        "words": [3, 0],
    }
    calls = []
    item = SimpleNamespace(
        Get=lambda *args, **kw: state["name"],
        GetRole=lambda **kw: state["role"],
        GetState=lambda **kw: state["words"],
    )

    def get_object(peer, path):
        calls.append((peer, path))
        if peer == "org.freedesktop.DBus":
            return SimpleNamespace(GetConnectionUnixProcessID=lambda *args, **kw: state["pid"])
        assert (peer, path) == (":1.42", "/org/a11y/atspi/accessible/7")
        return item

    bus = SimpleNamespace(get_unix_user=lambda _: state["bus_uid"], get_object=get_object)
    atspi = SimpleNamespace(
        Role=SimpleNamespace(DIALOG=16, FILE_CHOOSER=43),
        StateType=SimpleNamespace(ACTIVE=0, SHOWING=1),
    )
    record = {
        "type": "source",
        "event": "window:activate",
        "peer": ":1.42",
        "path": "/org/a11y/atspi/accessible/7",
        "identity": identity,
    }
    monkeypatch.setattr(events.os, "geteuid", lambda: 1001)
    monkeypatch.setenv("ODIN_ORCA_ELECTRON", "/lab/electron")
    monkeypatch.setenv("ODIN_ORCA_DESKTOP", "gnome")
    monkeypatch.setattr(events, "trusted_executable", lambda filename: None)
    monkeypatch.setattr(events, "bus_connection", lambda: (bus, "unix:guest"))
    monkeypatch.setattr(events, "read_events", lambda *args: [])

    def process(pid):
        result = state["identity"].copy()
        result["pid"] = pid
        return result

    monkeypatch.setattr(events, "process_identity", process)
    return state, bus, atspi, record, item, calls


def test_unregistered_real_source_lookup_queries_only_observed_reference(model):
    _, bus, atspi, record, item, calls = model
    binding = events.DialogBinding(bus, record, atspi)
    assert binding.revalidate("Attach files") is item
    assert (":1.42", "/org/a11y/atspi/accessible/7") in calls
    assert not any(path.endswith("root") or "cache" in path for _, path in calls)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bus_uid", 0),
        ("pid", 401),
        ("name", "terminal"),
        ("role", 23),
        ("words", [1, 0]),
        ("words", [2, 0]),
        ("words", [0, 0]),
        ("words", [3]),
    ],
)
def test_foreign_or_stale_pid_title_role_state_rejected(model, field, value):
    state, bus, atspi, record, _, _ = model
    state[field] = value
    with pytest.raises(RuntimeError):
        events.DialogBinding(bus, record, atspi).revalidate("Attach files")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("uid", 0),
        ("exe", "/usr/bin/terminal"),
        ("exe", "/different/electron"),
        ("start", "988"),
    ],
)
def test_foreign_process_owner_executable_or_pid_reuse_rejected(model, field, value):
    state, bus, atspi, record, _, _ = model
    state["identity"][field] = value
    with pytest.raises(RuntimeError):
        events.DialogBinding(bus, record, atspi).revalidate("Attach files")


def test_credentials_rechecked_after_accessible_queries(model):
    state, bus, atspi, record, item, _ = model

    def get_state(**kw):
        state["pid"] = 401
        return [3, 0]

    item.GetState = get_state
    with pytest.raises(RuntimeError, match="changed during validation"):
        events.DialogBinding(bus, record, atspi).revalidate("Attach files")


@pytest.mark.parametrize("title", events.TITLES)
def test_exact_portal_backend_real_source_and_states_supported(model, title):
    state, bus, atspi, record, item, _ = model
    record["identity"]["exe"] = "/usr/libexec/xdg-desktop-portal-gnome"
    state["identity"] = record["identity"].copy()
    state["name"] = title
    assert events.DialogBinding(bus, record, atspi).revalidate(title) is item


@pytest.mark.parametrize(
    "change",
    [
        "foreignexe", "uid", "start", "pid", "inactive", "hidden",
        "title", "role", "desktop", "untrusted",
    ],
)
def test_portal_binding_rejects_foreign_stale_or_untrusted_sources(model, monkeypatch, change):
    state, bus, atspi, record, _, _ = model
    record["identity"]["exe"] = "/usr/libexec/xdg-desktop-portal-gnome"
    state["identity"] = record["identity"].copy()
    if change == "foreignexe":
        state["identity"]["exe"] = "/tmp/xdg-desktop-portal-gnome"
    elif change in ("uid", "start"):
        state["identity"][change] = 0 if change == "uid" else "stale"
    elif change == "pid":
        state["pid"] += 1
    elif change in ("inactive", "hidden"):
        state["words"] = [2 if change == "inactive" else 1, 0]
    elif change == "title":
        state["name"] = "Authentication Required"
    elif change == "role":
        state["role"] = 23
    elif change == "desktop":
        monkeypatch.setenv("ODIN_ORCA_DESKTOP", "kde")
    else:
        def reject(filename):
            raise RuntimeError("writable executable")
        monkeypatch.setattr(events, "trusted_executable", reject)
    with pytest.raises(RuntimeError):
        events.DialogBinding(bus, record, atspi).revalidate("Attach files")


def test_actual_gtk4_portal_event_path_accepted_not_arbitrary_namespace():
    path = "/org/gtk/application/xdg_desktop_portal_gnome/a11y/8d94a6f5_862e_4f84_90f2_626f890bb694"
    assert events.event_reference(Message(path=path))["path"] == path
    with pytest.raises(RuntimeError):
        events.event_reference(Message(path=path.replace("portal_gnome", "terminal")))


@pytest.mark.parametrize(
    "defect", [None, "owner", "writable", "ancestor", "symlink", "not-file", "not-executable"]
)
def test_executable_trust_checks_exact_canonical_file_and_every_ancestor(monkeypatch, defect):
    class ModelPath:
        def __init__(self, name):
            self.name = name

        def __eq__(self, other):
            return self.name == getattr(other, "name", None)

        def is_absolute(self):
            return True

        def resolve(self, strict):
            return ModelPath("/other") if defect == "symlink" else self

        @property
        def parents(self):
            return [ModelPath("/usr/libexec"), ModelPath("/usr"), ModelPath("/")]

        def stat(self):
            file = self.name.endswith("portal-gnome")
            mode = stat.S_IFREG | 0o755 if file else stat.S_IFDIR | 0o755
            uid = 1001 if defect == "owner" and file else 0
            if defect == "writable" and file or defect == "ancestor" and self.name == "/usr":
                mode |= 0o020
            if defect == "not-file" and file:
                mode = stat.S_IFDIR | 0o755
            if defect == "not-executable" and file:
                mode = stat.S_IFREG | 0o644
            return SimpleNamespace(st_uid=uid, st_mode=mode)

    monkeypatch.setattr(events, "Path", ModelPath)
    if defect is None:
        events.trusted_executable("/usr/libexec/xdg-desktop-portal-gnome")
    else:
        with pytest.raises(RuntimeError):
            events.trusted_executable("/usr/libexec/xdg-desktop-portal-gnome")


def test_other_dialog_titles_are_never_authorized(model):
    state, bus, atspi, record, _, _ = model
    state["name"] = "Authentication Required"
    with pytest.raises(RuntimeError):
        events.DialogBinding(bus, record, atspi).revalidate(state["name"])


def test_real_inactive_event_revokes_source_not_activation():
    reference = events.event_reference(
        Message(interface="Object", member="StateChanged", args=["active", 0, 0, "", {}])
    )
    assert reference["event"] == "object:state-changed:inactive"
    assert reference["event"] not in events.EVENTS


@pytest.mark.parametrize("revoke", [None, "inactive", "other-source", "hidden", "not-modal"])
def test_gtk4_portal_active_event_state_requires_live_unrevoked_modal(model, monkeypatch, revoke):
    state, bus, atspi, record, item, _ = model
    record["identity"]["exe"] = "/usr/libexec/xdg-desktop-portal-gnome"
    state["identity"] = record["identity"].copy()
    record["event"] = "object:state-changed:active"
    atspi.StateType.MODAL = 2
    state["words"] = [6, 0]  # GTK4 SHOWING|MODAL, no GetState ACTIVE bit.
    latest = record.copy()
    if revoke == "inactive":
        latest["event"] = "object:state-changed:inactive"
    elif revoke == "other-source":
        latest["path"] += "other"
    elif revoke == "hidden":
        state["words"] = [4, 0]
    elif revoke == "not-modal":
        state["words"] = [2, 0]
    monkeypatch.setattr(events, "bus_connection", lambda: (bus, "unix:guest"))
    monkeypatch.setattr(events, "read_events", lambda *args: [record, latest])
    binding = events.DialogBinding(bus, record, atspi)
    if revoke is None:
        assert binding.revalidate("Attach files") is item
    else:
        with pytest.raises(RuntimeError):
            binding.revalidate("Attach files")


def test_lookup_deduplicates_current_source_and_returns_binding(model, monkeypatch):
    _, bus, atspi, record, _, calls = model
    monkeypatch.setitem(sys.modules, "gi", SimpleNamespace(require_version=lambda *args: None))
    monkeypatch.setitem(sys.modules, "gi.repository", SimpleNamespace(Atspi=atspi))
    monkeypatch.setattr(events, "bus_connection", lambda: (bus, "unix:guest"))
    monkeypatch.setattr(events, "read_events", lambda *args: [record, record])
    assert isinstance(events.active_dialog("Attach files"), events.DialogBinding)
    assert sum(peer == ":1.42" for peer, _ in calls) == 1


def test_missing_current_target_fails_closed_no_root_or_cache_fallback(model, monkeypatch):
    state, bus, atspi, record, _, calls = model
    state["words"] = [0, 0]
    monkeypatch.setitem(sys.modules, "gi", SimpleNamespace(require_version=lambda *args: None))
    monkeypatch.setitem(sys.modules, "gi.repository", SimpleNamespace(Atspi=atspi))
    monkeypatch.setattr(events, "bus_connection", lambda: (bus, "unix:guest"))
    monkeypatch.setattr(events, "read_events", lambda *args: [record, record])
    with pytest.raises(RuntimeError, match="No owned active"):
        events.active_dialog("Attach files")
    assert sum(peer == ":1.42" for peer, _ in calls) == 1


def test_registry_registration_uses_same_stable_bus_and_sass_arguments():
    calls = []
    registry = SimpleNamespace(RegisterEvent=lambda *args, **kw: calls.append((args, kw)))
    bus = SimpleNamespace(
        add_signal_receiver=lambda *args, **kw: calls.append((args, kw)),
        get_object=lambda peer, path: registry,
    )
    dbus = SimpleNamespace(Array=lambda values, signature: (values, signature))

    def callback(*args):
        pass

    assert events.register(bus, dbus, callback) is registry
    assert len(calls) == 4
    assert all(call[1]["message_keyword"] == "message" for call in calls[:2])
    assert [args for args, _ in calls[2:]] == [
        ("window:activate", ([], "s"), ""),
        ("object:state-changed:active", ([], "s"), ""),
    ]


@pytest.fixture
def evidence_model(monkeypatch):
    identity = {"pid": 200, "uid": 1001, "exe": "/usr/bin/python3", "start": "1"}
    ready = {
        "type": "ready",
        "address": "unix:guest",
        "collector_peer": ":1.2",
        "collector": identity,
        "run": "this-run",
        "started_ns": 100,
    }
    record = {"type": "source", "run": "this-run", "observed_ns": 200}
    state = {
        "lines": [ready, record],
        "mode": stat.S_IFREG | 0o600,
        "uid": 1001,
        "bound": True,
        "cmd": b"python3\0/lab/native_dialog_events.py\0",
    }

    class ModelPath:
        def __init__(self, value):
            self.value = str(value)

        def __eq__(self, other):
            return self.value == getattr(other, "value", str(other))

        def resolve(self):
            if self.value.endswith("/fd/8") and state["bound"]:
                return ModelPath("/lab/evidence/events.jsonl")
            return self

        def stat(self):
            return SimpleNamespace(st_mode=state["mode"], st_uid=state["uid"], st_size=500)

        def read_text(self):
            return "\n".join(json.dumps(line) for line in state["lines"])

        def joinpath(self, name):
            return ModelPath(self.value + "/" + name)

        def read_bytes(self):
            return state["cmd"]

        def iterdir(self):
            return iter([ModelPath(self.value + "/8")])

        @property
        def name(self):
            return self.value.rsplit("/", 1)[-1]

    monkeypatch.setattr(events, "Path", ModelPath)
    monkeypatch.setattr(events, "event_path", lambda: ModelPath("/lab/evidence/events.jsonl"))
    monkeypatch.setattr(events.os, "geteuid", lambda: 1001)
    monkeypatch.setattr(events, "peer_identity", lambda *args: identity.copy())
    monkeypatch.setattr(events.time, "monotonic_ns", lambda: 300)
    return state, ready, record


def test_private_live_current_run_evidence_accepted(evidence_model):
    _, _, record = evidence_model
    assert events.read_events(object(), "unix:guest") == [record]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", stat.S_IFREG | 0o644),
        ("mode", stat.S_IFSOCK | 0o600),
        ("uid", 0),
        ("bound", False),
        ("cmd", b"python3\0anonymous.py\0"),
    ],
)
def test_private_collector_file_process_binding_required(evidence_model, field, value):
    state, _, _ = evidence_model
    state[field] = value
    with pytest.raises(RuntimeError):
        events.read_events(object(), "unix:guest")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type", "log"),
        ("address", "unix:host"),
        ("collector", {"pid": 201, "uid": 1001, "exe": "/usr/bin/python3", "start": "1"}),
    ],
)
def test_collector_ready_bus_and_live_identity_must_match(evidence_model, field, value):
    _, ready, _ = evidence_model
    ready[field] = value
    with pytest.raises(RuntimeError):
        events.read_events(object(), "unix:guest")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run", "prior-run"),
        ("observed_ns", 99),
        ("observed_ns", 301),
        ("type", "orca-log"),
    ],
)
def test_records_before_ready_future_or_other_run_are_not_authority(evidence_model, field, value):
    _, _, record = evidence_model
    record[field] = value
    assert events.read_events(object(), "unix:guest") == []


def test_old_observation_expired(evidence_model, monkeypatch):
    monkeypatch.setattr(events.time, "monotonic_ns", lambda: 60_000_000_301)
    assert events.read_events(object(), "unix:guest") == []


def test_process_identity_uses_proc_uid_exe_and_start_field_not_process_name(monkeypatch):
    class ModelPath:
        def __init__(self, value):
            self.value = str(value)

        def joinpath(self, name):
            return ModelPath(self.value + "/" + name)

        def stat(self):
            assert self.value == "/proc/400"
            return SimpleNamespace(st_uid=1001)

        def read_text(self):
            assert self.value == "/proc/400/stat"
            return "400 (electron ) arbitrary spaces) " + " ".join(str(n) for n in range(3, 53))

        def resolve(self, strict):
            assert strict and self.value == "/proc/400/exe"
            return "/lab/electron"

    monkeypatch.setattr(events, "Path", ModelPath)
    assert events.process_identity(400) == {
        "pid": 400,
        "uid": 1001,
        "exe": "/lab/electron",
        "start": "22",
    }


def test_native_lookup_wrapper_loads_shipped_collector_without_connecting_host_bus(monkeypatch):
    source = SOURCE.parents[4] / "app/test/e2e/orca-guest.py"
    spec = importlib.util.spec_from_file_location("orca_guest_wrapper", source)
    guest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guest)
    target = object()

    def load(name, path):
        assert Path(path) == SOURCE
        return SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _: None))

    monkeypatch.setattr(importlib.util, "spec_from_file_location", load)
    monkeypatch.setattr(
        importlib.util,
        "module_from_spec",
        lambda _: SimpleNamespace(active_dialog=lambda title: target),
    )
    assert guest.active_dialog("Attach files") is target


def test_event_file_only_in_current_run_evidence_directory(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    path = evidence / "native-dialog-events.jsonl"
    monkeypatch.setenv("ODIN_ORCA_ROOT", str(tmp_path))
    monkeypatch.setenv("ODIN_ORCA_DIALOG_EVENTS", str(path))
    assert events.event_path() == path
    monkeypatch.setenv("ODIN_ORCA_DIALOG_EVENTS", str(tmp_path / "outside.jsonl"))
    with pytest.raises(RuntimeError, match="private evidence"):
        events.event_path()
    path.symlink_to(tmp_path / "outside.jsonl")
    monkeypatch.setenv("ODIN_ORCA_DIALOG_EVENTS", str(path))
    with pytest.raises(RuntimeError, match="private evidence"):
        events.event_path()


def test_collector_ready_header_precedes_only_post_registration_real_source(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    identity = {"pid": 200, "uid": 1001, "exe": "/usr/bin/python3", "start": "1"}
    callbacks, teardown = [], []
    monkeypatch.setenv("ODIN_ORCA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        importlib.util,
        "spec_from_file_location",
        lambda *args: SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _: None)),
    )
    monkeypatch.setattr(
        importlib.util, "module_from_spec", lambda _: SimpleNamespace(guard=lambda: None)
    )
    monkeypatch.setitem(sys.modules, "dbus", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules, "dbus.mainloop.glib", SimpleNamespace(DBusGMainLoop=lambda **kw: None)
    )
    bus = SimpleNamespace(get_unique_name=lambda: ":1.2", close=lambda: teardown.append("close"))
    registry = SimpleNamespace(DeregisterEvent=lambda event, **kw: teardown.append(event))

    def register(bus, dbus, callback):
        # dbus-python can dispatch while synchronous registration waits.
        callback(message=Message())
        callbacks.append(callback)
        return registry

    class Loop:
        def run(self):
            assert json.loads(path.read_text())["type"] == "ready"
            callbacks[0](message=Message())
            callbacks[0](message=Message(sender="anonymous"))

    monkeypatch.setitem(
        sys.modules, "gi.repository", SimpleNamespace(GLib=SimpleNamespace(MainLoop=Loop))
    )
    monkeypatch.setattr(events, "bus_connection", lambda: (bus, "unix:guest"))
    monkeypatch.setattr(events, "register", register)
    monkeypatch.setattr(events, "event_path", lambda: path)
    monkeypatch.setattr(events, "process_identity", lambda _: identity)
    monkeypatch.setattr(
        events, "source_identity", lambda *args: {**identity, "exe": "/lab/electron"}
    )
    events.collect()
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [line["type"] for line in lines] == ["ready", "source"]
    assert lines[0]["run"] == lines[1]["run"]
    assert lines[1]["observed_ns"] >= lines[0]["started_ns"]
    assert lines[1]["peer"] == ":1.42"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert teardown == [*events.EVENTS, "close"]
    with pytest.raises(FileExistsError):
        events.collect()
