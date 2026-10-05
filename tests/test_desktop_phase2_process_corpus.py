"""All frozen process-manager cases on the retained neutral engine."""
import pytest

from scripts.maintenance.fixture_corpus import corpus
from tests.desktop_adapters.process_cases import load, temporary_owner


@pytest.fixture(autouse=True)
def _authentic_temporary_process_owner(tmp_path):
    with temporary_owner(tmp_path):
        yield


_original, _adapted = load(globals())


def test_process_corpus_exact_assertions_and_parameters():
    assert corpus(_original) == corpus(_adapted)
