"""Fresh runtime extraction plus strict omission and stale-hash verification."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from scripts.maintenance import fresh_profile_parity as parity

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def observed():
    return parity.collect(ROOT)


def test_fresh_runtime_observations_match_committed_proof(observed):
    proof = json.loads((ROOT / parity.PROOF).read_text())
    assert proof["observations"] == {"baseline_sha256": parity.digest(observed["baseline"]),
                                    "desktop_sha256": parity.digest(observed["desktop"])}
    assert parity.digest(observed["baseline"]) == parity.BASELINE_OBSERVATION_SHA256
    assert parity.digest(observed["desktop"]) == parity.DESKTOP_OBSERVATION_SHA256
    assert parity.expand_deltas(proof["deltas"]) == parity.differences(**observed)
    assert parity.digest(parity.expand_deltas(proof["deltas"])) == parity.DELTA_SHA256


def test_actual_local_default_and_owner_access(observed):
    for side in observed.values():
        assert side["settings.tools.default_host"] == "localhost"
        assert side["settings.tools.hosts.localhost.address"] == "127.0.0.1"
        assert side["settings.tools.hosts.localhost.ssh_user"] == "root"
        assert side["access.owner_hosts"] == ["localhost"]
        assert side["access.owner_tool_names"] is None
        assert side["access.preference_default"] == ""
        for name in ("omitted_host", "explicit_host", "http_probe_local_fallback"):
            assert side["runtime." + name] == {
                "address": "127.0.0.1", "ssh_user": "root", "target": None}
    assert observed["desktop"]["access.unauthenticated_hosts"] == []
    assert observed["baseline"]["settings.permissions.default_tier"] == "admin"
    for side in observed.values():
        assert side["settings.browser.enabled"] is True
        assert side["settings.browser.allow_private_targets"] == ["http://127.0.0.1:3000", "http://localhost:3000"]
        assert side["settings.tools.skill_allowed_urls"] == ["http://localhost:8188"]


def test_extraction_data_covers_every_difference(observed, tmp_path):
    result = dict(schema_version=1, baseline_sha256=parity.ARCHIVE_SHA256,
                  hashes={path: parity.file_hash(ROOT / path)
                          for path in parity.source_paths(ROOT)},
                  **observed, deltas=parity.differences(**observed))
    (tmp_path / "observations.json").write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    assert result["deltas"]
    # 38 reviewed deltas plus step 7's four D10 webhook ingress settings.
    assert len(result["deltas"]) == 42
    assert all(row["approval"]["status"] == "approved" for row in result["deltas"])
    old_deltas = parity.expand_deltas(json.loads((ROOT / parity.PROOF).read_text())["deltas"])
    socket_key = "settings.tools.ssh_pool.socket_dir"
    assert [row for row in old_deltas if row["path"] != socket_key] == [
        row for row in result["deltas"] if row["path"] != socket_key]
    assert next(row for row in result["deltas"] if row["path"] == socket_key) == {
        "path": socket_key, "baseline": "/tmp/odin_ssh_sockets",
        "desktop": "$PROFILE_RUNTIME/default/ssh", "approval": parity.approval_for(socket_key)}
    print(json.dumps({"executed_collect": True,
                      "baseline_sha256": parity.digest(observed["baseline"]),
                      "desktop_sha256": parity.digest(observed["desktop"]),
                      "delta_sha256": parity.digest(result["deltas"]),
                      "delta_count": len(result["deltas"]),
                      "socket_dir": observed["desktop"]["settings.tools.ssh_pool.socket_dir"]},
                     sort_keys=True))


@pytest.mark.parametrize("uid", [1003, 4242])
@pytest.mark.parametrize("runtime_dir", [None, "/run/user/4242", "/tmp/rt-fixture"])
def test_socket_normalization_is_uid_and_runtime_root_independent(uid, runtime_dir):
    fallback = f"/tmp/odin-desktop-{uid}/default/ssh"
    assert parity.normalize_socket_directory(
        fallback, profile_id="default", uid=uid, runtime_dir=runtime_dir,
    ) == "$PROFILE_RUNTIME/default/ssh"
    if runtime_dir:
        assert parity.normalize_socket_directory(
            f"{runtime_dir}/odin-desktop/default/ssh", profile_id="default", uid=uid,
            runtime_dir=runtime_dir,
        ) == "$PROFILE_RUNTIME/default/ssh"


@pytest.mark.parametrize("value", [
    "/tmp/odin-desktop-4242/default/ssh",  # Wrong UID.
    "/tmp/odin-desktop-1003/other/ssh",  # Wrong profile.
    "/tmp/odin-desktop-1003/default/ssh/extra",  # Not the exact default.
    "/unselected/odin-desktop/default/ssh",  # Unselected XDG root.
    "/tmp/odin-desktop-1003/default/../default/ssh",  # Custom spelling.
    "/home/fresh/.cache/odin-desktop/default/ssh-sockets",  # Former D5 default.
    "custom/ssh", "/tmp/odin_ssh_sockets",
])
def test_socket_normalization_preserves_nondefault_observations(value):
    assert parity.normalize_socket_directory(
        value, profile_id="default", uid=1003, runtime_dir="/tmp/rt-fixture",
    ) == value


def test_fresh_collect_matches_with_verified_xdg_runtime_and_fallback(observed, monkeypatch):
    # A short private runtime root qualifies for the real selector. tmp_path can
    # be long enough to force fallback and would not exercise XDG selection.
    from src.desktop.paths import ProfilePaths
    from src.desktop.ssh_sockets import socket_directory

    key = "settings.tools.ssh_pool.socket_dir"
    assert observed["desktop"][key] == "$PROFILE_RUNTIME/default/ssh"
    with tempfile.TemporaryDirectory(prefix="rt-") as runtime_dir:
        monkeypatch.setenv("XDG_RUNTIME_DIR", runtime_dir)
        paths = ProfilePaths.from_xdg(home=Path(runtime_dir) / "home", environ={})
        assert socket_directory(paths) == f"{runtime_dir}/odin-desktop/default/ssh"
        xdg_observed = parity.collect(ROOT)
        monkeypatch.delenv("XDG_RUNTIME_DIR")
        assert socket_directory(paths) == f"/tmp/odin-desktop-{os.geteuid()}/default/ssh"
        fallback_observed = parity.collect(ROOT)
    assert xdg_observed == fallback_observed == observed


@pytest.fixture
def proof_root(tmp_path):
    (tmp_path / "maintenance").mkdir()
    return tmp_path


def check_fixture(monkeypatch, root, proof):
    monkeypatch.setattr(parity, "source_paths", lambda root: ["source.py"])
    monkeypatch.setattr(parity, "file_hash", lambda path: parity.ARCHIVE_SHA256
                        if path.name.endswith(".tar.gz") else "source-hash")
    monkeypatch.setattr(parity, "BASELINE_OBSERVATION_SHA256", "baseline-hash")
    monkeypatch.setattr(parity, "DESKTOP_OBSERVATION_SHA256", "desktop-hash")
    monkeypatch.setattr(parity, "DELTA_SHA256", parity.digest([]))
    (root / parity.PROOF).write_text(json.dumps(proof))
    return parity.check(root)


def fixture_proof():
    return {"schema_version": 1, "baseline_sha256": parity.ARCHIVE_SHA256,
            "hashes": {"source.py": "source-hash"},
            "observations": {"baseline_sha256": "baseline-hash", "desktop_sha256": "desktop-hash"},
            "deltas": []}


def test_static_checker_accepts_exact_equal_fixture(monkeypatch, proof_root):
    assert check_fixture(monkeypatch, proof_root, fixture_proof())["valid"]


@pytest.mark.parametrize("mutation", ["baseline-omission", "desktop-omission", "stale",
                                         "missing-hash", "self-claim", "missing-delta", "unknown"])
def test_static_checker_rejects_bad_data(monkeypatch, proof_root, mutation):
    proof = fixture_proof()
    if mutation == "baseline-omission":
        proof["observations"].pop("baseline_sha256")
    elif mutation == "desktop-omission":
        proof["observations"].pop("desktop_sha256")
    elif mutation == "stale":
        proof["hashes"]["source.py"] = "old"
    elif mutation == "missing-hash":
        proof["hashes"] = {}
    elif mutation == "self-claim":
        proof["passed"] = True
    else:
        proof["deltas"] = parity.differences(
            {"settings.timezone": "UTC"}, {"settings.timezone": "changed"})
        if mutation == "unknown":
            proof["deltas"][0]["approval"]["status"] = "approved"
    assert not check_fixture(monkeypatch, proof_root, proof)["valid"]
