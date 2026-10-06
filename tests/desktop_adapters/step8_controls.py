"""Complete frozen synthetic vision corpus, with no setup or behavior adaptation.

The other mapped controls suites are not partially exported here: their removed
transport or identity contracts require disposition, not a compatibility facade.
"""
from __future__ import annotations

import ast
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module

CORPUS_SELECTIONS = {"test_computer_native_vision_r5": None}
CORPUS_EXCLUSIONS = {}
SUITES = {
    "test_computer_native_vision_r5": (
        "41fd36c3afe06c24f1221d9a809fba96efddd4f77d12878080f6a4984b6681c7"
    )
}
SOURCE_PATH = "tests/test_computer_native_vision_r5.py"
SOURCE_SHA256 = "41fd36c3afe06c24f1221d9a809fba96efddd4f77d12878080f6a4984b6681c7"


def validate_source(source):
    """Fail before compiling changed source, assertions or case signatures."""
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("controls vision baseline bytes changed")
    original = ast.parse(source, filename=SOURCE_PATH)
    adapted = ast.parse(source, filename=SOURCE_PATH)
    if corpus(original) != corpus(adapted) or dump(original) != dump(adapted):
        raise ValueError("controls vision complete AST changed")
    return original, adapted


def load(namespace):
    original, tree = validate_source(frozen_source(SOURCE_PATH))
    module = ModuleType("frozen_step8_controls_vision")
    module.__dict__["__file__"] = SOURCE_PATH
    exec(compile(tree, SOURCE_PATH, "exec"), module.__dict__)
    register_module(namespace, module, prefix="controls_vision")
    return original, tree
