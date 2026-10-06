"""Frozen whole-suite runtime/health corpus with explicit case dispositions."""
# ruff: noqa: E501
from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import ROOT, corpus, frozen_source

SUITES = {
    "test_config_liveness_wiring": "87127ab087e9d0b7df63d61529227b3495b1cf3bc18a00fee8cb82de05457db9",
    "test_graceful_shutdown": "9ce9bf0f2021d3377fdf178e7afe9aee655026d29fb083d60496de7cd03fb5ea",
    "test_health_checker": "ddd7a689876cae2c1b25a5ad9710c1facf6f2445509f734bdeae27f3722d893f",
    "test_health_checker_paths": "cf90cead05a53a9c4701fa9b84e20b6ef6fc6fef77d133565538255ed16d5b40",
    "test_process_api_provenance": "a6d0fdd4dd939d26c9ddd375698dc81da3603d0ee72071d4dda1a50aa44273b8",
    "test_process_command_visibility": "b433e3936ba4c20e14f5dadc2d97ea50a19fd9db5fe743e222697ab13e1917b2",
}
REVIEWER = "Claude, review of step 8 part 4"
EVIDENCE = {}
CASE_MAP = {}
DISPOSITIONS = {}
CORPUS_SELECTIONS = {
    "test_config_liveness_wiring": None,
    "test_graceful_shutdown": None,
    "test_health_checker": None,
    "test_health_checker_paths": None,
    "test_process_api_provenance": None,
    "test_process_command_visibility": None,
}
CORPUS_EXCLUSIONS = {
    "test_config_liveness_wiring": [
        "TestHealthServerBacklink.test_set_bot_backlinks_the_server",
        "TestHealthServerBacklink.test_backlink_happens_even_when_the_web_ui_is_disabled",
        "TestHealthServerBacklink.test_stop_is_idempotent",
        "TestHealthServerBacklink.test_failed_cleanup_stays_retryable",
    ],
    "test_graceful_shutdown": [
        "TestOdinBotClose.test_close_no_components",
        "TestOdinBotClose.test_close_stops_health_server",
        "TestOdinBotClose.test_close_all_components",
    ],
    "test_health_checker": [
        "TestCheckDiscord.test_online", "TestCheckDiscord.test_not_ready",
        "TestCheckDiscord.test_multiple_guilds", "TestCheckDiscord.test_exception",
        "TestCheckAll.test_has_all_component_names", "TestCheckerList.test_checker_names",
        "TestExports.test_health_init_exports",
        "TestHealthAPI.test_health_components_has_all_names",
        "TestEdgeCases.test_knowledge_none_member_count",
    ],
}


class EngineFixture:
    """Legacy setup attribute names delegate to actual engine dependency owners."""
    def __init__(self):
        from tests.desktop_adapters.lane6_health_learning import GRAPH
        object.__setattr__(self, "graph", GRAPH.get())

    def __getattr__(self, name):
        aliases = {"knowledge": "knowledge_store"}
        if name == "config":
            return self.graph.config_holder.config
        return getattr(self.graph.engine.deps, aliases.get(name, name))

    def __setattr__(self, name, value):
        if name == "config":
            self.graph.config_holder.config = value
        else:
            if name == "sessions":
                value.save = value.save_all
            elif name == "scheduler":
                value._task = None
            setattr(self.graph.engine.deps, {"knowledge": "knowledge_store"}.get(name, name), value)

    async def shutdown_application(self):
        await self.graph.requests.close()
        await self.graph.engine.close()


def make_bot():
    return EngineFixture()


async def shutdown_services(supplied):
    from tests.desktop_adapters.lane6_health_learning import GRAPH

    graph = GRAPH.get()
    components = getattr(supplied, "components", None)
    media = getattr(components, "media_tools", None)
    if media is not None:
        graph.engine.deps.native_tools.owners["media"] = media
    for name in ("usage_rollup", "codex_quota_check"):
        value = getattr(supplied, name, None)
        if value is not None:
            setattr(graph.engine.deps.runtime_context, name, value)
    await graph.requests.close()
    await graph.engine.close()


