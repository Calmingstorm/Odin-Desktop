"""The frozen wrapper suite under Odin 4.19.2: one reviewed retirement, the rest unchanged."""
from scripts.maintenance import phase2_suites as checker
from scripts.maintenance.fixture_corpus import corpus
from tests.desktop_adapters.odin_4192_wrapper_r10 import (
    CORPUS_EXCLUSIONS,
    SOURCE_PATH,
    SOURCE_SHA256,
    load,
    source_tree,
)

RETIRED = "test_started_shell_cleanup_failure_preserves_launch_error"


def test_the_retirement_is_the_reviewed_source_pinned_one():
    dispositions = CORPUS_EXCLUSIONS["test_local_supervisor_wrapper_r10"]
    assert checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, dispositions)
    assert [row["case"] for row in dispositions] == [RETIRED]
    widened = [dict(dispositions[0], case="test_private_session_required")]
    assert not checker._case_retirements(checker.ROOT, SOURCE_PATH, SOURCE_SHA256, widened)


def test_every_other_frozen_case_is_exported_unchanged():
    namespace = {"__name__": "odin_4192_wrapper_probe"}
    load(namespace)
    cases = sorted(case for case, _, _ in corpus(source_tree())["cases"])
    exported = sorted(key for key in namespace if key.startswith("test_"))
    assert type(namespace["isolated"]).__name__ == "FixtureFunctionDefinition"
    assert len(cases) == 10 and RETIRED in cases
    assert exported == sorted(f"test_test_local_supervisor_wrapper_r10_{case[5:]}"
                              for case in cases if case != RETIRED)


load(globals())
