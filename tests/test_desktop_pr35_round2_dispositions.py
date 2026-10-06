"""Round2 dispositions are exact source/case authority, not passing coverage."""
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.maintenance import phase2_suites as checker

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = "tests/characterization/test_executor_dispatch_parity.py"


def dispatch_dispositions():
    from tests.desktop_adapters.step8_review_dispatch import CORPUS_EXCLUSIONS
    return deepcopy(CORPUS_EXCLUSIONS["characterization/test_executor_dispatch_parity"])


def test_round2_dispatch_exact_dispositions_admitted_without_source_change():
    rows = dispatch_dispositions()
    assert len(rows) == 3
    assert sum(row["reviewer"] == checker.PR35_ROUND2_REVIEWER for row in rows) == 2
    assert checker._case_retirements(ROOT, DISPATCH,
                                     checker.PR35_CASE_SOURCE_SHA256[DISPATCH], rows)
    assert checker._full_adapter(ROOT, "tests/test_desktop_step8_review_dispatch.py",
                                  DISPATCH, checker.PR35_CASE_SOURCE_SHA256[DISPATCH], rows)


@pytest.mark.parametrize("field", ["case", "reviewer", "reason", "source_path", "source_sha256"])
@pytest.mark.parametrize("index", [0, 2])
def test_round2_dispatch_each_field_is_pinned(index, field):
    rows = dispatch_dispositions()
    rows[index][field] = "unreviewed"
    assert not checker._case_retirements(ROOT, DISPATCH,
                                         checker.PR35_CASE_SOURCE_SHA256[DISPATCH], rows)


def test_round2_does_not_extend_case_retirement_to_supported_dispatch():
    rows = dispatch_dispositions()
    rows[0]["case"] = "TestPatchSeam.test_handlers_are_resolved_late"
    rows.sort(key=lambda row: row["case"])
    assert not checker._case_retirements(ROOT, DISPATCH,
                                         checker.PR35_CASE_SOURCE_SHA256[DISPATCH], rows)


@pytest.mark.parametrize("source,selector,declaration", [
    ("tests/test_campaign_cli_coverage.py", "tests/test_desktop_step8_review_cli_exact.py",
     "tests/desktop_adapters/step8_review_cli_exact.py"),
    ("tests/test_chat_steering_parity.py", "tests/test_desktop_step8_review2_parity_exact.py",
     "tests/desktop_adapters/step8_review_parity_exact.py"),
])
def test_round2_complete_case_adapter_associations(source, selector, declaration):
    import ast

    tree = ast.parse((ROOT / declaration).read_bytes())
    exclusions = next(ast.literal_eval(node.value) for node in tree.body
                      if isinstance(node, ast.Assign) and any(
                          isinstance(target, ast.Name) and target.id == "CORPUS_EXCLUSIONS"
                          for target in node.targets))
    rows = exclusions[Path(source).stem]
    assert checker._full_adapter(ROOT, selector, source,
                                  checker.PR35_CASE_SOURCE_SHA256[source], rows)
    for row in rows:
        assert row["reviewer"] == checker.PR35_ROUND2_REVIEWER
    for field in ("case", "reviewer", "reason", "source_path", "source_sha256"):
        changed = deepcopy(rows)
        changed[0][field] = "unreviewed"
        assert not checker._case_retirements(ROOT, source,
                                             checker.PR35_CASE_SOURCE_SHA256[source], changed)


def codex_parameter_rows():
    from tests.desktop_adapters.step8_review_codex import PARAMETER_RETIREMENTS
    return deepcopy(PARAMETER_RETIREMENTS["test_codex_replay_matrix"])


def test_round2_codex_exact_parameter_rows_required_for_full_association():
    source = "tests/test_codex_replay_matrix.py"
    sha = checker.PR35_CASE_SOURCE_SHA256[source]
    rows = codex_parameter_rows()
    assert checker._parameter_retirements(ROOT, source, sha, rows)
    assert checker._full_adapter(ROOT, "tests/test_desktop_step8_review_codex.py", source,
                                  sha, parameter_retirements=rows)
    assert not checker._full_adapter(ROOT, "tests/test_desktop_step8_review_codex.py", source, sha)


@pytest.mark.parametrize("mutation", ["extra", "missing", "duplicate", "unsorted", "wildcard",
                                     "other_case", "other_source", "other_hash"])
def test_round2_codex_parameter_retirement_fail_closed(mutation):
    source = "tests/test_codex_replay_matrix.py"
    sha = checker.PR35_CASE_SOURCE_SHA256[source]
    rows = codex_parameter_rows()
    labels = rows["test_emitted_replayed_matrix"]
    if mutation == "extra":
        labels.append("builtin-read_file")
    elif mutation == "missing":
        labels.pop()
    elif mutation == "duplicate":
        labels.append(labels[0])
    elif mutation == "unsorted":
        labels.reverse()
    elif mutation == "wildcard":
        labels[:] = ["*"]
    elif mutation == "other_case":
        rows["test_supported"] = rows.pop("test_emitted_replayed_matrix")
    elif mutation == "other_source":
        source = DISPATCH
    else:
        sha = "0" * 64
    assert not checker._parameter_retirements(ROOT, source, sha, rows)


@pytest.mark.parametrize("mutation", ["remove", "dynamic", "wrong_authority", "annotation",
                                     "item_write", "clear", "alter_rows"])
def test_round2_codex_loader_metadata_cannot_mutate(monkeypatch, mutation):
    import ast

    source = "tests/test_codex_replay_matrix.py"
    selector = "tests/test_desktop_step8_review_codex.py"
    trees = deepcopy(checker._adapter_modules(ROOT, selector))
    declaration = next(tree for tree in trees if any(
        isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                                            and target.id == "PARAMETER_RETIREMENTS"
                                            for target in node.targets)
        for node in tree.body))
    assignment = next(node for node in declaration.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "PARAMETER_RETIREMENTS"
                              for target in node.targets))
    if mutation == "remove":
        declaration.body.remove(assignment)
    elif mutation == "dynamic":
        assignment.value = ast.parse("arbitrary_retirements()", mode="eval").body
    elif mutation == "wrong_authority":
        node = next(node for node in declaration.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "REVIEW_AUTHORITY"
                            for target in node.targets))
        node.value = ast.Constant("unreviewed")
    elif mutation == "alter_rows":
        assignment.value = ast.parse(repr({"test_codex_replay_matrix": {
            "test_emitted_replayed_matrix": ["builtin-read_file"]}}), mode="eval").body
    else:
        injected = {
            "annotation": "PARAMETER_RETIREMENTS: dict = {}",
            "item_write": "PARAMETER_RETIREMENTS['extra'] = {}",
            "clear": "PARAMETER_RETIREMENTS.clear()",
        }[mutation]
        declaration.body.extend(ast.parse(injected).body)
    monkeypatch.setattr(checker, "_adapter_modules", lambda _root, _selector: trees)
    assert not checker._full_adapter(ROOT, selector, source,
                                      checker.PR35_CASE_SOURCE_SHA256[source],
                                      parameter_retirements=codex_parameter_rows())
