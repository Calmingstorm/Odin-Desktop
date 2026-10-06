"""Exact frozen campaign setup over real profile-owner and Desktop services."""
# ruff: noqa: E501
from __future__ import annotations

import ast
import copy
import hashlib
from types import ModuleType

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, register_module
from src.config.schema import ToolsConfig
from src.desktop.services import _ReadyCatalog, _ReadyPolicy
from tests.desktop_adapters.tools_cases import SkillManager as SkillManager
from tests.desktop_adapters.tools_cases import ToolExecutor as OwnerExecutor
from tests.desktop_adapters.tools_cases import _fixture, owner_id
from tests.desktop_adapters.tools_cases import owner_fixture as owner_fixture


class ToolExecutor(OwnerExecutor):
    def __init__(self, *args, **kwargs):
        state = _fixture.get()
        config = kwargs.get("config")
        if config is None:
            config = ToolsConfig()
            kwargs["config"] = config
        workspace = state.paths.cache_dir.parent / "campaign-workspace"
        workspace.mkdir(mode=0o700, exist_ok=True)
        config.local_working_dir = str(workspace)
        super().__init__(*args, **kwargs)
        self.readiness.update({name: True for name in (
            "http_probe", "run_script", "manage_process", "memory_manage",
        )})


def _executor(tmp_path):
    from src.config.schema import ToolHost
    from src.tools.hosts import HostRegistry
    registry = HostRegistry(
        {"alpha": ToolHost(address="127.0.0.1"), "remote": ToolHost(address="192.0.2.10")},
        default_host="alpha", trust_dir=tmp_path / "trust")
    return ToolExecutor(config=ToolsConfig(), host_registry=registry)


class ToolCatalog(_ReadyCatalog):
    """Qualified fixture backends, with real catalog and policy filtering intact."""
    def __init__(self, **kwargs):
        get_config = kwargs["get_config"]
        from src.tools.registry import TOOLS
        policy = _ReadyPolicy(get_config, lambda: {item["name"]: True for item in TOOLS})
        super().__init__(policy=policy, **kwargs)


CORPUS_SELECTIONS = {'test_campaign_diagnostic_privacy': None,
                     'test_catalog_campaign': None,
                     'test_campaign_display_binding_coverage': None,
                     'test_campaign_web_final_coverage': None}
