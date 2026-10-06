"""Round-2 CLI replay: six original executions, three approved HTTP retirements.

Only no-transport setup changes to the real LocalClient.connect boundary. The
complete frozen AST stays compiled; discovery excludes exactly the two approved
HTTP cases (three parametrized executions), never their assertion bodies.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from scripts.maintenance.fixture_corpus import register_module as shared_register_module

SOURCE_PATH = "tests/test_campaign_cli_coverage.py"
SOURCE_SHA256 = "fe47a4c99af2c48f8bf397a0634830b82c5afa50e74ab53eb0fb26864a434d0b"
CORPUS_SELECTIONS = {"test_campaign_cli_coverage": None}
CORPUS_EXCLUSIONS = {"test_campaign_cli_coverage": [
    {"case": "test_piped_prompt_and_environment_build_real_authenticated_request",
     "reviewer": "Claude, review of #35, round 2",
     "reason": "HTTP API client replaced by the authenticated local IPC client",
     "source_path": "tests/test_campaign_cli_coverage.py",
     "source_sha256": "fe47a4c99af2c48f8bf397a0634830b82c5afa50e74ab53eb0fb26864a434d0b"},
    {"case": "test_transport_failure_is_nonzero_even_in_json_mode",
     "reviewer": "Claude, review of #35, round 2",
     "reason": "HTTP API client replaced by the authenticated local IPC client",
     "source_path": "tests/test_campaign_cli_coverage.py",
     "source_sha256": "fe47a4c99af2c48f8bf397a0634830b82c5afa50e74ab53eb0fb26864a434d0b"},
]}
SETUP_RULES = (
    (19, 'monkeypatch.setattr(cli.urllib.request, "urlopen", transport)',
     "monkeypatch.setattr(cli.local_client.LocalClient, 'connect', transport)"),
    (70, 'monkeypatch.setattr(cli.urllib.request, "urlopen", network)',
     "monkeypatch.setattr(cli.local_client.LocalClient, 'connect', network)"),
)


def adapt(source, *, rules=None):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("CLI frozen bytes changed")
    admitted = SETUP_RULES if rules is None else rules
    if admitted != SETUP_RULES:
        raise ValueError("CLI exact setup allowlist changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    tree = copy.deepcopy(original)
    for line, before, after in admitted:
        expected = dump(ast.parse(before).body[0])
        matches = [(parent, index, node)
                   for parent in ast.walk(tree)
                   if isinstance(getattr(parent, "body", None), list)
                   for index, node in enumerate(parent.body)
                   if isinstance(node, ast.AST)
                   and getattr(node, "lineno", None) == line and dump(node) == expected]
        if len(matches) != 1:
            raise ValueError("CLI setup must match exactly once")
        parent, index, node = matches[0]
        body = parent.body
        body[index] = ast.copy_location(ast.parse(after).body[0], node)
    ast.fix_missing_locations(tree)
    if corpus(tree) != corpus(original):
        raise ValueError("CLI assertion/signature/decorator/parameter drift")
    restored = copy.deepcopy(tree)
    for line, before, after in admitted:
        matches = [(parent, index, node) for parent in ast.walk(restored)
                   if isinstance(getattr(parent, "body", None), list)
                   for index, node in enumerate(parent.body)
                   if getattr(node, "lineno", None) == line
                   and dump(node) == dump(ast.parse(after).body[0])]
        if len(matches) != 1:
            raise ValueError("CLI reverse replay match changed")
        parent, index, _node = matches[0]
        parent.body[index] = ast.parse(before).body[0]
    if dump(restored) != dump(original):
        raise ValueError("CLI complete AST reverse replay failed")
    return original, tree


def register_module(namespace, module, *, prefix=None, excluded=()):
    """Project pytest discovery only, never substitute test functions/assertions."""
    expected = [item["case"] for item in
                CORPUS_EXCLUSIONS["test_campaign_cli_coverage"]]
    if list(excluded) != expected or len(set(excluded)) != len(excluded):
        raise ValueError("CLI exact approved retirement projection changed")
    exposed = ModuleType(module.__name__ + "_exposed")
    exposed.__dict__.update({name: value for name, value in vars(module).items()
                             if name not in excluded})
    shared_register_module(namespace, exposed, prefix=prefix)


def load(namespace):
    original, tree = adapt(frozen_source(SOURCE_PATH))
    module = ModuleType("frozen_step8_review_cli_exact")
    module.__file__ = SOURCE_PATH
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    stem = "test_campaign_cli_coverage"
    register_module(namespace, module, prefix=stem,
                    excluded=[item["case"] for item in CORPUS_EXCLUSIONS.get(stem, ())])
    return module, original, tree
