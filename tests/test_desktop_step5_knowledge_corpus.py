"""Complete inherited knowledge and learning corpus."""
from types import SimpleNamespace

import pytest

from src.desktop.authority import OwnerAuthority
from src.desktop.paths import ProfilePaths
from tests.desktop_adapters.step5_knowledge_corpus import load
from tests.desktop_adapters.step5_knowledge_services import fixture_state


@pytest.fixture(autouse=True)
def step5_knowledge_owner(tmp_path):
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    token = fixture_state.set(SimpleNamespace(paths=paths, authority=authority))
    try:
        yield
    finally:
        fixture_state.reset(token)
        authority.release_runtime()

load(globals())