def create_api_routes(bot):
    return [("health.get", bot)]


class HealthClient:
    """Socket-free historical spelling forwards only to RecordsService.health.get."""
    __test__ = False

    def __init__(self, server):
        self.app = server.app

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, path):
        from src.desktop.records import RecordsService
        from tests.desktop_adapters.lane6_health_learning import GRAPH
        from tests.desktop_adapters.step5_observability_http import Response

        if path != "/api/health/components":
            raise AssertionError("Unadmitted legacy fixture path")
        method, bot = self.app.router.routes[0]
        bot.delivery_readiness = True
        bot.mcp_manager = None
        from src.health.checker import check_all
        result = await RecordsService(GRAPH.get().paths, health=lambda: check_all(bot)).handle(method, {})
        return Response(result)


def _live_recovery_policy_source(bot):
    graph = bot.graph if isinstance(bot, EngineFixture) else make_bot().graph
    graph.config_holder.config = bot.config
    original = graph.engine.deps.llm_gateway._recovery_policy_source

    def read():
        graph.config_holder.config = bot.config
        return original()

    return read


def disposition(stem, case):
    if stem == "test_config_liveness_wiring":
        if case.startswith("TestHealthServerBacklink."):
            return "retired", "Removed HTTP HealthServer/WebUI listener backlink/runner cleanup."
        if case == "TestLiveAgentAdmissionSource.test_catalog_limits_share_live_admission_source":
            return "proposed", "Exact assertion expects legacy Max N/channel wording. Desktop catalog enforces and renders Max N/conversation. Dynamic admission still survives; wording substitution inside assertions needs reviewer approval."
        return "restored", "Live rebound config through canonical engine dependency providers."
    if stem == "test_health_checker":
        if case.startswith("TestCheckDiscord.") or case == "TestEdgeCases.test_knowledge_none_member_count":
            return "retired", "Removed Discord readiness/guild population probe."
        if case in {"TestCheckAll.test_has_all_component_names", "TestCheckerList.test_checker_names"}:
            return "retired", "Exact Discord checker/name inventory replaced by authenticated delivery."
        if case == "TestExports.test_health_init_exports":
            return "retired", "Exports removed listener HealthServer."
        if case == "TestHealthAPI.test_health_components_has_all_names":
            return "retired", "Exact route payload inventory asserts removed Discord component name."
    if stem == "test_graceful_shutdown":
        if case == "TestOdinBotClose.test_close_all_components":
            return "proposed", "Mixed exact teardown order asserts removed HTTP health listener and retained component cleanup. Reviewer decision required; retained cleanup is not retired."
        if case in {"TestOdinBotClose.test_close_stops_health_server", "TestOdinBotClose.test_close_no_components"}:
            return "retired", "Exact case asserts removed transport superclass close and/or removed HTTP health listener in teardown ordering."
        if case in {"TestOdinBotClose.test_close_stops_loop_manager", "TestOdinBotClose.test_close_stops_scheduler", "TestOdinBotClose.test_close_shuts_down_process_registry", "TestOdinBotClose.test_close_does_not_create_unused_process_registry", "TestOdinBotClose.test_close_tolerates_missing_tool_executor", "TestOdinBotClose.test_close_closes_knowledge_store", "TestOdinBotClose.test_close_saves_sessions"}:
            return "restored", "Canonical EngineServices.close ownership; legacy session save_all setup aliases actual save seam."
        if case.startswith("TestOdinBotClose."):
            return "proposed", "Frozen component-error case requires session persistence after unresolved producer shutdown errors. Canonical EngineServices.close deliberately vetoes persistence beneath unsettled producers. Reviewer decision required; do not weaken cleanup barriers."
        if case == "TestProcessRegistryShutdown.test_shutdown_services_closes_image_backend":
            return "proposed", "Image backend release omission fixed on canonical engine; frozen case additionally requires backend close failure swallowed, conflicting with truthful cleanup propagation. Reviewer decision required."
        if case == "TestUnprovenCleanupEscalation.test_wiring_reports_cleanup_error_without_raising":
            return "proposed", "Frozen case requires logging/swallowing unproven process cleanup; canonical Desktop deliberately propagates resource cleanup barriers. Reviewer disposition required; do not weaken barriers."
        if case in {"test_shutdown_stops_usage_rollup", "test_shutdown_stops_codex_quota_check"}:
            return "restored", "Canonical EngineServices releases actual optional runtime quota/usage owners; exposed omission fixed."
        if case == "test_shutdown_usage_failure_is_nonfatal":
            return "proposed", "Frozen case requires telemetry stop errors swallowed and legacy log spelling; canonical engine keeps cleanup error outcome truthful. Reviewer decision required."
    if stem == "test_process_api_provenance" and case != "test_real_remote_supervisor_shell_identity_is_sh":
        return "deferred", "WorkService now exposes scrubbed command, effective_shell, termination_reason and manager_record for admitted work. Frozen cases additionally require ownerless restored/legacy and manually inserted record provenance; that admission-preserving projection is absent. Do not invent ownership or use raw registry entries as a management substitute."
    if stem == "test_process_command_visibility":
        return "deferred", "WorkService exposes admitted scrubbed command and immutable work lookup; schema absence is not the blocker. A setup-only RequestService-bound ProcessRegistry/WorkService bridge preserved the full corpus but 6/16 expanded cases failed the exact safe_text(command) equality: native scrub_output_secrets rendering differs for refresh-token JSON, Authorization bearer and PEM fixtures. No scrubber substitution or assertion rewrite; exact operator-copy redaction parity needs review."
    return "restored", "Actual retained health/storage/process implementation, exact frozen corpus."


