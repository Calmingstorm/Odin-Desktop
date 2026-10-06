"""Whole frozen Hyprland suites without unavailable foreground dispatch IO."""
import pytest

from scripts.maintenance.fixture_corpus import corpus
from tests.desktop_adapters.step8_6a_hyprland import SUITES, adapted, load

load(globals())


@pytest.mark.parametrize("name", sorted(SUITES))
def test_hyprland_complete_corpus_and_case_dispositions(name):
    original, changed = adapted(name)
    assert corpus(original) == corpus(changed)
