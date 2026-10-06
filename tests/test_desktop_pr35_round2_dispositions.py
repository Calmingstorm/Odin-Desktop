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