class Setup(ast.NodeTransformer):
    def __init__(self, stem):
        self.stem, self.edits = stem, []

    def visit_Assert(self, node):
        return node

    def visit_ImportFrom(self, node):
        if self.stem == "test_health_checker" and node.module == "src.web.api":
            node.module = __name__
            return node
        if self.stem == "test_health_checker" and node.module == "aiohttp":
            node.module = "tests.desktop_adapters.step5_observability_http"
            return node
        if self.stem == "test_health_checker" and node.module == "aiohttp.test_utils":
            return [ast.copy_location(ast.ImportFrom(module=__name__, names=[ast.alias(name="HealthClient", asname="TestClient")], level=0), node),
                    ast.copy_location(ast.ImportFrom(module="tests.desktop_adapters.step5_observability_http", names=[ast.alias(name="TestServer")], level=0), node)]
        if self.stem == "test_config_liveness_wiring" and node.module in {"src.discord.wiring", "tests.fakes"}:
            node.module = __name__
            return node
        if self.stem == "test_graceful_shutdown" and node.module == "src.discord.wiring":
            node.module = __name__
            return node
        if node.module == "src.health.checker":
            node.names = [n for n in node.names if n.name != "check_discord"]
            for name in node.names:
                if name.name == "check_kimi":
                    name.name, name.asname = "check_compatible", "check_kimi"
                    self.edits.append((node.lineno, "canonical_compatible_probe_alias"))
        if node.module in {"src.discord.client", "src.discord.wiring", "src.web.api.agents_loops"}:
            self.edits.append((node.lineno, "remove_unavailable_setup_import"))
            return None
        return node

    def visit_FunctionDef(self, node):
        if self.stem == "test_graceful_shutdown" and node.name == "_make_bot":
            node.body = ast.parse("return make_bot()").body
            self.edits.append((node.lineno, "canonical_engine_fixture"))
        if self.stem == "test_health_checker" and node.name == "_make_healthy_bot":
            for index, child in enumerate(node.body):
                if isinstance(child, ast.Return):
                    node.body.insert(index, ast.parse("bot.delivery_readiness = True").body[0])
                    self.edits.append((node.lineno, "observed_delivery_ready_fixture"))
                    break
        if self.stem == "test_health_checker_paths" and node.name == "_gw":
            node.body = ast.parse("if 'kimi_client' in kw:\n kw['compatible_client'] = kw.pop('kimi_client')\nreturn SimpleNamespace(llm_gateway=SimpleNamespace(**kw))").body
            self.edits.append((node.lineno, "canonical_compatible_client_slot"))
        return self.generic_visit(node)

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "Config":
            node.keywords = [keyword for keyword in node.keywords if keyword.arg != "discord"]
        return node


