"""The frozen native knowledge suite under Odin 4.20.0: three reviewed retirements, the rest
unchanged."""
import json

from scripts.maintenance import phase2_suites as checker
from scripts.maintenance.fixture_corpus import corpus
from tests.desktop_adapters.odin_4200_native_knowledge import (
    CORPUS_EXCLUSIONS,
    SOURCE_PATH,
    SOURCE_SHA256,
    load,
    source_tree,
)

RETIRED = [
    "TestSearchAudit.test_formats_entries",
    "TestSearchAudit.test_renders_agent_attribution_and_tool_input",
    "TestSearchAudit.test_renders_audit_metadata",
]


def test_the_retirements_are_the_reviewed_source_pinned_ones():
    dispositions = CORPUS_EXCLUSIONS["test_native_knowledge"]
    assert checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, dispositions)
    assert [row["case"] for row in dispositions] == RETIRED
    for kept in ("TestSearchAudit.test_no_results", "TestListDelete.test_delete_paths"):
        widened = [*dispositions, dict(dispositions[0], case=kept)]
        assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, widened)
    wrong_authority = [dict(row, reviewer=checker.ODIN_4192_REVIEWER) for row in dispositions]
    assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256,
                                         wrong_authority)
    for field in ("reason", "source_sha256"):
        changed = [dict(dispositions[0], **{field: "changed"}), *dispositions[1:]]
        assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, changed)
    missing = [{k: v for k, v in dispositions[0].items() if k != "reason"}, *dispositions[1:]]
    assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, missing)
    assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256,
                                         list(reversed(dispositions)))


def test_a_case_without_reviewed_authority_is_refused_even_with_a_null_reason():
    approved = CORPUS_EXCLUSIONS["test_native_knowledge"][0]
    row = json.loads(json.dumps(dict(approved, case="TestSearchAudit.test_no_results",
                                     reason=None)))
    assert row["reason"] is None
    assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, [row])
    assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256,
                                         [approved, row])
    assert checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, [approved])


def test_the_earlier_authorities_still_refuse_these_cases():
    # Neither the PR35 nor the Odin 4.19.2 authority can bless a 4.20.0 retirement.
    approved = CORPUS_EXCLUSIONS["test_native_knowledge"]
    assert SOURCE_PATH not in checker.ODIN_4192_CASE_SOURCE_SHA256
    assert SOURCE_PATH not in checker.PR35_CASE_SOURCE_SHA256
    assert not checker._odin_4192_case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256,
                                                   approved)


def test_every_other_frozen_case_is_exported_unchanged():
    namespace = {"__name__": "odin_4200_native_knowledge_probe"}
    load(namespace)
    cases = sorted(case for case, _, _ in corpus(source_tree())["cases"])
    assert len(cases) == 26 and set(RETIRED) <= set(cases)
    exported = sorted(
        f"{cls}.{name}" for cls, value in namespace.items()
        if cls.startswith("Test") and isinstance(value, type)
        for name in vars(value) if name.startswith("test_"))
    expected = sorted(f"Test_test_native_knowledge_{case[4:].split('.')[0]}."
                      f"{case.split('.')[1]}" for case in cases if case not in RETIRED)
    assert exported == expected
    assert not any(key.startswith("test_") for key in namespace)


load(globals())
