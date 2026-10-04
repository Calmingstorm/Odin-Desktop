"""Frozen pure computer declaration cases. No native lifecycle runs."""

from tests.test_desktop_shared_config import _load_corpus

CORPUS_SELECTIONS = {"computer_profile_status_r6": None}

_load_corpus("computer_profile_status_r6", destination=globals())
