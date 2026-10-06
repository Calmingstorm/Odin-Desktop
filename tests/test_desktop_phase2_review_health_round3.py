"""Round3 case-level retirement, exact knowledge diagnostics and provenance."""
import ast
import copy
import hashlib
import json

import pytest

from scripts.maintenance import phase2_suites as checker
from scripts.maintenance import record_step8_part2_review as recorder
from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from tests.desktop_adapters.step8_review_health_round3 import (
    CORPUS_EXCLUSIONS,
    CORPUS_SELECTIONS,
    SUITES,
    adapted_tree,
    load,
    records,
    source_tree,
    verify_adaptation,
    verify_dispositions,
)


def test_all_health_cases_accounted_without_manufactured_parity():
    assert verify_dispositions()
    rows = {row["path"]: row for row in records()["entries"]}
    endpoints = rows["tests/test_health_endpoints.py"]
    assert len(endpoints["case_retirements"]) == 22
    assert sum(row["reason"] == "multi-user tiers removed"
               for row in endpoints["case_retirements"]) == 4
    assert "restoration" not in endpoints
    startup = rows["tests/test_campaign_startup_health.py"]
    assert startup["restoration"]["inherited_cases"] == 2
    assert len(startup["restoration"]["case_retirements"]) == 1
    assert startup["case_counts"] == {"restored": 2, "retired": 2, "deferred": 0}


def test_intact_startup_corpus_only_loses_obsolete_imports():
    name = "test_campaign_startup_health"
    original = source_tree(name)
    adapted = adapted_tree(name)
    assert verify_adaptation(name, adapted)
    assert corpus(original) == corpus(adapted)
    assert len(corpus(original)["cases"]) == 3
    assert len(corpus(original)["assertions"]) == 8
    assert CORPUS_SELECTIONS[name] is None
    assert hashlib.sha256(frozen_source(f"tests/{name}.py")).hexdigest() == SUITES[name]
    for node in original.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert any(dump(node) == dump(candidate) for candidate in adapted.body)


@pytest.mark.parametrize("mutation", ("assertion", "signature", "parameter", "case", "setup"))
def test_frozen_startup_guard_rejects_tampering(mutation):
    tree = copy.deepcopy(adapted_tree("test_campaign_startup_health"))
    if mutation == "assertion":
        target = next(node for node in ast.walk(tree) if isinstance(node, ast.Assert))
        target.test = ast.Constant(True)
    elif mutation == "signature":
        next(node for node in tree.body if isinstance(node, ast.FunctionDef)).args.args.clear()
    elif mutation == "parameter":
        node = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef))
        node.decorator_list.pop()
    elif mutation == "case":
        tree.body = [node for node in tree.body if not isinstance(node, ast.AsyncFunctionDef)]
    else:
        tree.body.append(ast.parse("unreviewed_setup = True").body[0])
    with pytest.raises(ValueError, match="undeclared source change"):
        verify_adaptation("test_campaign_startup_health", tree)


def test_pytest_export_excludes_whole_removed_definition_not_its_assertions():
    namespace = {"__name__": "health_round3_export_probe"}
    load(namespace)
    exported = sorted(name for name in namespace if name.startswith("test_"))
    assert exported == [
        "test_test_campaign_startup_health_knowledge_diagnostic_accepts_first_run_and_valid_schema",
        "test_test_campaign_startup_health_knowledge_diagnostic_rejects_corrupt_existing_database",
    ]
    assert CORPUS_EXCLUSIONS["test_campaign_startup_health"][0]["case"] not in namespace


@pytest.mark.parametrize("field,value", (
    ("reviewer", "unapproved reviewer"), ("reason", "different reason"),
    ("source_sha256", "0" * 64),
    ("case", "test_knowledge_diagnostic_accepts_first_run_and_valid_schema"),
))
def test_case_authority_rejects_widening(monkeypatch, field, value):
    modified = copy.deepcopy(records())
    startup = next(row for row in modified["entries"]
                   if row["path"] == "tests/test_campaign_startup_health.py")
    startup["restoration"]["case_retirements"][0][field] = value
    monkeypatch.setattr("tests.desktop_adapters.step8_review_health_round3.records",
                        lambda: modified)
    with pytest.raises(ValueError, match="authority changed"):
        verify_dispositions()


def test_step5_completion_settled_the_suites_this_review_held():
    # The three mixed suites waited on step 5 completion (#40), which has merged.
    rows = {row["path"]: row for row in
            json.loads((checker.ROOT / checker.MAP_PATH).read_text())["entries"]}
    assert rows["tests/test_log_search.py"]["status"] == "restored"
    for path in ("tests/test_image_model_config_api.py", "tests/test_web_api_llm_admin.py"):
        assert rows[path]["status"] == "deferred" and rows[path]["step"] == 5
        assert rows[path]["blocked_on"] not in (None, "", "awaiting the step 5 completion PR")
    with pytest.raises(ValueError, match="must remain deferred"):
        recorder.build()


@pytest.mark.parametrize("mutation", ("none", "missing", "unreviewed_case", "dynamic"))
def test_offline_association_requires_exact_declared_exclusions(monkeypatch, mutation):
    path = "tests/test_campaign_startup_health.py"
    selector = "tests/test_desktop_phase2_review_health_round3.py"
    retired = CORPUS_EXCLUSIONS["test_campaign_startup_health"]
    trees = copy.deepcopy(checker._adapter_modules(checker.ROOT, selector))
    for tree in trees:
        for node in tree.body:
            if (isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "CORPUS_EXCLUSIONS"
                    for target in node.targets)):
                if mutation == "missing":
                    node.value = ast.Dict(keys=[], values=[])
                elif mutation == "unreviewed_case":
                    value = copy.deepcopy(ast.literal_eval(node.value))
                    value["test_campaign_startup_health"][0]["case"] = (
                        "test_knowledge_diagnostic_accepts_first_run_and_valid_schema")
                    node.value = ast.parse(repr(value), mode="eval").body
                elif mutation == "dynamic":
                    node.value = ast.parse("runtime_exclusions()", mode="eval").body
    monkeypatch.setattr(checker, "_adapter_modules", lambda root, target: trees)
    assert checker._full_adapter(
        checker.ROOT, selector, path, SUITES["test_campaign_startup_health"], retired
    ) is (mutation == "none")


load(globals())