SUITES = {
    'test_campaign_diagnostic_privacy': '584ef3fca00a3f88171b0ce10eb4197d1f67972c9706964d140dd4bb9fb4eca6',
    'test_catalog_campaign': '694371b2f130d6cede610e69334dbef50ff3337ea18e752aa0f996fb52fe05f8',
    'test_campaign_display_binding_coverage': 'd74cddea7e7c2b4dcc56aa6b6329fd0cfb34dcea19ba03be5a4bcfcfe759d3a5',
    'test_campaign_web_final_coverage': '03afb8a2d7ef9988f4e824ea317d2d4529397bd5f89b6c9d7a09bbd5d2b5e575',
}
SUPPORT_SUITES = {
    'test_campaign_execution_outcomes': '535d5636bda63bc41cd4ecdffd2f1a3ab91a6ba65ae46724819de41113f87434',
    'test_smoke_run_bot': '08d911add7b63cd5f52a05c2eaf4a7c70824aa07a63dfaa6240decd06a847e83',
    'test_web_security_reliability': '210abc309c370eb3721a89d0f96b493023ba862de20d6b17c14af8bcdec8f0c2',
}
CORPUS_EXCLUSIONS = {
 'test_campaign_display_binding_coverage': [
  {'case': 'test_unknown_backing_credential_never_grants_browser_authority', 'reason': 'Removed bearer browser session authority.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_campaign_display_binding_coverage.py', 'source_sha256': 'd74cddea7e7c2b4dcc56aa6b6329fd0cfb34dcea19ba03be5a4bcfcfe759d3a5'}],
 'test_campaign_web_final_coverage': [
  {'case': 'test_discord_connection_admin_errors_do_not_expose_credentials', 'reason': 'Removed Discord connection HTTP route.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_campaign_web_final_coverage.py', 'source_sha256': '03afb8a2d7ef9988f4e824ea317d2d4529397bd5f89b6c9d7a09bbd5d2b5e575'},
  {'case': 'test_discord_connection_rejects_malformed_admin_requests_without_side_effects', 'reason': 'Removed Discord connection HTTP route.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_campaign_web_final_coverage.py', 'source_sha256': '03afb8a2d7ef9988f4e824ea317d2d4529397bd5f89b6c9d7a09bbd5d2b5e575'},
  {'case': 'test_discord_connection_requires_real_admin_identity_and_supervisor', 'reason': 'Removed Discord connection HTTP route.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_campaign_web_final_coverage.py', 'source_sha256': '03afb8a2d7ef9988f4e824ea317d2d4529397bd5f89b6c9d7a09bbd5d2b5e575'},
  {'case': 'test_schedule_unavailable_and_bad_json_are_safe', 'reason': 'Removed schedule HTTP route.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_campaign_web_final_coverage.py', 'source_sha256': '03afb8a2d7ef9988f4e824ea317d2d4529397bd5f89b6c9d7a09bbd5d2b5e575'},
  {'case': 'test_token_guard_accepts_async_bool_and_rejects_non_bool', 'reason': 'Removed bearer-token HTTP auth guard.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_campaign_web_final_coverage.py', 'source_sha256': '03afb8a2d7ef9988f4e824ea317d2d4529397bd5f89b6c9d7a09bbd5d2b5e575'},
  {'case': 'test_websocket_auth_inventory_and_revoked_chat_are_denied', 'reason': 'Removed WebSocket listener.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_campaign_web_final_coverage.py', 'source_sha256': '03afb8a2d7ef9988f4e824ea317d2d4529397bd5f89b6c9d7a09bbd5d2b5e575'},
  {'case': 'test_websocket_invalid_chat_inputs_do_not_call_bot', 'reason': 'Removed WebSocket listener.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_campaign_web_final_coverage.py', 'source_sha256': '03afb8a2d7ef9988f4e824ea317d2d4529397bd5f89b6c9d7a09bbd5d2b5e575'}],
 'test_campaign_diagnostic_privacy': [
  {'case': 'test_process_api_scrubs_legacy_and_spoofed_commands_and_output', 'reason': 'Removed web process inventory HTTP handler.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_campaign_diagnostic_privacy.py', 'source_sha256': '584ef3fca00a3f88171b0ce10eb4197d1f67972c9706964d140dd4bb9fb4eca6'},
  {'case': 'test_process_preview_scrubs_multiline_key_before_tail', 'reason': 'Removed web process inventory HTTP handler.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_campaign_diagnostic_privacy.py', 'source_sha256': '584ef3fca00a3f88171b0ce10eb4197d1f67972c9706964d140dd4bb9fb4eca6'}],
 'test_smoke_run_bot': [
  {'case': 'TestEntryPoint.test_client_module_imports', 'reason': 'Removed Discord OdinBot public facade.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_smoke_run_bot.py', 'source_sha256': '08d911add7b63cd5f52a05c2eaf4a7c70824aa07a63dfaa6240decd06a847e83'},
  {'case': 'TestOdinBotInit.test_bot_has_cog_list', 'reason': 'Removed Discord cog bootstrap.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_smoke_run_bot.py', 'source_sha256': '08d911add7b63cd5f52a05c2eaf4a7c70824aa07a63dfaa6240decd06a847e83'},
  {'case': 'TestOdinBotInit.test_instantiate_bot', 'reason': 'Removed Discord OdinBot construction.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_smoke_run_bot.py', 'source_sha256': '08d911add7b63cd5f52a05c2eaf4a7c70824aa07a63dfaa6240decd06a847e83'},
  {'case': 'TestOdinConfig.test_construct_default', 'reason': 'Removed Discord bootstrap token dataclass.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_smoke_run_bot.py', 'source_sha256': '08d911add7b63cd5f52a05c2eaf4a7c70824aa07a63dfaa6240decd06a847e83'},
  {'case': 'TestOdinConfig.test_construct_with_token', 'reason': 'Removed Discord token validation.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_smoke_run_bot.py', 'source_sha256': '08d911add7b63cd5f52a05c2eaf4a7c70824aa07a63dfaa6240decd06a847e83'},
  {'case': 'TestOdinConfig.test_validate_missing_token', 'reason': 'Removed Discord token validation.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_smoke_run_bot.py', 'source_sha256': '08d911add7b63cd5f52a05c2eaf4a7c70824aa07a63dfaa6240decd06a847e83'},
  {'case': 'TestPydanticConfig.test_config_has_all_round_fields', 'reason': 'Exact removed web and multi-user tier fields.', 'reviewer': 'Claude, review of step 8 part 4', 'source_path': 'tests/test_smoke_run_bot.py', 'source_sha256': '08d911add7b63cd5f52a05c2eaf4a7c70824aa07a63dfaa6240decd06a847e83'}],
}
SETUP_HUNKS = {
 'test_web_security_reliability': {
  (22, '779b4d9fef969a6a740fd85bf2ed5ff5f991c6847d5787c6c42845899064eb5b'): ('statement', ''),
  (25, '8f7eb0ae214cc6e6e174d83e695e61372dea88ff6bb13d60361b0126005ca814'): ('statement', 'from src.web.api_common import _is_sensitive_key, _redact_config'),
 },
 'test_campaign_display_binding_coverage': {
  (6, '054860dc42a1bd252d1a3591a38f1cea32f46d859bec8b609b5f5bc29fa9191b'): ('statement', 'from src.config.schema import Config'),
  (7, 'ea345a79fe87b960757d46e5abbbea68735e3a669046da945660c72d81991dea'): ('statement', ''),
  (9, '81561545434e8bd5d6a8f1339d662fea0b9e740c95618b1136547a4775069e02'): ('statement', ''),
 },
 'test_campaign_web_final_coverage': {
  (14, '4e9a92fe1461a2a686c9a22fa5bd56ef81cac812ea8851aeac3ae0796a6aea03'): ('statement', ''),
  (15, 'bef529167ef78a32cdf3ee41129ad8092f420a4b33dc5b210c808400914594d5'): ('statement', ''),
  (16, 'a0c8a3ee1fb55acca6867b117626b229375714519d5a79fddc907f96959d39cd'): ('statement', ''),
  (18, 'a6de7972e6d6b840bb418916da1168c122380083efccba3b9d7969e9a6e6b09c'): ('statement', ''),
 },
 'test_campaign_execution_outcomes': {
  (16, '48f7980224a8d0229e2354231c784e02b2c76847eb26eedfe01be6db2c9594dc'): ('statement', 'from tests.desktop_adapters.step8_6a_campaigns import ToolExecutor'),
  (20, 'e2ff33a6261375e7d38f782a0a8cabfa8cf284eb9d36863eac5a58aeee03bba0'): ('statement', 'from tests.desktop_adapters.step8_6a_campaigns import _executor'),
  (211, '9cf09d237a240651c8d9029c70bbe32057c9a4d2aa8931c232bc7e7047cdef7b'): ('statement', 'from src.tools.skill_manager import LoadedSkill\nfrom tests.desktop_adapters.step8_6a_campaigns import SkillManager'),
  (231, '4c7a319c9ee04845facd12e788a55f026629a9aa76e9f58ab7c919b9c9a1138e'): ('expression', "deliver_runtime_result(exe, raw, tool_name='fetch_url', tool_input={}, user_id=desktop_owner_id())"),
 },
 'test_catalog_campaign': {
  (6, '49785e3a823780b3c5e204689ddbd288081948b9b4215280ce977ea9084ff424'): ('statement', 'from tests.desktop_adapters.step8_6a_campaigns import ToolCatalog'),
  (12, '55872c5214bd2ee281cdb2d5265cc0bf4b59f6905e7648399e6aa5a53bf48b99'): ('expression', "Config(browser={'enabled': enabled}, search={'enabled': enabled})"),
  (23, '29b96388ae58ab27a946784f22ad3c0d78e926f363f03259f3aec796de8187b1'): ('expression', "Config(email={'enabled': True})"),
  (40, '6736a035ff66cbfb59bd31523d57759b9959c8fee0e4443c85572c7675975d0c'): ('expression', "Config(computer={'enabled': True}, tools={'disabled_tools': [name]})"),
 },
 'test_smoke_run_bot': {
  (74, 'ca75f5ca738ef39fb436bb7da28c02e96cb9aac7f7618bc6cfa9cd9c2e6dccec'): ('expression', 'Config()'),
  (93, '97724ff5d15cb07ad79e6692f4625f72e1e89709e344212c6b0b96fc1d8cb00e'): ('expression', 'Config()'),
  (100, '97724ff5d15cb07ad79e6692f4625f72e1e89709e344212c6b0b96fc1d8cb00e'): ('expression', 'Config()'),
 },
}
DEFERRED_CASES = {
    'test_campaign_execution_outcomes': {
        'test_dispatch_failure_is_durably_unknown_and_fenced':
        'The inherited helper admits a Discord-shaped turn; Desktop requires worker-scoped RequestService admission and its ledger key. Exact legacy helper assertions cannot run on the removed admission path.'
    },
    'test_smoke_run_bot': {
        'TestImportSweep.test_import':
        'Frozen mixed import parameter list includes removed src.discord.client; parameter list cannot be edited. Reviewer decision required to restore neutral parameters without silently deleting the removed parameter.'
    },
}
PARTIAL_CASES = {
 'test_web_security_reliability': {
  'test_redaction_covers_hmac_and_webhook_and_secret', 'test_is_sensitive_key_substring',
  'test_redaction_leaves_empty_values', 'test_operator_named_container_children_are_masked',
  'test_container_masking_keeps_shape', 'test_empty_container_values_are_left_alone',
  'test_blocked_fields_are_found_inside_lists',
  'test_container_masking_handles_lists_and_runaway_nesting',
  'test_blocked_field_scan_stops_at_a_depth_limit', 'test_mask_scan_stops_at_a_depth_limit',
  'test_the_redaction_mask_is_refused_as_input', 'test_metadata_url_blocks_metadata_ip',
  'test_metadata_url_allows_internal_and_public', 'test_is_url_blocked_still_blocks_private',
  'test_http_probe_blocks_metadata', 'test_http_probe_allows_internal_target',
  'test_http_probe_sinkholes_metadata_on_redirect', 'test_http_probe_no_sinkhole_when_not_following',
  'test_context_loader_tolerates_bad_encoding', 'test_context_loader_skips_oversized_file'},
}


