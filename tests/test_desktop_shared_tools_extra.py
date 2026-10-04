"""Audited frozen read-file, retry, bulkhead and timeout requalification."""

import ast

import pytest

from tests.desktop_adapters.tools_cases import owner_fixture
from tests.desktop_adapters.tools_extra import (
    CORPUS_SELECTIONS,
    ImportSurfaces,
    corpus,
    export_suite,
    frozen_source,
)


@pytest.fixture(autouse=True)
def desktop_extra_owner(tmp_path_factory):
    with owner_fixture(tmp_path_factory.mktemp("desktop-extra-owner")):
        yield


@pytest.mark.parametrize("name", list(CORPUS_SELECTIONS))
def test_extra_frozen_assertions_and_parameter_corpus_are_unchanged(name):
    source = frozen_source(f"tests/{name}.py")
    assert corpus(ast.parse(source)) == corpus(ImportSurfaces().visit(ast.parse(source)))


for _suite in CORPUS_SELECTIONS:
    export_suite(globals(), _suite)
