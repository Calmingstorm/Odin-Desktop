"""Exact frozen foundation corpus with narrowly admitted Desktop fixture setup.

No assertion, test signature, decorator or parameter value is rewritten. Removed
transport contracts are selected out by exact name, never replaced by fake APIs.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import tempfile as _tempfile
from pathlib import Path
from types import ModuleType

from scripts.maintenance.fixture_corpus import (
    ROOT,
    apply_transformations,
    dump,
    frozen_source,
    nodes,
    verify_transform,
)
from src.knowledge.importer import BulkImporter as EngineImporter
from src.search.embedder import LocalEmbedder as EngineEmbedder
from tests.desktop_adapters.tools_cases import ToolExecutor as ToolExecutor
from tests.desktop_adapters.tools_cases import _fixture

CORPUS_SELECTIONS = {
    "test_apply_registry": None,
    "test_builtin_tool_policy": [
        "TestNormalization", "TestDispatchRejection", "TestCatalogFiltering",
    ],
    "test_documented_tool_contracts": [],
    "test_embedder_loading": None,
    "test_error_presentation": None,
    "test_generated_tool_reference": [
        "test_committed_tool_reference_is_byte_identical",
        "test_cli_check_works_outside_repo_and_without_git",
        "test_complete_served_descriptions_and_core_flags",
        "test_every_property_row_and_order_is_rendered",
        "test_nested_required_and_constraints_are_not_lost",
        "test_untrusted_markup_and_vue_expressions_stay_literal",
        "test_drift_check_fails_without_writing",
    ],
    "test_host_access": ["TestEntrySemantics.test_to_dict_roundtrip"],
    "test_hosts_ratcheted_consumers": None,
    "test_image_backends": None,
    "test_knowledge_import": [
        "TestImportResult", "TestBatchResult", "TestImportDirectory", "TestLocalFileIntegrity",
        "TestImportPdfUrl", "TestImportWebUrl", "TestImportBatch", "TestConstants",
        "TestModuleImports", "TestEdgeCases", "TestToolDefinition",
    ],
    "test_skill_context": None,
}
CORPUS_EXCLUSIONS = {
    "test_apply_registry": [
        "TestVocabulary.test_the_registry_speaks_only_modes_the_page_renders",
        "TestResolution.test_discord_precedence_copy_matches_intake_policy",
        "TestResolution.test_removed_noop_switches_are_absent_and_siblings_require_restart",
        "TestSecretsInsideListRecords.test_public_siblings_stay_readable",
        "TestSchemaDerivedFacts.test_populated_container_children_get_the_read_only_marker",
        "TestSchemaDerivedFacts.test_list_entry_paths_resolve_to_their_record_field",
        "TestSchemaDerivedFacts.test_credentials_in_list_entries_are_known_to_the_schema_walk",
        "TestEffectiveIsNeverGuessed.test_a_re_read_field_is_effective_immediately",
        "TestRevisionIsNotAnOracle.test_effective_revision_is_not_published_as_a_raw_boot_diff",
        "TestContainerSensitivity.test_empty_secret_containers_are_not_public_json_controls",
        "TestMetaPayload.test_health_vocabulary_matches_the_page",
        "TestPlainLanguageEffects.test_every_workspace_protected_config_path_publishes_restart_truth",
    ],
    "test_builtin_tool_policy": [
        "TestDispatchRejection.test_computer_native_dispatch_rejects_before_owner_lookup",
        "TestDispatchRejection.test_native_dispatch_rejects_before_owner_lookup",
        "TestDispatchRejection.test_background_special_cased_builtins_reject_before_effect",
        "TestDispatchRejection.test_executor_ungated_without_policy",
    ],
    "test_error_presentation": [
        "TestFormatUserFacingError.test_discord_http_exception_never_renders_body",
        "TestFailSafe.test_internal_failure_falls_back_to_type_name",
        "TestStructuredReason.test_controls_stripped_from_reason",
        "TestStructuredReason.test_mentions_neutralized_in_reason",
        "TestStructuredReason.test_format_chars_stripped_from_reason",
        "TestStructuredReason.test_html_reason_dropped_status_kept",
        "TestStructuredReason.test_non_int_status_rendered_safely",
        "TestSecretScrubbing.test_reason_phrase_is_scrubbed",
    ],
    "test_knowledge_import": [
        "TestLocalFileIntegrity.test_single_file_missing_and_outside_safe_roots",
        "TestEdgeCases.test_batch_result_dict_format",
    ],
    "test_skill_context": [
        "TestHelpers.test_set_skill_allowed_urls",
        "TestHostAndFile.test_run_on_host_uses_executor_with_requester",
        "TestHostAndFile.test_read_file",
        "TestMessaging.test_post_message_no_callback",
        "TestMessaging.test_post_file_no_callback",
        "TestDelegations.test_knowledge_and_history_disabled",
        "TestDelegations.test_knowledge_enabled",
        "TestDelegations.test_scheduler_disabled",
        "TestDelegations.test_scheduler_enabled",
        "TestDelegations.test_execute_tool",
    ],
}


class LocalEmbedder(EngineEmbedder):
    def __init__(self):
        state = _fixture.get()
        root = state.paths.cache_dir / "mock-bundled-model"
        root.mkdir(exist_ok=True)
        super().__init__(model_roots=(root,))


class BulkImporter(EngineImporter):
    def __init__(self, *args, **kwargs):
        state = _fixture.get()
        kwargs.setdefault("admitted_roots", tuple(getattr(state, "import_roots", ())))
        super().__init__(*args, **kwargs)
        if not hasattr(state, "importers"):
            state.importers = []
        state.importers.append(self)


class TemporaryDirectory(_tempfile.TemporaryDirectory):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("dir", _fixture.get().paths.cache_dir)
        super().__init__(*args, **kwargs)

    def __enter__(self):
        name = super().__enter__()
        state = _fixture.get()
        if not hasattr(state, "import_roots"):
            state.import_roots = []
        state.import_roots.append(Path(name).resolve())
        for importer in getattr(state, "importers", ()):
            importer._admitted_roots = tuple(state.import_roots)
        return name


class _TempfileFixture:
    TemporaryDirectory = TemporaryDirectory

    @staticmethod
    def mkstemp(*args, **kwargs):
        kwargs.setdefault("dir", _fixture.get().paths.cache_dir)
        return _tempfile.mkstemp(*args, **kwargs)


tempfile_fixture = _TempfileFixture()


def skill_context_fixture(*args, **kwargs):
    """Real owner-scoped host policy; HTTP transport remains original mocks."""
    from src.tools.skill_context import SkillContext

    executor = kwargs["tool_executor"]
    # Host listing uses persisted policy, never a mocked grant-all accessor.
    from src.permissions.host_access import HostAccessManager
    from src.permissions.persistence import write_private_atomic

    state = _fixture.get()
    policy = state.paths.config_dir / "skill-context-hosts.json"
    write_private_atomic(policy, json.dumps({"allowed_hosts": ["srv"], "default_host": "srv"}))
    executor._host_access = HostAccessManager(
        policy, available_hosts=["srv"], permission_manager=state.manager,
    )
    kwargs.setdefault("requester_id", state.authority.owner_id)
    kwargs.setdefault("allowed_urls", ("https://api.example.com",))
    return SkillContext(*args, **kwargs)


def _replacement(name, symbol, node):
    if isinstance(node, ast.Import) and name == "test_error_presentation":
        if any(alias.name == "discord" for alias in node.names):
            return []
    if isinstance(node, ast.Import) and name == "test_knowledge_import":
        if len(node.names) == 1 and node.names[0].name == "tempfile":
            return ast.parse(
                "from tests.desktop_adapters.foundation_cases "
                "import tempfile_fixture as tempfile"
            ).body
    if isinstance(node, ast.ImportFrom):
        if node.module in {"src.discord.tool_catalog", "src.discord.prompts"}:
            return None
        if node.module and node.module.startswith("src.discord"):
            return []
        if node.module == "src.web.api.observability":
            return []
        new = copy.deepcopy(node)
        if node.module == "src.config.schema":
            new.names = [alias for alias in new.names
                         if alias.name not in {"DiscordConfig", "WebConfig"}]
            if not new.names:
                return []
        elif node.module == "src.search.embedder":
            new.module = "tests.desktop_adapters.foundation_cases"
        elif node.module == "src.knowledge.importer":
            importer = [a for a in new.names if a.name == "BulkImporter"]
            if importer:
                other = [a for a in new.names if a.name != "BulkImporter"]
                imports = [ast.ImportFrom(
                    module="tests.desktop_adapters.foundation_cases", names=importer, level=0,
                )]
                if other:
                    imports.append(ast.ImportFrom(module=node.module, names=other, level=0))
                return imports
        elif node.module == "src.tools.skill_context":
            new.names = [a for a in new.names if a.name != "set_skill_allowed_urls"]
        elif node.module == "src.tools.executor":
            new.module = "tests.desktop_adapters.foundation_cases"
        elif node.module in {"src.tools", "src.tools.registry"}:
            for alias in new.names:
                if alias.name == "get_tool_definitions":
                    alias.name, alias.asname = (
                        "get_documentation_tool_definitions", "get_tool_definitions",
                    )
        if dump(new) != dump(node):
            return [new]
    if isinstance(node, ast.Assign) and symbol == "<module>" and name == "test_apply_registry":
        if any(isinstance(t, ast.Name) and t.id == "VOCABULARY" for t in node.targets):
            return ast.parse(
                "VOCABULARY = {'live_read', 'live_apply', 'live_for_new_work', "
                "'restart', 'dormant', 'activation_required', 'legacy_control'}"
            ).body
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Config":
        new = copy.deepcopy(node)
        new.keywords = [k for k in new.keywords if k.arg != "discord"]
        if dump(new) != dump(node):
            return new
    if (isinstance(node, ast.arguments) and name == "test_embedder_loading"
            and symbol.endswith("Model.__init__")):
        new = copy.deepcopy(node)
        new.kwarg = ast.arg(arg="bundle_kwargs")
        return new
    if isinstance(node, ast.Call) and name == "test_skill_context" and symbol == "_ctx":
        if isinstance(node.func, ast.Name) and node.func.id == "SkillContext":
            new = copy.deepcopy(node)
            new.func.id = "desktop_skill_context_fixture"
            return new
    return None


def transformations(name):
    original = ast.parse(frozen_source(f"tests/{name}.py"))
    rows = []
    # Parent nodes replaced as whole hunks; never also register their children.
    replaced = set()
    for symbol, node in nodes(original):
        if id(node) in replaced:
            continue
        replacement = _replacement(name, symbol, node)
        if replacement is None:
            continue
        replaced.update(id(n) for n in ast.walk(node))
        representation = (dump(replacement) if isinstance(replacement, ast.AST)
                          else json.dumps([dump(n) for n in replacement]))
        # arguments nodes are expression-shaped but not parseable by eval; adapt
        # the enclosing __init__ function as one setup hunk instead below.
        if isinstance(node, ast.arguments):
            continue
        rows.append({
            "symbol": symbol, "line": node.lineno,
            "before_sha256": hashlib.sha256(dump(node).encode()).hexdigest(),
            "operation": "foundation_setup",
            "kind": "expression" if isinstance(replacement, ast.expr) else "statement",
            "after_source": (ast.unparse(replacement) if isinstance(replacement, ast.AST)
                             else "\n".join(ast.unparse(n) for n in replacement)),
            "after_sha256": hashlib.sha256(representation.encode()).hexdigest(),
        })
    if name == "test_embedder_loading":
        for symbol, node in nodes(original):
            if isinstance(node, ast.FunctionDef) and symbol.endswith("Model.__init__"):
                new = copy.deepcopy(node)
                new.args.kwarg = ast.arg(arg="bundle_kwargs")
                rows.append({
                    "symbol": symbol, "line": node.lineno,
                    "before_sha256": hashlib.sha256(dump(node).encode()).hexdigest(),
                    "operation": "foundation_setup", "kind": "statement",
                    "after_source": ast.unparse(new),
                    "after_sha256": hashlib.sha256(json.dumps([dump(new)]).encode()).hexdigest(),
                })
    return rows


def adapted_tree(name):
    path = f"tests/{name}.py"
    original = ast.parse(frozen_source(path), filename=path)
    adapted = apply_transformations(path, original)
    verify_transform(path, original, adapted)
    return adapted


def selected_tree(name):
    tree = adapted_tree(name)
    selected = CORPUS_SELECTIONS[name]
    excluded = set(CORPUS_EXCLUSIONS.get(name, ()))
    body = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            methods = []
            for method in node.body:
                symbol = f"{node.name}.{getattr(method, 'name', '')}"
                if (isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and method.name.startswith("test_")):
                    if (symbol in excluded or selected is not None
                            and node.name not in selected and symbol not in selected):
                        continue
                methods.append(method)
            node.body = methods or [ast.Pass()]
            if any(isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and m.name.startswith("test_") for m in methods):
                body.append(node)
        elif (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
              and node.name.startswith("test_")):
            if node.name not in excluded and (selected is None or node.name in selected):
                body.append(node)
        else:
            body.append(node)
    tree.body = body
    return ast.fix_missing_locations(tree)


def export_suite(namespace, name):
    from scripts.maintenance.fixture_corpus import register_module

    module = ModuleType(f"desktop_foundation_{name}")
    module.__file__ = str(ROOT / f"tests/{name}.py")
    module.desktop_skill_context_fixture = skill_context_fixture
    exec(compile(selected_tree(name), module.__file__, "exec"), module.__dict__)
    register_module(namespace, module, prefix=name, full_class_name=True)