def adapted_tree(stem):
    path = f"tests/{stem}.py"
    source = frozen_source(path)
    digest = hashlib.sha256(source).hexdigest()
    if digest != SUITES[stem]:
        raise AssertionError("Frozen suite bytes changed")
    original = ast.parse(source, filename=path)
    setup = Setup(stem)
    adapted = setup.visit(copy.deepcopy(original))
    ast.fix_missing_locations(adapted)
    if corpus(original) != corpus(adapted):
        raise AssertionError("Frozen assertion/signature/decorator/parameter corpus changed")
    EVIDENCE[path] = {"source_sha256": digest, "whole_suite": True,
                      "corpus_sha256": hashlib.sha256(repr(corpus(original)).encode()).hexdigest(),
                      "exact_corpus": corpus(original), "setup_edits": setup.edits}
    return adapted


def register_module(namespace, stem):
    tree = adapted_tree(stem)
    original_tree = ast.parse(frozen_source(f"tests/{stem}.py"))
    source_cases = {}
    for original_node in original_tree.body:
        if isinstance(original_node, ast.ClassDef):
            for child in original_node.body:
                if getattr(child, "name", "").startswith("test_"):
                    source_cases[f"{original_node.name}::{child.name}"] = child
        elif getattr(original_node, "name", "").startswith("test_"):
            source_cases[original_node.name] = original_node
    module = ModuleType(f"lane6_health_{stem}")
    module.__file__ = str(ROOT / f"tests/{stem}.py")
    module.make_bot = make_bot
    exec(compile(tree, module.__file__, "exec"), module.__dict__)
    for node in tree.body:
        name = getattr(node, "name", "")
        if isinstance(node, ast.ClassDef) and name.startswith("Test"):
            target = f"TestLane6Health_{stem}_{name[4:]}"
            cls = getattr(module, name)
            survivors = []
            for child in node.body:
                case = getattr(child, "name", "")
                if case.startswith("test_"):
                    original = f"tests/{stem}.py::{name}::{case}"
                    status, reason = disposition(stem, f"{name}.{case}")
                    CASE_MAP[original] = f"{target}::{case}"
                    DISPOSITIONS[original] = {"status": status, "reason": reason}
                    DISPOSITIONS[original]["case_sha256"] = hashlib.sha256(ast.dump(source_cases[f"{name}::{case}"], include_attributes=False).encode()).hexdigest()
                    if status == "restored":
                        survivors.append(case)
                    else:
                        delattr(cls, case)
            if survivors:
                namespace[target] = cls
        elif name.startswith("test_"):
            target = f"test_lane6_health_{stem}_{name[5:]}"
            status, reason = disposition(stem, name)
            fn = getattr(module, name)
            if status == "restored":
                namespace[target] = fn
            original = f"tests/{stem}.py::{name}"
            CASE_MAP[original] = target
            DISPOSITIONS[original] = {"status": status, "reason": reason}
            DISPOSITIONS[original]["case_sha256"] = hashlib.sha256(ast.dump(source_cases[name], include_attributes=False).encode()).hexdigest()


def load(namespace):
    for stem in SUITES:
        register_module(namespace, stem)
