"""Unmodified retained test bodies from five-suite accounting, never whole restores."""
from __future__ import annotations

import ast
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import dump, frozen_source

HASHES = {
    "test_gitlab_webhook": "69af5dbd480853daecad94389462663e7a6be8780d479549ef11b4b311446350",
    "test_self_audit_fixes": "bc37ab85b43c9348118f4ff8c1163f4ef49b559b90c077d96f671ec08477605b",
}
CLASSES = {
    "test_gitlab_webhook": {"TestSchedulerGitLabSource"},
    "test_self_audit_fixes": {"TestKnowledgeStoreConcurrency", "TestConfigSchemaFields"},
}
DEFERRED = {
    "TestConfigSchemaFields.test_trajectory_path_has_default",
    "TestConfigSchemaFields.test_audit_log_path_has_default",
}
CASE_MAP = {}
PROJECTED_AST = {}


def export(namespace):
    for stem, selected in CLASSES.items():
        source = frozen_source(f"tests/{stem}.py")
        if hashlib.sha256(source).hexdigest() != HASHES[stem]:
            raise ValueError("Frozen part6 hash changed")
        original = ast.parse(source)
        # Only imports required by unchanged selected bodies. No setup/data/
        # assertion transformation, fake ingress, or old Discord config facade.
        tree = ast.Module(body=[ast.Import(names=[ast.alias(name="pytest")])], type_ignores=[])
        tree.body += ast.parse("import asyncio\nfrom src.scheduler.scheduler import Scheduler").body
        tree.body += [node for node in original.body
                      if isinstance(node, ast.ClassDef) and node.name in selected]
        if {node.name for node in tree.body if isinstance(node, ast.ClassDef)} != selected:
            raise ValueError("Incomplete frozen selection")
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                node.body = [child for child in node.body
                             if f"{node.name}.{getattr(child, 'name', '')}" not in DEFERRED]
                PROJECTED_AST[f"tests/{stem}.py::{node.name}"] = dump(node)
        module = ModuleType(stem)
        module.__file__ = f"tests/{stem}.py"
        exec(compile(ast.fix_missing_locations(tree), module.__file__, "exec"), module.__dict__)
        for name in sorted(selected):
            owner = getattr(module, name)
            exported = f"TestPart6_{stem}_{name}"
            owner.__module__ = namespace["__name__"]
            owner.__name__ = owner.__qualname__ = exported
            namespace[exported] = owner
            for node in next(n for n in original.body if isinstance(n, ast.ClassDef)
                             and n.name == name).body:
                if (getattr(node, "name", "").startswith("test_")
                        and f"{name}.{node.name}" not in DEFERRED):
                    CASE_MAP[f"tests/{stem}.py::{name}::{node.name}"] = (
                        f"tests/test_desktop_step8_part6_retained.py::{exported}::{node.name}")
