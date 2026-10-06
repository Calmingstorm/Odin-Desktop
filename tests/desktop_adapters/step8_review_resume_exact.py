"""Exact resume assertion corpus on authenticated RequestService controls.

Legacy explicit entry names are fixture aliases to the actual control dispatcher,
not rewritten assertions and not direct runner admission. Production is untouched.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source
from scripts.maintenance.fixture_corpus import register_module as shared_register_module
from tests.desktop_adapters.step8_review_resume import owner_fixture as owner_fixture
from tests.desktop_adapters.step8_wait import _paths, _put

MANIFEST = (Path(__file__).resolve().parents[2]
            / "maintenance/step8-review-resume-alternative-candidates.json")
HUNKS_SHA256 = "516e19f3704213f9725221ee714d5265f2b86db83e928331f3bf4a986e389562"
SOURCE_PATH = "tests/test_resume_admission.py"
SOURCE_SHA256 = "995d1fb1df090aeb4ed5f5983859ae712f56de87f7f86e6e58c72ae20a8a41ce"
CORPUS_SELECTIONS = {"test_resume_admission": None}
CORPUS_EXCLUSIONS = {"test_resume_admission": [
    {"case":
     "TestExplicitResume.test_fetch_permission_failure_is_truthful_and_keeps_turn_resumable",
     "reviewer": "Claude, review of #35",
     "reason": "Removed Discord fetch-permission denial surface: injects Discord Forbidden 50013 "
     "and asserts Discord denial prose. Desktop transcript lookup has no Discord permission "
     "layer; retained fetch-outage cases preserve the checkpoint and calibration lease.",
     "source_path": "tests/test_resume_admission.py",
     "source_sha256": "995d1fb1df090aeb4ed5f5983859ae712f56de87f7f86e6e58c72ae20a8a41ce"},
    {"case": "TestExplicitResume.test_wrong_author_gets_notice",
     "reviewer": "Claude, review of #35",
     "reason": "Removed Discord multi-author resume intake and wrong-author notice. Desktop has "
     "one "
     "authenticated canonical profile owner; authentication and original-author provenance "
     "rejection remain supported and tested.",
     "source_path": "tests/test_resume_admission.py",
     "source_sha256": "995d1fb1df090aeb4ed5f5983859ae712f56de87f7f86e6e58c72ae20a8a41ce"},
    {"case": "TestMentionAnchoredResumeTrigger.test_foreign_mention_is_not_stripped",
     "reviewer": "Claude, review of #35",
     "reason": "Removed Discord foreign-mention stripping at resume intake; desktop bare resume "
     "and non-trigger pass-through remain supported and tested.",
     "source_path": "tests/test_resume_admission.py",
     "source_sha256": "995d1fb1df090aeb4ed5f5983859ae712f56de87f7f86e6e58c72ae20a8a41ce"},
    {"case": "TestMentionAnchoredResumeTrigger.test_leading_mention_resume_triggers",
     "reviewer": "Claude, review of #35",
     "reason": "Removed Discord leading bot-mention resume intake; desktop bare resume remains "
     "supported and tested.",
     "source_path": "tests/test_resume_admission.py",
     "source_sha256": "995d1fb1df090aeb4ed5f5983859ae712f56de87f7f86e6e58c72ae20a8a41ce"},
    {"case": "TestMentionAnchoredResumeTrigger.test_mention_plus_sentence_is_not_a_command",
     "reviewer": "Claude, review of #35",
     "reason": "Removed Discord mention-plus-sentence command intake; desktop bare resume and "
     "non-trigger pass-through remain supported and tested.",
     "source_path": "tests/test_resume_admission.py",
     "source_sha256": "995d1fb1df090aeb4ed5f5983859ae712f56de87f7f86e6e58c72ae20a8a41ce"},
    {"case": "TestMentionAnchoredResumeTrigger.test_mention_recognized_trigger_still_fails_closed",
     "reviewer": "Claude, review of #35",
     "reason": "Removed Discord mention-recognized resume intake; desktop bare resume rejection "
     "and fail-closed checkpoint admission remain supported and tested.",
     "source_path": "tests/test_resume_admission.py",
     "source_sha256": "995d1fb1df090aeb4ed5f5983859ae712f56de87f7f86e6e58c72ae20a8a41ce"},
    {"case": "TestMentionAnchoredResumeTrigger.test_nickname_mention_form_triggers",
     "reviewer": "Claude, review of #35",
     "reason": "Removed Discord nickname bot-mention resume intake; desktop bare resume remains "
     "supported and tested.",
     "source_path": "tests/test_resume_admission.py",
     "source_sha256": "995d1fb1df090aeb4ed5f5983859ae712f56de87f7f86e6e58c72ae20a8a41ce"},
    {"case": "TestMentionAnchoredResumeTrigger.test_trailing_mention_is_not_a_command",
     "reviewer": "Claude, review of #35",
     "reason": "Removed Discord trailing-mention command intake; desktop bare resume and "
     "non-trigger pass-through remain supported and tested.",
     "source_path": "tests/test_resume_admission.py",
     "source_sha256": "995d1fb1df090aeb4ed5f5983859ae712f56de87f7f86e6e58c72ae20a8a41ce"},
]}


def digest(node):
    return hashlib.sha256(dump(node).encode()).hexdigest()


def adapt(source, *, hunks=None):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("resume frozen source bytes changed")
    manifest = json.loads(MANIFEST.read_text())
    manifest_hash = hashlib.sha256(json.dumps(
        manifest["hunks"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if manifest_hash != HUNKS_SHA256:
        raise ValueError("resume immutable hunk manifest hash changed")
    rules = [dict(r, line=line, column=column) for r in manifest["hunks"]
             for line, column in r["positions"]]
    if hunks is not None and hunks != rules:
        raise ValueError("resume immutable hunk manifest changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    tree = copy.deepcopy(original)
    lookup = {(r["line"], r["column"], r["before_sha256"]): r for r in rules}
    if len(lookup) != len(rules):
        raise ValueError("duplicate resume hunk")
    seen = set()
    class Exact(ast.NodeTransformer):
        def visit(self, node):
            key = (getattr(node, "lineno", None), getattr(node, "col_offset", None), digest(node))
            if key not in lookup:
                return super().visit(node)
            if key in seen:
                raise ValueError("resume hunk matched twice")
            rule = lookup[key]
            parsed = ast.parse(rule["after_source"], mode="eval" if rule["expression"] else "exec")
            if not rule["expression"] and len(parsed.body) != 1:
                raise ValueError("resume replacement hash requires one node")
            replacement = parsed.body if rule["expression"] else parsed.body[0]
            if digest(replacement) != rule["after_sha256"]:
                raise ValueError("resume replacement hash mismatch")
            seen.add(key)
            return ast.copy_location(replacement, node)
    tree = Exact().visit(tree)
    if seen != set(lookup):
        raise ValueError("resume hunk not applied exactly once")
    ast.fix_missing_locations(tree)
    restored = copy.deepcopy(tree)
    for path, node in _paths(original):
        key = (getattr(node, "lineno", None), getattr(node, "col_offset", None), digest(node))
        if key in seen:
            _put(restored, path, copy.deepcopy(node))
    if dump(restored) != dump(original):
        raise ValueError("resume complete reverse replay failed")
    if corpus(original) != corpus(tree):
        raise ValueError("resume exact assertion/signature/decorator/parameter corpus changed")
    return original, tree, rules


def register_module(namespace, module, *, prefix=None, excluded=()):
    """Filter discovery clones only; preserve the complete frozen module and AST."""
    exposed = ModuleType(module.__name__ + "_exposed")
    exposed.__dict__.update(module.__dict__)
    excluded = set(excluded)
    for cls_name in {case.split(".")[0] for case in excluded}:
        cls = getattr(module, cls_name)
        attrs = {key: value for key, value in vars(cls).items()
                 if key not in {"__dict__", "__weakref__"}
                 and f"{cls_name}.{key}" not in excluded}
        setattr(exposed, cls_name, type(cls_name, cls.__bases__, attrs))
    shared_register_module(namespace, exposed, prefix=prefix, full_class_name=True)


def load(namespace):
    original, tree, rules = adapt(frozen_source(SOURCE_PATH))
    module = ModuleType("frozen_step8_review_resume_exact")
    module.__file__ = SOURCE_PATH
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    stem = "test_resume_admission"
    register_module(namespace, module, prefix="step8_review_resume_exact",
                    excluded=[item["case"] for item in CORPUS_EXCLUSIONS.get(stem, ())])
    return original, tree, rules
