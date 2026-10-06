"""Run the complete, assertion-identical frozen turn-state test corpus."""

import ast

from scripts.maintenance.fixture_corpus import corpus, frozen_source
from tests.desktop_adapters.step5_observability_turn_state import (
    CASE_MAP,
    EVIDENCE,
    load,
)

SOURCE_PATH = "tests/test_web_api_turn_state.py"
SOURCE_SHA256 = "23a20c4e9b712c53499bf638abe64cbb654e681a1ff675bd4de1882d6c0067e3"
CORPUS_SELECTIONS = {"test_web_api_turn_state": None}
CORPUS_EXCLUSIONS = {}

load(globals())


def test_whole_frozen_turn_state_corpus_is_exact():
    original = ast.parse(frozen_source(SOURCE_PATH))
    assert corpus(original) == EVIDENCE[SOURCE_PATH]["exact_corpus"]
    expected = {symbol for symbol, *_ in corpus(original)["cases"]}
    exported = {key.removeprefix(SOURCE_PATH + "::").replace("::", ".")
                for key in CASE_MAP if key.startswith(SOURCE_PATH + "::")}
    assert expected == exported
