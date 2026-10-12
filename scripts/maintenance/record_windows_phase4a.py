#!/usr/bin/env python3
"""Record only phase-4a's named runtime boundaries, retaining prior lineage.

This is byte accounting, not approval or test execution. Unchanged entries only
receive a named evidence digest refresh when the workflow contract test changes.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import fresh_profile_parity
import inventory

CHANGES = {
    "src/desktop/browser_runtime.py": (
        "Resolve Windows Chromium only inside the sealed install-relative tree.",
        ["tests/test_windows_payload_consumers.py", "tests/test_desktop_browser_runtime.py"]),
    "src/desktop/platform/windows_helpers.py": (
        "Resolve bundled curl and its explicit TLS trust policy for real http_probe calls.",
        ["tests/test_windows_payload_consumers.py"]),
    "src/desktop/platform/windows_payloads.py": (
        "Centralize fail-closed install-relative Windows tools and explicit CA policy.",
        ["tests/test_windows_payload_consumers.py"]),
    "src/desktop/platform/windows_ssh.py": (
        "Resolve bundled OpenSSH client programs without packaged System32 fallback.",
        ["tests/test_windows_payload_consumers.py"]),
    "src/desktop/platform/windows_validate.py": (
        "Route HTTP validation through the same bundled curl and explicit trust policy.",
        ["tests/test_windows_payload_consumers.py"]),
    "tests/test_desktop_isolated_runner.py": (
        "Enforce identical pinned build tooling in both hosted Windows jobs.",
        ["tests/test_desktop_isolated_runner.py"]),
    "tests/test_windows_payload_consumers.py": (
        "Test packaged Windows browser and tool resolution and no-fallback refusals.",
        ["tests/test_windows_payload_consumers.py"]),
    "tests/test_windows_runtime_acceptance_harness.py": (
        "Test cold acceptance environment, resource immutability and hosted workflow wiring.",
        ["tests/test_windows_runtime_acceptance_harness.py"]),
    "scripts/packaging/windows-runtime-acceptance.py": (
        "Qualify installed runtime loads and real consumers outside the source checkout.",
        ["tests/test_windows_runtime_acceptance_harness.py"]),
}


def main():
    root = inventory.ROOT
    before = copy.deepcopy(inventory.ledger(root))
    old = {entry["path"]: entry for entry in before["entries"]}
    for path, (reason, tests) in CHANGES.items():
        prior = old.get(path, {})
        inventory.record(root, SimpleNamespace(
            path=path, reason=reason,
            contract="Windows 4a P1-P6: pinned packaged payloads and real consumer qualification.",
            invariant="Preserve Linux/source behavior; no ambient fallback or live changes.",
            owner="Odin", tests=sorted(set(tests) | set(prior.get("tests", [])))))
    data = inventory.ledger(root)
    byte_fields = {"before_sha256", "after_sha256", "patch", "tests", "test_sha256"}
    for entry in data["entries"]:
        path = entry["path"]
        if path in CHANGES and path in old:
            generated = copy.deepcopy(entry)
            # Every old lineage/accountability field survives. Only the measured
            # delta, evidence and explicit new pending review statement change.
            entry.update(old[path])
            for field in byte_fields:
                entry[field] = generated[field]
            for field in ("reason", "contract", "invariant"):
                note = " | Windows phase 4a: " + generated[field]
                if note not in entry[field]:
                    entry[field] += note
            entry.update(state="pending", reviewer="pending Claude",
                         approval="pending independent phase-4a review",
                         evidence="Exact bytes only; native/test execution is recorded separately")
        for test in entry["tests"]:
            if test in CHANGES:
                entry.setdefault("test_sha256", {})[test] = inventory.digest(
                    (root / test).read_bytes())
    inventory.write_json(root / "maintenance/desktop-deltas.json", data)
    proof_path = root / fresh_profile_parity.PROOF
    proof = inventory.load_json(proof_path)
    expected = set(fresh_profile_parity.source_paths(root))
    changed = {path for path in expected if proof["hashes"].get(path)
               != fresh_profile_parity.file_hash(root / path)}
    if not changed <= set(CHANGES):
        raise ValueError(f"Refusing unrelated parity recapture: {sorted(changed - set(CHANGES))}")
    if set(proof["hashes"]) - expected:
        raise ValueError("Refusing parity source removal")
    for path in changed:
        proof["hashes"][path] = fresh_profile_parity.file_hash(root / path)
    inventory.write_json(proof_path, proof)
    return inventory.main(["refresh"])


if __name__ == "__main__":
    raise SystemExit(main())
