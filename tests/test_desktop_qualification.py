"""Static qualification records, never inherited source imports."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(config, items):
    """Opt-in collection plugin: record actual aliases, never guess exports.

    Load with ``-p tests.test_desktop_qualification --collect-only`` behind the
    sanitized PID runner. Frozen code filenames and code qualnames, not renamed
    Python attributes, identify original definitions. Parameter IDs come from
    collected node IDs unchanged.
    """
    if not config.getoption("collectonly"):
        return
    rows = []
    for item in items:
        obj = getattr(item, "obj", None)
        code = getattr(obj, "__code__", None)
        if code is None:
            continue
        path = Path(code.co_filename)
        if path.is_absolute():
            try:
                path = path.relative_to(ROOT)
            except ValueError:
                continue
        if not str(path).startswith("tests/"):
            continue
        name = code.co_qualname.replace(".", "::")
        param = item.nodeid[item.nodeid.find("["):] if "[" in item.nodeid else ""
        rows.append({"original": f"{path}::{name}{param}",
                     "executable": item.nodeid})
    target = ROOT / ".test-state/qualification-collected.json"
    target.write_text(json.dumps({"schema_version": 1, "cases": rows}, indent=2) + "\n")


def historical_node(case):
    """Convert JUnit class names without losing exact parameter identities."""
    parts = case.attrib["classname"].split(".")
    module_end = next(i for i, part in enumerate(parts) if part.startswith("test_")) + 1
    path = "/".join(parts[:module_end]) + ".py"
    return "::".join([path, *parts[module_end:], case.attrib["name"]])


def test_historical_node_preserves_parameter_rows():
    case = ET.Element("testcase", classname="tests.test_example.TestMatrix",
                      name="test_value[a-b-0]")
    assert historical_node(case) == "tests/test_example.py::TestMatrix::test_value[a-b-0]"


def test_original_inventory_and_failed_evidence_stay_honest():
    baseline = json.loads((ROOT / "maintenance/test-plan.json").read_text())
    plan = json.loads((ROOT / "maintenance/qualification-plan.json").read_text())
    assert len(baseline["entries"]) == 869
    assert len({entry["path"] for entry in baseline["entries"]}) == 869
    for entry in baseline["entries"]:
        if entry["classification"] != "excluded":
            digest = hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest()
            assert digest == entry["sha256"]
    assert [(run["failed"], run["passed"], run["complete"])
            for run in plan["observed_failures"]] == [
                (116, 5824, False), (259, 10169, True)]
    assert plan["status"] == "not-accepted"
    assert plan["acceptance"]["unmapped_cases_are_blockers_not_implicit_passes"]


def test_executable_groups_preserve_native_safety_gate():
    baseline = json.loads((ROOT / "maintenance/test-plan.json").read_text())
    plan = json.loads((ROOT / "maintenance/qualification-plan.json").read_text())
    assert len({group["name"] for group in plan["groups"]}) == len(plan["groups"])
    for group in plan["groups"]:
        assert group["files"] and group["reason"]
        for selector in group["files"]:
            path = selector.split("::", 1)[0]
            assert (ROOT / path).is_file()
            assert path not in baseline["safety_manual_gated"]
        assert "not " not in group.get("exclude_expression", "")
    assert "never" in plan["acceptance"]["native_scope"].lower()
    assert "even mocked" in plan["acceptance"]["prohibited_literal_scope"]


def test_38_foundation_labels_have_disjoint_reviewed_dispositions():
    baseline = json.loads((ROOT / "maintenance/test-plan.json").read_text())
    plan = json.loads((ROOT / "maintenance/qualification-plan.json").read_text())
    paths = [path for group in plan["foundation_dispositions"].values() for path in group]
    assert len(paths) == len(set(paths)) == 38
    assert set(paths) == set(baseline["retained_adaptation_gated"])
    assert plan["failure_accounting"]["unmapped_failure"].startswith("Phase1-blocker")


def test_exact_failure_population_has_no_implicit_waivers():
    accounting = json.loads((ROOT / "maintenance/case-accounting.json").read_text())
    rows = accounting["historical_failures"]
    assert len(rows) == len({row["original"] for row in rows}) == 259
    assert all(row["reason"] and row["source_sha256"] for row in rows)
    allowed = {"executable", "removed-surface-replacement", "phase2-admission-wiring",
               "native-prohibited-scope", "unmapped-neutral-blocker"}
    assert all(row["disposition"] in allowed for row in rows)
    for row in rows:
        if row["disposition"] == "executable":
            assert row["executable"] and row["collection_evidence"]
        if row["disposition"] == "removed-surface-replacement":
            assert row["replacement_cases"] and row["triage_source"]
        if row["disposition"] == "unmapped-neutral-blocker":
            assert row["blocks_phase1"]
    blockers = [row["original"] for row in rows if row["blocks_phase1"]]
    assert accounting["historical_failure_blockers"] == blockers
    assert accounting["status"] == "pending-review-not-accepted"


def test_exact_replacement_parameter_group_does_not_rewrite_original_rows():
    accounting = json.loads((ROOT / "maintenance/case-accounting.json").read_text())
    rows = accounting["historical_failures"]
    binding = [row for row in rows if "::test_recovery_operator_binding[" in row["original"]]
    assert {row["original"].split("[", 1)[1] for row in binding} == {
        "ctx0-operator_surface_required]", "ctx1-not_found]"}
    assert all(row["disposition"] == "removed-surface-replacement" for row in binding)
    assert all(row["replacement_cases"] for row in binding)


def test_accounted_executable_and_replacements_are_actually_collected():
    accounting = json.loads((ROOT / "maintenance/case-accounting.json").read_text())
    collected = {row["executable"] for row in accounting["collection_cases"]}
    rows = [*accounting["historical_failures"],
            *(row for suite in accounting["foundation_suites"] for row in suite["cases"])]
    for row in rows:
        if row["disposition"] == "executable":
            assert row["executable"] and set(row["executable"]) <= collected
        elif row["disposition"] == "removed-surface-replacement":
            assert row["replacement_cases"] and set(row["replacement_cases"]) <= collected
        elif row["disposition"] in {"phase2-admission-wiring", "native-prohibited-scope"}:
            assert row["triage_source"] and row["reason"]
            assert row["blocks_phase1"], "Deferred scope is not implemented parity"
        else:
            assert row["blocks_phase1"], "Unsupported disposition cannot silently clear a gap"


def test_foundation_accounting_covers_every_original_definition():
    import ast

    accounting = json.loads((ROOT / "maintenance/case-accounting.json").read_text())
    baseline = json.loads((ROOT / "maintenance/test-plan.json").read_text())
    suites = accounting["foundation_suites"]
    assert {row["path"] for row in suites} == set(baseline["retained_adaptation_gated"])
    assert len(suites) == 38
    for suite in suites:
        tree = ast.parse((ROOT / suite["path"]).read_text())
        originals = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    originals.add(suite["path"] + "::" + node.name)
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                originals.update(suite["path"] + "::" + node.name + "::" + method.name
                                 for method in node.body
                                 if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                                 and method.name.startswith("test_"))
        assert {row["original"] for row in suite["cases"]} == originals
        assert all(row["reason"] for row in suite["cases"])
        assert all(row["blocks_phase1"] for row in suite["cases"]
                   if row["disposition"] == "unmapped-neutral-blocker")
