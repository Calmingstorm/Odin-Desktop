"""Whole frozen provider suites bound to immutable bytes and exact case corpus."""
from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source

SUITE_NAMES = (
    "test_context_budget_activation", "test_context_density_calibration",
    "test_generation_duration_contract", "test_max_reasoning_effort",
    "test_mixed_agent_reasoning_contract", "test_predictive_presend",
    "test_preserved_reasoning_accounting", "test_provider_argument_acceptance",
    "test_provider_campaign_regressions", "test_provider_stream_acceptance",
    "test_reasoning_generation_records",
)
EVIDENCE = {}
CASE_MAP = {}
SUITES = {
    "test_context_budget_activation": (
        "3616a97cbd8aa2c22640614b934b5febfd90311d664c995128dc73bf8e736b6a"
    ),
    "test_context_density_calibration": (
        "6758f17d838dc83286e4974eaec41962d6db2aab5af30bbe2508d724aa9ed1b9"
    ),
    "test_generation_duration_contract": (
        "2b7575b89b1aaea5e230135f2dd557978951a4c52dce6d0dad4f426188c134e2"
    ),
    "test_max_reasoning_effort": (
        "b7fd583e10ab910c9523add50131032236a9563dc0ab7241764a997d73b03f5b"
    ),
    "test_mixed_agent_reasoning_contract": (
        "de80f566cf7be48ddd03d006b5ba68ce13286e1e01ca04af0c9d2a6873534330"
    ),
    "test_predictive_presend": "085ca193095b1b2d7a831495088eaa4bad4e25167bed1f02a2edde1a4e98f708",
    "test_preserved_reasoning_accounting": (
        "9f86bc04fdb9108e3ea4f1e91ab5adaccfb8c97267b17098bc083c2d2a0484bb"
    ),
    "test_provider_argument_acceptance": (
        "9a3183d8b67e55a346fc5945c9e2b65753d13de2911269c2b3d7e6089c711166"
    ),
    "test_provider_campaign_regressions": (
        "6a30d0463fba2d15cf2de86bce84c197b33473ad7c5150ac93add489a7d53448"
    ),
    "test_provider_stream_acceptance": (
        "b3b83f66584b7e8d197b2f4579be2ed21dcc03747a7ee9b02ebb03ca9ed214e3"
    ),
    "test_reasoning_generation_records": (
        "43b762f236d0b284426602c309f413eafd94f10bca1c0e757481005dd182c98c"
    ),
}
CORPUS_SELECTIONS = {
    "test_context_budget_activation": None,
    "test_context_density_calibration": None,
    "test_generation_duration_contract": None,
    "test_max_reasoning_effort": None,
    "test_mixed_agent_reasoning_contract": None,
    "test_predictive_presend": None,
    "test_preserved_reasoning_accounting": None,
    "test_provider_argument_acceptance": None,
    "test_provider_campaign_regressions": None,
    "test_provider_stream_acceptance": None,
    "test_reasoning_generation_records": None,
}
CORPUS_EXCLUSIONS = {
    "test_mixed_agent_reasoning_contract": [
        "test_codex_default_spawn_requires_model_selection"
    ],
}
RETIRED_CASES = {
    (
        "tests/test_mixed_agent_reasoning_contract.py::"
        "test_codex_default_spawn_requires_model_selection"
    ): {
        "reason": (
            "Exact whole-schema byte hash pins the removed Discord/channel description. The "
            "only frozen-to-current agents definition diff is Discord/channel to conversation "
            "wording; restoring these bytes would recreate a removed surface. Model-selection "
            "covered by real policy and engine tests."
        ),
        "reviewer": "Claude, review of step 8 part 4",
    },
}


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

        def visit_Call(self, node):
            self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == "Config":
                for keyword in list(node.keywords):
                    if keyword.arg == "discord":
                        if (
                            not isinstance(keyword.value, ast.Dict)
                            or len(keyword.value.keys) != 1
                            or keyword.value.keys[0].value != "token"
                        ):
                            raise AssertionError("Unreviewed obsolete Config fixture")
                        node.keywords.remove(keyword)
                        edits.append((node.lineno, "remove_inert_transport_config"))
            if (
                stem == "test_provider_campaign_regressions"
                and ast.unparse(node.func) == "LLMGateway"
            ):
                node.keywords.append(
                    ast.keyword(arg="settings_config", value=ast.Name(id="config", ctx=ast.Load()))
                )
                edits.append((node.lineno, "real_profile_candidate_config"))
            return node

        def visit_ImportFrom(self, node):
            if node.module in {
                "tests.characterization.test_autonomous_loop",
                "tests.characterization.test_chat_tool_loop",
            }:
                node.module = "tests.desktop_adapters.lane6_providers_engine"
                edits.append((node.lineno, "canonical_request_engine_fixture"))
            elif node.module == "tests.test_typing_resilience":
                node.module = "tests.desktop_adapters.lane6_providers_timing"
                edits.append((node.lineno, "neutral_generation_fixture"))
            elif node.module == "tests.fakes" and any(
                a.name == "make_bot" for a in node.names
            ):
                if len(node.names) != 1:
                    raise AssertionError("Unreviewed bot helper import")
                node.module = "tests.desktop_adapters.lane6_providers_engine"
                edits.append((node.lineno, "canonical_engine_boot_fixture"))
            elif node.module == "src.tools.registry":
                for alias in node.names:
                    if alias.name == "get_tool_definitions":
                        alias.name, alias.asname = (
                            "get_documentation_tool_definitions",
                            "get_tool_definitions",
                        )
                        edits.append((node.lineno, "documentation_schema_not_runtime_admission"))
            if node.module == "src.discord.llm_gateway":
                for alias in node.names:
                    if alias.name == "LLMGateway":
                        alias.name, alias.asname = "gateway", "LLMGateway"
                        edits.append((node.lineno, "canonical_profile_provider_owner"))
                        retained = [a for a in node.names if a is not alias]
                        swapped = ast.ImportFrom(
                            module="tests.desktop_adapters.lane6_providers_owner",
                            names=[alias], level=0)
                        if retained:
                            return [ast.copy_location(swapped, node), ast.copy_location(
                                ast.ImportFrom(node.module, retained, 0), node)]
                        return ast.copy_location(swapped, node)
            return node

        def visit_Constant(self, node):
            if node.value == "src.discord.llm_gateway.OpenAICompatibleClient":
                edits.append((node.lineno, "canonical_transport_constructor_fault_seam"))
                return ast.copy_location(
                    ast.Constant(value="src.desktop.providers.OpenAICompatibleClient"), node
                )
            return node

    adapted = ast.fix_missing_locations(Setup().visit(copy.deepcopy(original)))
    if corpus(adapted) != corpus(original):
        raise AssertionError("Frozen assertion/signature/decorator/parameter corpus changed")
    EVIDENCE[path] = {
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
        "whole_suite": not CORPUS_EXCLUSIONS.get(stem),
        "exact_corpus": corpus(original), "setup_edits": edits,
    }
    return adapted


def register_module(namespace, stem):
    tree = adapted_tree(stem)
    module = ModuleType(f"lane6_providers_{stem}")
    module.__file__ = str(ROOT / f"tests/{stem}.py")
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    for node in tree.body:
        name = getattr(node, "name", "")
        if name in CORPUS_EXCLUSIONS.get(stem, []):
            continue
        if name.startswith("test_"):
            target = f"test_lane6_providers_{stem}_{name[5:]}"
            namespace[target] = getattr(module, name)
            CASE_MAP[f"tests/{stem}.py::{name}"] = target
        elif name.startswith("Test"):
            target = f"Test_lane6_providers_{stem}_{name[4:]}"
            namespace[target] = getattr(module, name)
            for child in node.body:
                if getattr(child, "name", "").startswith("test_"):
                    CASE_MAP[f"tests/{stem}.py::{name}::{child.name}"] = f"{target}::{child.name}"


def load(namespace):
    for stem in SUITE_NAMES:
        register_module(namespace, stem)
