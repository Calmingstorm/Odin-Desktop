"""Whole frozen ingestion suite with exact temporary-root admission setup hunks."""

from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, nodes, register_module

SOURCE_DIGESTS = {
    "tests/test_knowledge_ingest_outcomes.py":
        "b2e46ac4039a15a267e14d9edd40ac420f4492ab5593fe7cc3f83ae8cb382a6d",
    "tests/test_search_small_delivery_budget.py":
        "8b6a4770edc3052255728030aaa367dbe57c531732215f7818e1e38a6f32c40c",
    "tests/test_turn_recorder_webhook_campaign.py":
        "e5cf1d18e667a580878ee4d067e66341f423f8eeab09c359cbec76d63f54d7aa",
}
INGEST_PATH = "tests/test_knowledge_ingest_outcomes.py"
SUITES = {
    "test_knowledge_ingest_outcomes":
        "b2e46ac4039a15a267e14d9edd40ac420f4492ab5593fe7cc3f83ae8cb382a6d",
}
CORPUS_SELECTIONS = {"test_knowledge_ingest_outcomes": None}
CORPUS_EXCLUSIONS = {}
SETUP_HUNKS = (
    ("TestImporterOutcomes.test_reimport_of_stored_file_reports_already_stored", 287),
    ("TestImporterOutcomes.test_identical_content_under_another_source_is_skipped_not_failed", 308),
    ("TestImporterOutcomes.test_durability_failure_is_still_an_error", 328),
    ("TestImporterOutcomes.test_near_duplicate_import_is_skipped_with_the_existing_source", 341),
    ("TestImporterOutcomes.test_plain_int_results_from_a_double_keep_old_semantics", 375),
    ("TestImporterOutcomes.test_unchanged_counts_as_success_and_duplicate_as_skipped", 391),
    ("TestImporterOutcomes.test_web_url_reimport_reports_unchanged", 427),
)
BEFORE_DIGEST = "e159c243595f10ab2c0d3a56c7a4c1d1c84b27df07e4bd30d5929e1eb37ec159"
AFTER_DIGEST = "b7d59529b5f9169038899808c2185b6f48b33155e3ffaafa397ac0ae46fbf969"
BEFORE_CALL = ast.parse("BulkImporter(store)", mode="eval").body
AFTER_CALL = ast.parse("BulkImporter(store, admitted_roots=[tmp_path])", mode="eval").body


def source_tree(path):
    source = frozen_source(path)
    assert hashlib.sha256(source).hexdigest() == SOURCE_DIGESTS[path]
    return ast.parse(source)


def verify_adaptation(original, adapted):
    """An independent complete expected tree admits only seven exact setup calls."""
    expected = copy.deepcopy(original)
    for symbol, line in SETUP_HUNKS:
        matches = [node for owner, node in nodes(expected)
                   if owner == symbol and getattr(node, "lineno", None) == line
                   and isinstance(node, ast.Call)
                   and dump(node) == dump(BEFORE_CALL)]
        assert len(matches) == 1, (symbol, line)
        call = matches[0]
        assert hashlib.sha256(dump(call).encode()).hexdigest() == BEFORE_DIGEST
        call.keywords = copy.deepcopy(AFTER_CALL.keywords)
        assert hashlib.sha256(dump(call).encode()).hexdigest() == AFTER_DIGEST
    assert corpus(original) == corpus(adapted)
    assert dump(expected) == dump(adapted)
    return True


def adapted_tree():
    original = source_tree(INGEST_PATH)
    tree = copy.deepcopy(original)
    for symbol, line in SETUP_HUNKS:
        matches = [node for owner, node in nodes(tree)
                   if owner == symbol and getattr(node, "lineno", None) == line
                   and isinstance(node, ast.Call)
                   and hashlib.sha256(dump(node).encode()).hexdigest() == BEFORE_DIGEST]
        assert len(matches) == 1, (symbol, line)
        call = matches[0]
        assert dump(call) == dump(BEFORE_CALL)
        call.keywords.append(ast.keyword(
            arg="admitted_roots",
            value=ast.List(elts=[ast.Name(id="tmp_path", ctx=ast.Load())], ctx=ast.Load()),
        ))
        assert dump(call) == dump(AFTER_CALL)
    verify_adaptation(original, tree)
    return ast.fix_missing_locations(tree)


def export_whole_suite(namespace):
    """Execute/export every inherited definition and helper, never a case subset."""
    module = ModuleType("desktop_step8_runtime_c_ingest")
    exec(compile(adapted_tree(), INGEST_PATH, "exec"), module.__dict__)
    assert not any(name in namespace for name in vars(module) if not name.startswith("__"))
    register_module(namespace, module)
    exported = {}
    for name, value in module.__dict__.items():
        if name.startswith("__"):
            continue
        if getattr(value, "__module__", None) == module.__name__:
            value.__module__ = namespace["__name__"]
        assert name not in namespace or namespace[name] is value, name
        namespace[name] = value
        exported[name] = value
    return exported


def load(namespace):
    """Public whole-module loader; no subset or exclusions are supported."""
    return export_whole_suite(namespace)
