"""Generate the integration report as an apply_patch envelope, no file writes."""
from __future__ import annotations

import json

from tests.desktop_adapters.lane6_providers_cases import (
    CASE_MAP,
    EVIDENCE,
    RETIRED_CASES,
    SUITE_NAMES,
    load,
)


def report():
    load({})
    suites, cases = [], []
    for stem in SUITE_NAMES:
        path = f"tests/{stem}.py"
        selectors = ["tests/test_desktop_lane6_providers.py"]
        suites.append({"path": path, "status": "restored", "blocked_on": None,
            "selector": "tests/test_desktop_lane6_providers.py", "selectors": selectors,
            "mode": "frozen-case-adapter"
            if path + "::test_codex_default_spawn_requires_model_selection" in RETIRED_CASES
            else "frozen-adapter",
            "adapter": "tests/desktop_adapters/lane6_providers_cases.py",
            "source_sha256": EVIDENCE[path]["source_sha256"],
            "corpus_sha256": EVIDENCE[path]["corpus_sha256"],
            "setup_edits": EVIDENCE[path]["setup_edits"]})
        cases.append({"suite": path, "status": "restored", "cases": [
            k.removeprefix(path + "::") for k in CASE_MAP if k.startswith(path + "::")],
            "selector_contract": "tests/test_desktop_lane6_providers.py::CASE_MAP[original]",
            "reason": (
                "Frozen exact corpus through real canonical algorithms/owners; external effects "
                "and provider responses stubbed."
            )})
    retired = [{"original": k, "status": "retired", **v} for k, v in RETIRED_CASES.items()]
    return {"version": 1, "batch": "lane6-providers", "suites": suites,
        "cases": cases + retired, "retired_cases": retired, "proposals": [], "substitutions": [],
        "lineage": [{"paths": [
            "tests/desktop_adapters/lane6_providers_cases.py",
            "tests/desktop_adapters/lane6_providers_owner.py",
            "tests/desktop_adapters/lane6_providers_engine.py",
            "tests/desktop_adapters/lane6_providers_timing.py",
            "tests/test_desktop_lane6_providers.py"],
            "contracts": [
                "Literal SUITES SHA256 pins plus fixture_corpus archive and retained source bytes "
                "validation.",
                "Full assertion/signature/decorator/parameter equality before case-level "
                "nonexport.",
                "ProviderOwner uses real SettingsService and CodexAccountsService with private "
                "profile "
                "and in-memory secret backend.",
                "Chat/loop dispatch enters authenticated OwnerAuthority, PermissionManager, "
                "durable "
                "RequestService worker, actual EngineServices runner.",
                "Generation submethod fixtures use actual EngineServices runner with neutral "
                "request "
                "data, not removed Discord transport.",
                "Budget/density/reasoning/accounting use actual canonical retained algorithms "
                "used by "
                "Desktop services."],
            "tests": [
                ".venv/bin/python scripts/run-phase1-tests.py "
                "tests/test_desktop_lane6_providers.py --tb=short"
            ]}],
        "production_fixes": [{
            "path": "src/desktop/providers.py",
            "status": "implemented",
            "reason": "Cancelled uncommitted candidate closed without retiring generation "
            "admission; "
            "frozen cancellation assertion exposed this gap."}],
        "test_results": {
            "final": "402 passed in 59.93s; 378 inherited restored parameterized cases + 23 "
            "existing ProviderOwner tests + 1 actual rollback admission regression.",
            "command": (
                ".venv/bin/python scripts/run-phase1-tests.py "
                "tests/test_desktop_lane6_providers.py tests/test_desktop_providers.py --tb=short"
            )}}


if __name__ == "__main__":
    data = report()
    text = "{\n" + ",\n".join(
        json.dumps(key) + ": " + json.dumps(value, separators=(",", ":"))
        for key, value in data.items()) + "\n}\n"
    print("*** Begin Patch\n*** Add File: maintenance/lane6-providers-report.json")
    print("\n".join("+" + line for line in text.splitlines()))
    print("*** End Patch")