def adapted_tree(name):
    path = f"tests/{name}.py"
    source = frozen_source(path)
    if hashlib.sha256(source).hexdigest() != (SUITES | SUPPORT_SUITES)[name]:
        raise ValueError("campaign frozen source identity changed")
    original = ast.parse(source)
    adapted = copy.deepcopy(original)
    seen = set()

    class ExactSetup(ast.NodeTransformer):
        def visit(self, node):
            key = (getattr(node, "lineno", None), hashlib.sha256(dump(node).encode()).hexdigest())
            if key not in SETUP_HUNKS.get(name, {}):
                return super().visit(node)
            if key in seen:
                raise ValueError("campaign setup matched twice")
            seen.add(key)
            replacement = SETUP_HUNKS[name][key]
            if replacement is None:
                return None
            mode, content = replacement
            if mode == "expression":
                return ast.copy_location(ast.parse(content, mode="eval").body, node)
            return [ast.copy_location(item, node) for item in ast.parse(content).body]

    adapted = ExactSetup().visit(adapted)
    ast.fix_missing_locations(adapted)
    if seen != set(SETUP_HUNKS.get(name, {})) or corpus(original) != corpus(adapted):
        raise ValueError("campaign assertion/signature/decorator/parameter/setup drift")
    return original, adapted


