"""Hash/corpus-bound neutral campaign regressions under private canonical owner."""

import pytest

from scripts.maintenance.fixture_corpus import corpus
from tests.desktop_adapters.step8_6a_campaigns import (
    CORPUS_EXCLUSIONS,
    CORPUS_SELECTIONS,
    DEFERRED_CASES,
    PARTIAL_CASES,
    SUITES,
    SUPPORT_SUITES,
    load,
    load_support,
    owner_fixture,
)


@pytest.fixture(autouse=True)
def _campaign_private_owner(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with owner_fixture(tmp_path):
        yield


_pairs = load(globals())
_support_pairs = load_support(globals())


def test_campaign_frozen_assertions_signatures_decorators_and_parameters():
    assert all(corpus(original) == corpus(adapted) for original, adapted in _pairs)


def test_campaign_support_preserves_assertions_signatures_decorators_and_parameters():
    assert all(corpus(original) == corpus(adapted) for original, adapted in _support_pairs)


def test_campaign_whole_admission_and_exact_complete_case_support_projection():
    assert set(CORPUS_SELECTIONS) == set(SUITES)
    assert all(value is None for value in CORPUS_SELECTIONS.values())
    assert set(SUITES).isdisjoint(SUPPORT_SUITES)
    assert set(PARTIAL_CASES) <= set(SUPPORT_SUITES)
    for stem, (original, _adapted) in zip(
        [*SUITES, *SUPPORT_SUITES], [*_pairs, *_support_pairs], strict=True,
    ):
        names = {name for name, _signature, _decorators in corpus(original)['cases']}
        excluded = {row['case'] for row in CORPUS_EXCLUSIONS.get(stem, ())}
        excluded.update(DEFERRED_CASES.get(stem, ()))
        expected = names - excluded
        if stem in PARTIAL_CASES:
            expected &= PARTIAL_CASES[stem]
        registered = set()
        for name, value in list(globals().items()):
            if name.startswith(f'test_{stem}_') and callable(value):
                registered.add('test_' + name.removeprefix(f'test_{stem}_'))
            elif name.startswith(f'Test_{stem}_') and isinstance(value, type):
                class_name = 'Test' + name.removeprefix(f'Test_{stem}_')
                registered.update(
                    f'{class_name}.{method}' for method in vars(value)
                    if method.startswith('test_')
                )
        assert registered == expected
