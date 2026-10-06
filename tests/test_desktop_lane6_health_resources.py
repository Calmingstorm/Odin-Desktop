"""Whole frozen lane6 resource/LLM-window/ranked-capture qualification."""
import ast
import hashlib
import json

import pytest

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters.lane6_health_resources import (
    CORPUS_EXCLUSIONS,
    CORPUS_SELECTIONS,
    ROOT,
    SUITES,
    disposition,
    load,
    owner_fixture,
)


@pytest.fixture(autouse=True)
def _temporary_owner(tmp_path_factory):
    # The observer's atomicity assertion exhaustively enumerates its own
    # tmp_path. Authority scaffolding belongs in a separate temporary root.
    with owner_fixture(tmp_path_factory.mktemp("lane6-health-owner")):
        yield


load(globals())


def test_lane6_health_resources_whole_suite_admission():
    assert CORPUS_SELECTIONS == {
        "test_resource_usage": None,
        "test_window_observer": None,
        "test_search_output_capture": None,
    }
    assert set(SUITES) == set(CORPUS_SELECTIONS)
    assert CORPUS_EXCLUSIONS == {}


def test_lane6_health_resources_exact_case_disposition_report():
    report = json.loads((ROOT / "maintenance/lane6-health-resources-report.json").read_text())
    counts = {status: 0 for status in ("restored", "retired", "deferred", "proposed")}
    for suite, digest in SUITES.items():
        path = f"tests/{suite}.py"
        source = frozen_source(path)
        original = corpus(ast.parse(source))
        recorded = report["suites"][path]
        assert hashlib.sha256(source).hexdigest() == digest == recorded["source_sha256"]
        if "corpus_sha256" in recorded:
            assert recorded["corpus_sha256"] == hashlib.sha256(
                json.dumps(original, sort_keys=True).encode()
            ).hexdigest()
        expected = {status: [] for status in counts}
        for symbol, _args, _decorators in original["cases"]:
            status, _reason = disposition(suite, symbol)
            cases = [symbol]
            if (suite == "test_search_output_capture" and symbol ==
                    "test_ranked_snapshot_preserves_original_order_and_oversized_match"):
                cases = [f"{symbol}[{kind}]" for kind in ("history", "knowledge", "background")]
            expected[status].extend(cases)
        assert expected == recorded["case_dispositions"]
        assert recorded["case_function_count"] == len(original["cases"])
        assert recorded["parameter_expanded_count"] == sum(map(len, expected.values()))
        for status, cases in expected.items():
            counts[status] += len(cases)
            for case in cases:
                symbol = case.split("[", 1)[0]
                if "." in symbol:
                    parent, name = symbol.rsplit(".", 1)
                    exported = globals().get(f"TestResources_{suite[5:]}_{parent[4:]}")
                    present = exported is not None and hasattr(exported, name)
                else:
                    present = f"test_resources_{suite[5:]}__{symbol[5:]}" in globals()
                assert present == (status == "restored")
    assert counts == report["counts"]
