"""Unqualified alternative: compile every frozen assertion, observe real IPC.

The six transport-independent executions can replay unchanged assertions. The
three obsolete HTTP executions are deliberately probed, not retired or passed.
No wrapper exposes synthetic full_url/get_header/data fields.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source

SOURCE_PATH = "tests/test_campaign_cli_coverage.py"
SOURCE_SHA256 = "fe47a4c99af2c48f8bf397a0634830b82c5afa50e74ab53eb0fb26864a434d0b"
CORPUS_SELECTIONS = {"test_campaign_cli_coverage": None}
CORPUS_EXCLUSIONS = {}
# These setup-only rules are experimental, not an admitted suite-map change.
SETUP_RULES = (
    (19, 'monkeypatch.setattr(cli.urllib.request, "urlopen", transport)',
     "monkeypatch.setattr(cli.local_client.LocalClient, 'connect', transport)"),
    (30, 'monkeypatch.setattr(cli.sys, "argv", ["odin", "hello", "--json"])',
     "monkeypatch.setattr(cli.sys, 'argv', ['odin', *ipc_arguments, 'hello', '--json'])"),
    (31, 'monkeypatch.setattr(cli.urllib.request, "urlopen", Mock(side_effect=error))',
     "arm_real_failure(error)"),
    (41, 'monkeypatch.setattr(cli.sys, "argv", ["odin", "--timeout", "12"])',
     "monkeypatch.setattr(cli.sys, 'argv', ['odin', *ipc_arguments, '--timeout', '12'])"),
    (53, 'monkeypatch.setattr(cli.urllib.request, "urlopen", transport)',
     "retain_original_transport(transport)"),
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


def load(**bindings):
    original, tree = adapt(frozen_source(SOURCE_PATH))
    module = ModuleType("frozen_step8_review_cli_exact")
    module.__file__ = SOURCE_PATH
    module.__dict__.update(bindings)
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    return module, original, tree
