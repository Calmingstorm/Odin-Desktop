"""Exact frozen startup diagnostics with reviewer-authorized removed cases.

The retired definition remains compiled, with unchanged assertions and parameters,
but is never exported to pytest. No substitute Discord/HTTP health is invented.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from scripts.maintenance.fixture_corpus import register_module as export_module

ROOT = Path(__file__).resolve().parents[2]
REVIEWER = "Claude, review of #34, round 3"
CORPUS_SELECTIONS = {"test_campaign_startup_health": None}
CORPUS_EXCLUSIONS = {
    "test_campaign_startup_health": [
        {
            "case": "test_production_health_wiring_keeps_http_bootstrap_ready",
            "reviewer": "Claude, review of #34, round 3",
            "reason": "Discord and the HTTP listener removed",
            "source_path": "tests/test_campaign_startup_health.py",
            "source_sha256": "41666712c09447ad5b362804478f7550a98329dda605db5c61c86b30e298f4ac",
        }
    ]
}
SUITES = {
    "test_campaign_startup_health":
        "41666712c09447ad5b362804478f7550a98329dda605db5c61c86b30e298f4ac",
}
REMOVED_IMPORTS = (
    "from src.__main__ import _wire_observability",
    "from src.config.schema import Config, WebhookConfig",
    "from src.health.server import HealthServer",
)


def source_tree(name):
    data = frozen_source(f"tests/{name}.py")
    if hashlib.sha256(data).hexdigest() != SUITES[name]:
        raise ValueError("inherited source hash changed")
    return ast.parse(data)


def _adapt(original):
    tree = copy.deepcopy(original)
    for source in REMOVED_IMPORTS:
        expected = dump(ast.parse(source).body[0])
        matches = [node for node in tree.body if dump(node) == expected]
        if len(matches) != 1:
            raise ValueError("exact removed-surface import must match once")
        tree.body.remove(matches[0])
    return tree


def verify_adaptation(name, adapted):
    original = source_tree(name)
    if dump(_adapt(original)) != dump(adapted):
        raise ValueError("undeclared source change or missing inherited case/helper")
    if corpus(original) != corpus(adapted):
        raise ValueError("inherited assertion/signature/decorator meaning changed")
    return True


def adapted_tree(name):
    tree = _adapt(source_tree(name))
    verify_adaptation(name, tree)
    return ast.fix_missing_locations(tree)


def records():
    return json.loads((ROOT / "maintenance/step8-part2-review-health.json").read_text())


def verify_dispositions():
    rows = records()["entries"]
    startup = next(row for row in rows if row["path"] == "tests/test_campaign_startup_health.py")
    if (startup.get("reviewer") != REVIEWER or startup["status"] != "restored"
            or startup["restoration"]["case_retirements"]
            != CORPUS_EXCLUSIONS["test_campaign_startup_health"]):
        raise ValueError("startup case retirement authority changed")
    endpoints = next(row for row in rows if row["path"] == "tests/test_health_endpoints.py")
    data = frozen_source(endpoints["path"])
    if hashlib.sha256(data).hexdigest() != endpoints["inherited_sha256"]:
        raise ValueError("inherited endpoint source hash changed")
    original = corpus(ast.parse(data))
    cases = {name for name, _, _ in original["cases"]}
    retired = endpoints["case_retirements"]
    if (endpoints["status"] != "retired" or endpoints.get("reviewer") != REVIEWER
            or len(retired) != len(cases)
            or [row["case"] for row in retired] != sorted(cases)):
        raise ValueError("every retired endpoint case must be accounted exactly once")
    for row in retired:
        tier = row["case"].startswith(
            ("TestContextWindowsAdminPolicy.", "TestBuiltinToolsAdminPolicy.")
        )
        if row != {
            "case": row["case"], "reviewer": REVIEWER,
            "reason": ("multi-user tiers removed" if tier else
                       "HTTP health endpoints removed with the listener"),
            "source_path": endpoints["path"], "source_sha256": endpoints["inherited_sha256"],
        }:
            raise ValueError("endpoint case retirement authority changed")
    return True


def register_module(namespace, module, *, prefix, excluded):
    """Export all and only nonretired definitions from the intact compiled module."""
    expected = [row["case"] for row in CORPUS_EXCLUSIONS[prefix]]
    if excluded != expected:
        raise ValueError("unreviewed inherited export exclusion")
    projected = ModuleType(module.__name__ + "_export")
    projected.__dict__.update({name: value for name, value in vars(module).items()
                               if name not in excluded})
    export_module(namespace, projected, prefix=prefix, full_class_name=True)


def load(namespace):
    verify_dispositions()
    for name in CORPUS_SELECTIONS:
        module = ModuleType(f"desktop_step8_review_health_round3_{name}")
        module.__file__ = str(ROOT / f"tests/{name}.py")
        exec(compile(adapted_tree(name), module.__file__, "exec"), module.__dict__)
        expected = [case for case, _, _ in corpus(source_tree(name))["cases"]]
        actual = [key for key in vars(module) if key.startswith("test_")]
        if sorted(actual) != sorted(expected):
            raise ValueError("incomplete inherited suite compilation")
        register_module(namespace, module, prefix=name,
                        excluded=[item['case'] for item in CORPUS_EXCLUSIONS.get(name, ())])
