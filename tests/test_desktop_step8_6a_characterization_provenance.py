"""Machine-consumed frozen characterization provenance, not document checks."""
import ast
import hashlib
import json
from pathlib import Path

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters.step8_6a_characterization import (
    CORPUS_EXCLUSIONS,
    CORPUS_SELECTIONS,
    SUITES,
    SUPPORT_CASES,
    SUPPORT_SUITE,
    adapted_tree,
)


@pytest.mark.parametrize("name", sorted(SUPPORT_SUITE))
def test_step8_characterization_exact_corpus(name):
    original, adapted = adapted_tree(name)
    assert corpus(original) == corpus(adapted)
    available = {symbol for symbol, *_ in corpus(original)["cases"]}
    assert SUPPORT_CASES[name] <= available
    exclusions = CORPUS_EXCLUSIONS.get(name, [])
    assert [row["case"] for row in exclusions] == sorted(row["case"] for row in exclusions)
    assert all(row["case"] in available for row in exclusions)
    assert not (SUPPORT_CASES[name] & {row["case"] for row in exclusions})
    assert all(row["reviewer"] == "Claude, review of step 8 part 4" for row in exclusions)


def test_step8_characterization_candidates_cover_exact_functions():
    root = Path(__file__).resolve().parents[1]
    candidates = json.loads((root / "maintenance/step8-part4-characterization-candidates.json")
                            .read_text())
    assert CORPUS_SELECTIONS == SUITES == {}
    for row in candidates["dispositions"]:
        source = frozen_source(row["path"])
        assert hashlib.sha256(source).hexdigest() == row["inherited_sha256"]
        available = {symbol for symbol, *_ in corpus(ast.parse(source))["cases"]}
        name = Path(row["path"]).stem
        support = SUPPORT_CASES.get(name, set())
        assert row["restoration"] is None
        categories = [support, *(set(item["case"] for item in row.get(key, []))
                                 for key in ("retired_cases", "deferred_cases", "proposed_cases"))]
        assert set().union(*categories) == available
        assert sum(map(len, categories)) == len(available)
        for key in ("retired_cases",):
            records = row.get(key, [])
            assert records == sorted(records, key=lambda item: item["case"])
            for record in records:
                assert record["source_path"] == row["path"]
                assert record["source_sha256"] == row["inherited_sha256"]
                assert record["reviewer"] == "Claude, review of step 8 part 4"
