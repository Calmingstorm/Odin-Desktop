"""Inherited resume assertions, with legacy fixture entry names retained verbatim."""
import ast
import copy
import json
from types import ModuleType

import pytest
import pytest_asyncio

from scripts.maintenance import phase2_suites as checker
from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from tests.desktop_adapters.step8_review_resume_exact import (
    CORPUS_EXCLUSIONS,
    MANIFEST,
    SOURCE_PATH,
    SOURCE_SHA256,
    adapt,
    load,
    owner_fixture,
)
from tests.desktop_adapters.step8_review_resume_exact import (
    register_module as register_discovery,
)


@pytest_asyncio.fixture(autouse=True)
async def authenticated_owner(tmp_path):
    async for state in owner_fixture(tmp_path):
        yield state


def test_exact_resume_complete_corpus_and_reverse_guard():
    original, tree, rules = adapt(frozen_source(SOURCE_PATH))
    assert corpus(original) == corpus(tree)
    assert len(corpus(original)["assertions"]) == 185
    assert len(corpus(original)["cases"]) == 58
    # No class deletion, rewritten assertion call, denial prose normalization,
    # assertion namespace rebasing, or predicate/operator/count change.
    before = [dump(n) for n in ast.walk(original) if isinstance(n, ast.Assert)]
    after = [dump(n) for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    assert before == after
    assert len(CORPUS_EXCLUSIONS["test_resume_admission"]) == 8
    groups = json.loads(MANIFEST.read_text())["hunks"]
    assert rules == [dict(r, line=line, column=column) for r in groups
                     for line, column in r["positions"]]


def test_exact_resume_rejects_source_manifest_replacement_drift(monkeypatch, tmp_path):
    source = frozen_source(SOURCE_PATH)
    with pytest.raises(ValueError, match="source bytes"):
        adapt(source + b"\n")
    with pytest.raises(ValueError, match="immutable hunk"):
        adapt(source, hunks=[])
    data = json.loads(MANIFEST.read_text())
    changed = copy.deepcopy(data)
    changed["hunks"][0]["after_source"] += "\nassert False"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(changed))
    monkeypatch.setattr("tests.desktop_adapters.step8_review_resume_exact.MANIFEST", path)
    # A second statement must not be silently accepted from a hunk.
    changed["hunks"][0]["after_sha256"] = "invalid"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="immutable hunk manifest hash"):
        adapt(source)


def test_exact_resume_retirements_match_source_pinned_dispositions():
    dispositions = CORPUS_EXCLUSIONS["test_resume_admission"]
    assert checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, dispositions)
    assert [row["case"] for row in dispositions] == sorted(
        checker.PR35_CASE_REASONS[SOURCE_PATH])


def test_exact_resume_discovery_clones_preserve_original_class_and_retained_methods():
    module = ModuleType("original_resume_discovery")

    class TestExplicitResume:
        def test_wrong_author_gets_notice(self):
            pass

        def test_retained(self):
            pass

    module.TestExplicitResume = TestExplicitResume
    namespace = {"__name__": __name__}
    register_discovery(namespace, module, prefix="cloned",
                    excluded=["TestExplicitResume.test_wrong_author_gets_notice"])
    exported = namespace["Test_cloned_TestExplicitResume"]
    assert exported is not TestExplicitResume
    assert hasattr(TestExplicitResume, "test_wrong_author_gets_notice")
    assert not hasattr(exported, "test_wrong_author_gets_notice")
    assert exported.test_retained is TestExplicitResume.test_retained


# Export every retained inherited case alongside these integrity guards.
load(globals())
