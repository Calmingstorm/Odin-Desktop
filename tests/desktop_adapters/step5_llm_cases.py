"""WHOLE frozen suites, exact assertion/decorator/signature/parameter AST."""
from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source

SUITE_NAMES = ("test_campaign_openrouter_coverage", "test_openrouter_admin_boundaries",
              "test_web_api_new_endpoints")
SUITES = {
    "test_campaign_openrouter_coverage":
        "824f4e1c6e9b969a12b2a3a264215271f5d4f5ad9b9af94956bffa1a22c36974",
    "test_openrouter_admin_boundaries":
        "8c40036891cba7438efd85f569aa31be8cfcce668c17e9887ab9350f97552e17",
    "test_web_api_new_endpoints":
        "7fe8c3706f7d9c08ae7b2412af59007abb77a7dfd88348e15e605b18d439239f",
}
EVIDENCE = {}
CASE_MAP = {}
BRIDGE = "tests.desktop_adapters.step5_llm_bridge"


def adapted_tree(stem):
    path = f"tests/{stem}.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != SUITES[stem]:
        raise AssertionError("Pinned immutable suite bytes changed")
    original = ast.parse(source, filename=path)
    edits = []

    class Setup(ast.NodeTransformer):
        def visit_Assert(self, node):
            return node

        def visit_ImportFrom(self, node):
            if node.module == "tests.test_web_api_llm_admin":
                edits.append((node.lineno, "real_profile_fixture_import"))
                node.module = BRIDGE
            elif node.module == "src.web.api.llm_admin":
                bridges = [item for item in node.names if item.name.startswith("register_")]
                retained = [item for item in node.names if item not in bridges]
                if bridges:
                    edits.append((node.lineno, "named_method_route_markers"))
                    result = [ast.copy_location(ast.ImportFrom(
                        module=BRIDGE, names=bridges, level=0), node)]
                    if retained:
                        result.append(ast.copy_location(ast.ImportFrom(
                            module=node.module, names=retained, level=0), node))
                    return result
            elif node.module == "src.web.api":
                if [item.name for item in node.names] != ["create_api_routes"]:
                    raise AssertionError("Unreviewed API import")
                edits.append((node.lineno, "removed_obsolete_route_factory_import"))
                return None
            return node

        def visit_FunctionDef(self, node):
            if stem == "test_web_api_new_endpoints" and node.name == "_make_bot":
                edits.append((node.lineno, "real_settings_provider_fixture"))
                return ast.copy_location(ast.parse(
                    f"from {BRIDGE} import _make_bot").body[0], node)
            return self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            if stem == "test_web_api_new_endpoints" and node.name == "_client":
                edits.append((node.lineno, "test_only_named_method_bridge"))
                return ast.copy_location(ast.parse(
                    f"from {BRIDGE} import _client").body[0], node)
            return self.generic_visit(node)

        def visit_Constant(self, node):
            if node.value == "src.web.api.llm_admin.persist_config_paths_locked":
                edits.append((node.lineno, "persistence_fault_probe_import"))
                return ast.copy_location(ast.Constant(
                    value=f"{BRIDGE}.persist_config_paths_locked"), node)
            return node

        def visit_Call(self, node):
            self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == "Config":
                for keyword in list(node.keywords):
                    if keyword.arg == "discord":
                        if (not isinstance(keyword.value, ast.Dict)
                                or len(keyword.value.keys) != 1
                                or keyword.value.keys[0].value != "token"):
                            raise AssertionError("Unreviewed Config fixture")
                        node.keywords.remove(keyword)
                        edits.append((node.lineno, "remove_inert_transport_config"))
            return node

        def visit_Assign(self, node):
            self.generic_visit(node)
            value = node.value
            targets = [ast.unparse(target) for target in node.targets]
            if targets == ["provider.provider_name"]:
                edits.append((node.lineno, "concrete_transport_provider_name"))
                node.targets[0].attr = "_provider_name"
            for attribute, kind in (("codex_client", "codex"), ("ollama_client", "ollama"),
                                    ("compatible_client", "compat")):
                if (targets == [f"bot.llm_gateway.{attribute}"]
                        and isinstance(value, ast.Call)
                        and isinstance(value.func, ast.Name)
                        and value.func.id in {"object", "SimpleNamespace"}):
                    edits.append((node.lineno, "concrete_unopened_provider_transport"))
                    node.value = ast.parse(f'bot.client("{kind}")', mode="eval").body
            if (isinstance(value, ast.Attribute) and value.attr == "openai_compatible"
                    and ast.unparse(value.value) == "bot.config"):
                edits.append((node.lineno, "live_profile_section_pointer"))
                node.value = ast.parse('bot.section("openai_compatible")', mode="eval").body
            if any(ast.unparse(target) == "bot.llm_gateway.active_client"
                   for target in node.targets):
                if not isinstance(value, ast.Constant) or value.value is not None:
                    raise AssertionError("Unreviewed explicit serving-client fixture")
                edits.append((node.lineno, "remove_obsolete_derived_property_assignment"))
                return None
            return node

    adapted = Setup().visit(copy.deepcopy(original))
    ast.fix_missing_locations(adapted)
    if corpus(adapted) != corpus(original):
        raise AssertionError("Full frozen assertion/signature/decorator/parameter AST changed")
    EVIDENCE[path] = {"source_sha256": hashlib.sha256(source).hexdigest(),
                     "corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
                     "whole_suite": True, "exact_corpus": corpus(original), "setup_edits": edits}
    return adapted


def register_module(namespace, stem):
    tree = adapted_tree(stem)
    module = ModuleType(f"desktop_step5_{stem}")
    module.__file__ = str(ROOT / f"tests/{stem}.py")
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    for node in tree.body:
        name = getattr(node, "name", "")
        if name.startswith("test_"):
            target = f"test_step5_{stem}_{name[5:]}"
            namespace[target] = getattr(module, name)
            CASE_MAP[f"tests/{stem}.py::{name}"] = target
        elif name.startswith("Test"):
            target = f"TestStep5_{stem}_{name[4:]}"
            namespace[target] = getattr(module, name)
            for child in node.body:
                if getattr(child, "name", "").startswith("test_"):
                    CASE_MAP[f"tests/{stem}.py::{name}::{child.name}"] = f"{target}::{child.name}"
        elif any(isinstance(d, ast.Call) and ast.unparse(d.func) == "pytest.fixture"
                 for d in getattr(node, "decorator_list", [])):
            namespace[f"fixture_{stem}_{name}"] = getattr(module, name)


def load(namespace):
    for stem in SUITE_NAMES:
        register_module(namespace, stem)
