"""Offline accounting tests and named pure loader metadata in the PID runner."""
# ruff: noqa: E501
import pytest

from scripts.maintenance import lane6_case_manifest as manifest


def test_exact_population_and_disjoint_partition():
    report = manifest.build_report(extra_roots=[manifest.ROOT.parent / "agents"])
    assert report["assignment"]["count"] == 62
    counts = report["source_case_definitions"]
    assert counts["total"] == sum(counts[status] for status in manifest.STATUSES)
    for row in report["entries"]:
        assert sum(row["counts"].values()) == len(row["cases"])
        assert len({case["original"] for case in row["cases"]}) == len(row["cases"])
    assert report["parameter_expanded_collected"] is None


def test_normalizer_rejects_counts_and_prose():
    path = "tests/test_output_streamer.py"
    claims, _ = manifest.normalize_report({"path": path, "restored": 102,
        "retired_cases": [{"case": "TestAPIEndpoint.test_no_executor", "reason": "removed"}],
        "proposals": "Exact cases in another report, not a declaration"})
    assert len(claims) == 1
    assert claims[0][0] == path + "::TestAPIEndpoint.test_no_executor"
    assert manifest.identity("fictional prose", path) is None


def test_retirement_override_requires_exact_ast():
    key = "tests/test_mixed_agent_reasoning_contract.py::test_codex_default_spawn_requires_model_selection"
    report = manifest.build_report()
    case = next(case for row in report["entries"] for case in row["cases"] if case["original"] == key)
    assert case["status"] == "proposed"
    decision = {"status": "retired", "reason": "Explicit test decision only",
                "reviewer": "Claude, review of step 8 part 4", "surface": "Discord",
                "source_sha256": case["case_ast_sha256"]}
    report = manifest.build_report(overrides={key: decision})
    assert not any(key in error and "Unbound retirement" in error for error in report["errors"])
    decision["source_sha256"] = "0" * 64
    report = manifest.build_report(overrides={key: decision})
    assert any(key in error and "Unbound retirement" in error for error in report["errors"])


def test_named_loader_snapshot():
    snapshot = manifest.snapshot_loaders(["tests.desktop_adapters.lane6_health_core"])
    assert snapshot["claims"] and snapshot["exports"]
    report = manifest.build_report(snapshot=snapshot)
    assert not any("Stale loader snapshot" in error for error in report["errors"])


def test_unknown_override_fails_closed():
    with pytest.raises(ValueError, match="Unknown override"):
        manifest.build_report(overrides={"tests/test_missing.py::test_fake": {"status": "restored"}})
