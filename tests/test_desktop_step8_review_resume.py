"""Rejected resume adapter cannot claim normalized assertion preservation."""

import hashlib
import json
from pathlib import Path

import pytest
import pytest_asyncio

from scripts.maintenance.fixture_corpus import dump, frozen_source, nodes
from tests.desktop_adapters.step8_review_resume import (
    SOURCE_PATH,
    SOURCE_SHA256,
    adapt,
    owner_fixture,
)


@pytest_asyncio.fixture(autouse=True)
async def authenticated_owner(tmp_path):
    async for state in owner_fixture(tmp_path):
        yield state


def test_frozen_resume_preserves_bytes_but_rejects_changed_assertion_corpus():
    source = frozen_source(SOURCE_PATH)
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA256
    with pytest.raises(ValueError, match="blocked resume assertion"):
        adapt(source)


def test_frozen_resume_setup_rejects_rule_drift():
    source = frozen_source(SOURCE_PATH)
    with pytest.raises(ValueError, match="allowlist"):
        adapt(source, hunks=[])
    with pytest.raises(ValueError, match="source bytes"):
        adapt(source + b"\n")


def test_persistent_resume_admission_manifest_matches_frozen_ast():
    import ast
    path = (
        Path(__file__).resolve().parents[1]
        / "maintenance/step8-review-resume-admission-manifest.json")
    manifest = json.loads(path.read_text())
    from tests.desktop_adapters.step8_review_resume import _rules
    original = ast.parse(frozen_source(SOURCE_PATH))
    rules = _rules(original)
    cases = [(s, n) for s, n in nodes(original)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name.startswith("test_")]

    def digest(text):
        return hashlib.sha256(text.encode()).hexdigest()

    assert manifest["cases"] == {s: digest(dump(n)) for s, n in cases}
    assert manifest["assertion_hashes"] == [digest(json.dumps([
        dump(x) for x in ast.walk(n) if isinstance(x, ast.Assert)])) for _, n in cases]
    for key, component in (("signature_hashes", lambda n: dump(n.args)),
                           ("decorator_hashes",
                            lambda n: json.dumps([dump(x) for x in n.decorator_list]))):
        actual = {}
        for index, (_, node) in enumerate(cases):
            actual.setdefault(digest(component(node)), []).append(index)
        assert manifest[key] == actual
    declared = {(line, column, r["before"], r["after"], r["source"])
                for r in manifest["setup_rules"] for line, column in r["positions"]}
    expected = {(r["line"], r["column"], r["before_sha256"], r["after_sha256"], r["after_source"])
                for r in rules}
    assert declared == expected
