"""Complete frozen output suites, with case-level removed HTTP route accounting."""
import ast
import json

import pytest

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source
from tests.desktop_adapters.lane6_health_output import (
    CASE_MAP,
    CORPUS_EXCLUSIONS,
    EVIDENCE,
    PROPOSED_CASES,
    SUITES,
    admitted_message,
    load,
    owner_fixture,
)

load(globals())


@pytest.fixture(autouse=True)
def lane6_health_output_owner(tmp_path):
    with owner_fixture(tmp_path) as fixture:
        fixture.message = admitted_message(fixture)
        yield fixture


@pytest.mark.parametrize("suite", SUITES)
def test_lane6_health_output_exact_corpus_and_complete_accounting(suite):
    path = f"tests/{suite}.py"
    expected = corpus(ast.parse(frozen_source(path)))
    assert EVIDENCE[path]["exact_corpus"] == expected
    cases = {symbol for symbol, *_ in expected["cases"]}
    restored = {key.removeprefix(path + "::").replace("::", ".")
                for key in CASE_MAP if key.startswith(path + "::")}
    excluded = set(CORPUS_EXCLUSIONS.get(suite, []))
    assert restored.isdisjoint(excluded)
    proposed = set(PROPOSED_CASES.get(suite, {}))
    assert restored.isdisjoint(proposed)
    assert restored | excluded | proposed == cases
    report = json.loads((ROOT / "maintenance/lane6-health-output-report.json").read_text())
    row, = [entry for entry in report["suites"] if entry["path"] == path]
    assert set(row["restored_cases"]) == restored
    assert {case["case"] for case in row["retired"]} == excluded
    assert {case["case"] for case in row["proposed"]} == proposed
    assert row["source_sha256"] == SUITES[suite]
    assert row["corpus_sha256"] == EVIDENCE[path]["corpus_sha256"]