def _load(namespace, suites):
    pairs = []
    for name in suites:
        original, adapted = adapted_tree(name)
        executable = copy.deepcopy(adapted)
        excluded = {item["case"] for item in CORPUS_EXCLUSIONS.get(name, ())}
        excluded.update(DEFERRED_CASES.get(name, ()))
        executable.body = [node for node in executable.body if not (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in excluded)]
        if name in PARTIAL_CASES:
            executable.body = [node for node in executable.body if not (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and
                (getattr(node, 'name', '').startswith(('test_', 'Test'))) and
                node.name not in PARTIAL_CASES[name])]
        for node in executable.body:
            if isinstance(node, ast.ClassDef):
                node.body = [child for child in node.body if
                             f"{node.name}.{getattr(child, 'name', '')}" not in excluded]
                if not node.body:
                    node.body = [ast.copy_location(ast.Pass(), node)]
        ast.fix_missing_locations(executable)
        module = ModuleType(f"desktop_frozen_{name}")
        module.__file__ = f"tests/{name}.py"
        module.desktop_owner_id = owner_id
        exec(compile(executable, module.__file__, "exec"), module.__dict__)
        register_module(namespace, module, prefix=name,
                        excluded=[item['case'] for item in CORPUS_EXCLUSIONS.get(name, ())])
        pairs.append((original, adapted))
    return pairs


def load(namespace):
    """Only complete retained suites, never partial support for a deferred row."""
    return _load(namespace, SUITES)


def load_support(namespace):
    """Exact complete cases from deferred suites; not suite-restoration evidence."""
    return _load(namespace, SUPPORT_SUITES)


