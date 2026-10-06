#!/usr/bin/env python3
"""Offline Phase 2 suite accounting. No engine or inherited test is imported.

This checks immutable membership, bytes, classifications and executable whole-
suite associations. It is not runtime passing evidence or feature qualification.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import subprocess
import tarfile
from collections import Counter
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "cd7530906e9cfa10a0fa900247d7ce2a8bb33e25"
SOURCE_MAIN = "7d919f0c32402e28179e019dee948be8ed3f5407"
ARCHIVE_SHA256 = "845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0"
POPULATION_SHA256 = "a4bcf41b3ee1660c991df903cccbda1583497c2ec01cea6bb2be6425ba43888f"
HISTORICAL_PLAN_SHA256 = "75a862f004d6780baa11fd85c509b0ef5ddfa7a5c9ad3d9f734df4c1abe2ff9f"
HISTORICAL_QUALIFICATION_SHA256 = "0e45810c0574b26a79d23842a65fe02f0d1ec0ca6d8c9691ece0680536baff02"
MERGED_MAIN = "566b7954911154ed36d9e5e751c2db9029e262e2"
MERGED_QUALIFICATION_SHA256 = "89094765dc426da5fa6844efb8d54273d94d1b79dd54e62e0207d315bfc79956"
RETIREMENT_REVIEWER = "Claude, review of #26"
RETIRABLE_SUITES = {
    "tests/test_client.py", "tests/test_command_reconciliation.py",
    "tests/test_gateway_transition_regressions.py", "tests/test_rate_limiter.py",
    "tests/test_websocket_production_stack.py",
}
RETIREMENT_REASONS = {
    "tests/test_client.py": (
        "Retired: Odin's Discord client (class name, intents, prefix, reaction extension). "
        "Report paging is step 6's reports.py, with its own tests."),
    "tests/test_command_reconciliation.py": "Retired: Discord slash-command publication.",
    "tests/test_gateway_transition_regressions.py": (
        "Retired: Discord gateway ready/resume/disconnect races."),
    "tests/test_rate_limiter.py": (
        "Retired: it covers only Odin's /api/ routes (src/health/server.py:721-753), "
        "and the desktop has no management listener. Odin's incoming webhooks (/webhook/*) "
        "aren't rate-limited, so step 7's listener inherits nothing here."),
    "tests/test_websocket_production_stack.py": (
        "Retired: the WebSocket stack. The IPC transport has no URL to carry a credential, "
        "and step 1's tests prove its handshake authenticates before any method runs."),
}
WORK_ORDER = "docs/work/phase-2-desktop-engine.md"
PR35_REVIEWER = "Claude, review of #35"
PR35_ROUND2_REVIEWER = "Claude, review of #35, round 2"
PR35_ROUND2_CASE_REASONS = {
    "tests/characterization/test_executor_dispatch_parity.py": {
        "TestMiddlewarePins.test_contextvar_isolation_concurrent":
        "multi-user caller identities removed; one canonical owner",
        "TestPatchSeam.test_memory_manage_receives_user_id_kwarg":
        "multi-user caller identities removed; one canonical owner",
    },
    "tests/test_campaign_cli_coverage.py": {
        "test_piped_prompt_and_environment_build_real_authenticated_request":
        "HTTP API client replaced by the authenticated local IPC client",
        "test_transport_failure_is_nonzero_even_in_json_mode":
        "HTTP API client replaced by the authenticated local IPC client",
    },
    "tests/test_chat_steering_parity.py": {
        "test_unsteered_native_batch_protocol_permissions_and_resume_parity":
        "Tier-denial prose removed: both fresh and run-resumed-rebind goldens "
        "require Permission denied: blocked for the canonical owner; desktop "
        "has no per-tool tier ACL. Retire this case, not individual assertions.",
    },
}
# Deliberately separate from #26: neither review grants blanket retirement.
PR35_RETIREMENTS = {
    "tests/characterization/test_delivery.py": (
        3, "Discord chunked reply, file transport and retry delivery"),
    "tests/characterization/test_intake_gating.py": (
        3, "Discord guild/channel intake, allowlists and multi-bot origin gating"),
    "tests/characterization/test_pipeline_persistence.py": (
        4, "Discord pipeline routing, thread inheritance and reply/file handoff"),
    "tests/test_campaign_attachment_intake_coverage.py": (3, "Discord attachment intake"),
    "tests/test_campaign_discord_attachments.py": (3, "Discord attachment intake and delivery"),
    "tests/test_campaign_discord_intake.py": (3, "Discord message intake"),
    "tests/test_campaign_discord_resume.py": (4, "Discord resume intake"),
    "tests/test_channel_privacy_campaign.py": (3, "Discord channel privacy and allowlists"),
    "tests/test_channel_logger.py": (2, "Discord guild/DM channel logging"),
    "tests/test_chat_session.py": (3, "HTTP chat session and web/API identities"),
    "tests/test_chat_steering_admission.py": (4, "Discord steering admission"),
    "tests/test_chat_steering_notifications.py": (4, "Discord steering notifications"),
    "tests/test_delivery_file_retries.py": (3, "Discord file delivery retries"),
    "tests/test_delivery_status.py": (3, "Discord delivery and typing status"),
    "tests/test_execute_api.py": (3, "HTTP execute API routes and identities"),
    "tests/test_intake_pipeline.py": (3, "Discord message intake pipeline"),
    "tests/test_native_channel_ops.py": (3, "Discord channel operations"),
    "tests/test_sessions_review_regressions.py": (
        3, "Discord/web session identities and allowlists"),
    "tests/test_stop_command.py": (4, "Discord slash-command stop intake"),
    "tests/test_typing_resilience.py": (3, "Discord typing and presence"),
    "tests/test_web_chat.py": (3, "HTTP web chat routes and sessions"),
}
PR35_RETIREMENT_REASONS = {
    path: f"Retired: {surface}; removed by Desktop design (group A, review of #35)."
    for path, (_, surface) in PR35_RETIREMENTS.items()
}
PR35_CASE_REASONS = {
    "tests/test_resume_admission.py": {
        "TestExplicitResume.test_fetch_permission_failure_is_truthful_and_keeps_turn_resumable":
        "Removed Discord fetch-permission denial surface: injects Discord Forbidden 50013 "
        "and asserts Discord denial prose. Desktop transcript lookup has no Discord permission "
        "layer; retained fetch-outage cases preserve the checkpoint and calibration lease.",
        "TestExplicitResume.test_wrong_author_gets_notice":
        "Removed Discord multi-author resume intake and wrong-author notice. Desktop has one "
        "authenticated canonical profile owner; authentication and original-author provenance "
        "rejection remain supported and tested.",
        "TestMentionAnchoredResumeTrigger.test_foreign_mention_is_not_stripped":
        "Removed Discord foreign-mention stripping at resume intake; desktop bare resume "
        "and non-trigger pass-through remain supported and tested.",
        "TestMentionAnchoredResumeTrigger.test_leading_mention_resume_triggers":
        "Removed Discord leading bot-mention resume intake; desktop bare resume remains "
        "supported and tested.",
        "TestMentionAnchoredResumeTrigger.test_mention_plus_sentence_is_not_a_command":
        "Removed Discord mention-plus-sentence command intake; desktop bare resume and "
        "non-trigger pass-through remain supported and tested.",
        "TestMentionAnchoredResumeTrigger.test_mention_recognized_trigger_still_fails_closed":
        "Removed Discord mention-recognized resume intake; desktop bare resume rejection "
        "and fail-closed checkpoint admission remain supported and tested.",
        "TestMentionAnchoredResumeTrigger.test_nickname_mention_form_triggers":
        "Removed Discord nickname bot-mention resume intake; desktop bare resume remains "
        "supported and tested.",
        "TestMentionAnchoredResumeTrigger.test_trailing_mention_is_not_a_command":
        "Removed Discord trailing-mention command intake; desktop bare resume and "
        "non-trigger pass-through remain supported and tested.",
    },
    "tests/test_chat_steering_runtime.py": {
        "test_tool_batch_pairs_checkpoint_before_replan_no_stale_judgment_or_handoff":
        "Removed Discord admin/multi-requester steering: this case admits user 999999 as admin "
        "and asserts a distinct numeric Discord requester retains tool authority; desktop has "
        "exactly one authenticated canonical profile owner.",
    },
    "tests/test_session_search.py": {
        "TestSessionSearchAPI.test_search_with_user_filter":
        "Removed API identity surface: REST selects Bob from Alice/Bob messages; desktop one "
        "canonical installation owner, no multi-user participant/API identity metadata; "
        "fabricating seed identities as authority does not preserve meaning; copied engine "
        "user-provenance cases remain restored.",
    },
    "tests/characterization/test_executor_dispatch_parity.py": {
        "TestMiddlewarePins.test_rbac_denial_shape_and_metrics":
        "Guest-tier RBAC is removed by Desktop D17; Claude, review of #35 retires only this "
        "guest denial/metrics case.",
    },
    "tests/test_tool_loop_helpers.py": {
        case: (
            "Multi-bot origin handling (from_another_bot=True) is removed by Desktop; "
            "Claude, review of #35 retires only bot-origin cases.")
        for case in ("TestBuildRequestPreamble.test_bot_message_block",
                     "TestBuildRequestPreamble.test_no_history_bot_turn_keeps_bot_origin_note")
    },
}
PR35_CASE_SOURCE_SHA256 = {
    "tests/test_codex_replay_matrix.py":
        "eed93185f30efd619bafbfb1fd0f2d7bcac1eda96879b50214cfc1f8f5585256",
    "tests/test_campaign_cli_coverage.py":
        "fe47a4c99af2c48f8bf397a0634830b82c5afa50e74ab53eb0fb26864a434d0b",
    "tests/test_chat_steering_parity.py":
        "48cf45bcceed1be223a2cf8428af0a9eff3e57b695b1d147a3e6fe7a843233ec",
    "tests/test_resume_admission.py":
        "995d1fb1df090aeb4ed5f5983859ae712f56de87f7f86e6e58c72ae20a8a41ce",
    "tests/test_chat_steering_runtime.py":
        "b41818cc97a50a4794cac024b953f7199369b225e863e1c9b4c34b2e32cc3f2b",
    "tests/test_session_search.py":
        "38aa1cce39048336ef77697cade3d9d6f964e294fa8b9daed24a50600ab0c292",
    "tests/characterization/test_executor_dispatch_parity.py":
        "652656e3e628455a90975498315f7fe4fcc329cac940e0e5ff34ac60bea43a29",
    "tests/test_tool_loop_helpers.py":
        "a852e1e285166c02beaedc9c5c4ae113c77ffd1aec08641bcc19870b19ea5782",
}
KINDS = ("excluded", "phase2", "retained_adaptation_gated", "retained_support",
         "safe_pass_now", "safety_manual_gated", "retired")
MAP_PATH = "maintenance/phase2-suite-map.json"
PLAN_PATH = "maintenance/test-plan.json"
QUALIFICATION_PATH = "maintenance/qualification-plan.json"
RESTORATION_GROUPS = {
    1: "phase2-core-transport",
    2: "phase2-step2-restored-corpus",
    3: "phase2-step3-restored-corpus",
    4: "phase2-step4-restored-corpus",
    5: "phase2-step5-profile-management",
}

# Reviewed PR28 additions only. These are byte-pinned full original imports,
# not the generic frozen-adapter protocol used by Phase 2 restorations.
STEP6A_GROUP = "phase2-step6a-qualified-local-services"
STEP6A_FILES = frozenset({
    "tests/test_desktop_skills.py", "tests/test_desktop_mcp.py",
    "tests/test_desktop_browser_runtime.py", "tests/test_desktop_computer_binding.py",
    "tests/test_desktop_dependency_resolver.py", "tests/test_desktop_service_catalog.py",
    "tests/test_desktop_services_core.py", "tests/test_desktop_workspace_diagnostics.py",
})
STEP6A_REASON = (
    "Step 6A real skill lifecycle/schema/dependency installation, supervised configured MCP, "
    "bundled Chromium startup, bounded local workspace diagnostics and authentic computer "
    "management/recovery. Pip, keyring, network, browser and native backends stubbed; benign "
    "disposable git only. No foreground/delivery/work/schedule implementation or native "
    "qualification claim. Immutable GI original cases run in the direct group through the "
    "worker-only resolver adapter without assertion edits. All engine suites remain isolated "
    "PID namespace with throwaway HOME."
)
MERGED_SELECTOR_ADAPTERS = {
    "direct-shared-stores-providers-tools": (
        "tests/test_gi_support_loading.py", "tests/test_desktop_gi_loading_adaptation.py",
        "18488dd73087297c17291811744e770730d866d338f563cd3490a411f1e24b8b",
    ),
    "direct-shared-computer": (
        "tests/test_computer_runtime_coverage_r10.py",
        "tests/test_desktop_accessibility_gi_adaptation.py",
        "01f8d63a5d5c6f6fa596209fc29623a7a9f344e9475e134a86974bb4d3192955",
    ),
}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: str | bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def _git_blob(root: Path, revision: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{revision}:{path}"],
        check=False, capture_output=True, timeout=30,
    )
    if result.returncode:
        raise ValueError(f"cannot read pinned historical object {revision}:{path}")
    return result.stdout


def _path(value, *, python=True) -> bool:
    return (isinstance(value, str) and value.startswith("tests/")
            and (not python or value.endswith(".py")) and "::" not in value
            and not PurePosixPath(value).is_absolute()
            and ".." not in PurePosixPath(value).parts
            and str(PurePosixPath(value)) == value)


def _regular(root: Path, path: str) -> Path:
    target = root / path
    current = root
    for part in PurePosixPath(path).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlink test path: {path}")
    if not target.is_file():
        raise ValueError(f"missing regular file: {path}")
    return target


def _strings(value, label: str, errors: list[str], *, empty=False) -> list[str]:
    if (not isinstance(value, list) or (not value and not empty)
            or any(not isinstance(item, str) or not item.strip() for item in value)):
        errors.append(f"{label}: expected {'possibly empty ' if empty else ''}string list")
        return []
    if len(value) != len(set(value)):
        errors.append(f"{label}: duplicate values")
    return value


def _indexed(rows, label: str, errors: list[str]) -> dict:
    if not isinstance(rows, list):
        errors.append(f"{label}: expected row list")
        return {}
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not _path(row.get("path"), python=False):
            errors.append(f"{label}: malformed/noncanonical path row")
            continue
        path = row["path"]
        if path in result:
            errors.append(f"{label}: duplicate path {path}")
        result[path] = row
    return result


def _adapter_modules(root: Path, selector: str) -> list[ast.Module]:
    """Read only test-local static import closure; never import these modules."""
    todo, seen, trees = [selector], set(), []
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(_regular(root, path).read_bytes(), filename=path)
        trees.append(tree)
        for node in ast.walk(tree):
            names = ([node.module] if isinstance(node, ast.ImportFrom)
                     and node.level == 0 and node.module else
                     [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.extend(f"{node.module}.{alias.name}" for alias in node.names
                             if alias.name != "*")
            for name in names:
                candidate = name.replace(".", "/") + ".py"
                if candidate.startswith("tests/") and (root / candidate).is_file():
                    todo.append(candidate)
    return trees


def _case_retirements(root: Path, path: str, inherited_hash: str, value) -> bool:
    """Exact review dispositions, canonical source case identities, no globs/params."""
    if not isinstance(value, list):
        return False
    if not value:
        return True
    if inherited_hash != PR35_CASE_SOURCE_SHA256.get(path):
        return False
    source = _regular(root, path).read_bytes()
    if _digest(source) != inherited_hash:
        return False
    tree = ast.parse(source, filename=path)
    cases = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cases.add(node.name)
        elif isinstance(node, ast.ClassDef):
            cases.update(f"{node.name}.{child.name}" for child in node.body
                         if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)))
    names = []
    for row in value:
        if (not isinstance(row, dict) or set(row) != {
                "case", "reviewer", "reason", "source_path", "source_sha256"}):
            return False
        case = row["case"]
        round2_reason = PR35_ROUND2_CASE_REASONS.get(path, {}).get(case)
        expected_reviewer = PR35_ROUND2_REVIEWER if round2_reason else PR35_REVIEWER
        expected_reason = round2_reason or PR35_CASE_REASONS.get(path, {}).get(case)
        if (not isinstance(case, str) or case not in cases
                or row["reviewer"] != expected_reviewer
                or row["source_path"] != path or row["source_sha256"] != inherited_hash
                or expected_reason is None or row["reason"] != expected_reason):
            return False
        names.append(case)
    return names == sorted(set(names))


def _branch_retirements(root: Path, path: str, inherited_hash: str, value) -> bool:
    if value == []:
        return True
    if path != "tests/test_tool_loop_helpers.py" or inherited_hash != PR35_CASE_SOURCE_SHA256[path]:
        return False
    expected = {
        "case": "TestBehaviorPreservedByRefactor.test_all_combinations_match_reference",
        "reviewer": PR35_REVIEWER,
        "reason": PR35_CASE_REASONS[path]["TestBuildRequestPreamble.test_bot_message_block"],
        "source_path": path, "source_sha256": inherited_hash,
        "line": 170, "column": 36,
        "node_sha256": "dca8f82ad2c13093e18831c63d876733f70de16f7f9f34083e01bc131bb8218e",
        "before_source": "(True, False)", "after_source": "(False,)",
    }
    if (not isinstance(value, list) or value != [expected]
            or type(value[0].get("line")) is not int
            or type(value[0].get("column")) is not int):
        return False
    source = _regular(root, path).read_bytes()
    if _digest(source) != inherited_hash:
        return False
    matches = [node for node in ast.walk(ast.parse(source))
               if getattr(node, "lineno", None) == 170 and getattr(node, "col_offset", None) == 36
               and _digest(ast.dump(node, include_attributes=False).encode())
               == expected["node_sha256"]]
    return len(matches) == 1


def _reviewed_exclusion_expression(node: ast.expr) -> bool:
    """Only the documented metadata-to-case projection, not arbitrary selection."""
    for variable in ("stem", "name"):
        expected = ast.parse(
            f"[item['case'] for item in CORPUS_EXCLUSIONS.get({variable}, ())]",
            mode="eval").body
        if ast.dump(node) == ast.dump(expected):
            return True
    return False


def _parameter_retirements(root: Path, path: str, inherited_hash: str, value) -> bool:
    """Exactly five reviewed Codex matrix rows, both original replay paths."""
    if value == {}:
        return True
    expected = {
        "test_emitted_replayed_matrix": [
            "builtin-add_reaction", "builtin-create_poll", "builtin-purge_messages",
            "builtin-read_channel", "builtin-set_permission",
        ],
    }
    if (path != "tests/test_codex_replay_matrix.py" or value != expected
            or inherited_hash != PR35_CASE_SOURCE_SHA256[path]):
        return False
    source = _regular(root, path).read_bytes()
    if _digest(source) != inherited_hash:
        return False
    tree = ast.parse(source)
    matrix = [node for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "BUILTIN_INPUTS"
                      for target in node.targets)]
    if (len(matrix) != 1 or _digest(ast.dump(matrix[0], include_attributes=False).encode())
            != "96af24f8e2b4f7d499fa0c8c7f0b8fa77600552871bc1109b85169e8ae736c43"):
        return False
    names = {ast.literal_eval(key) for key in matrix[0].value.keys}
    retired_names = {
        label.removeprefix("builtin-") for label in expected["test_emitted_replayed_matrix"]
    }
    return retired_names <= names


def _full_adapter(root: Path, selector: str, path: str, inherited_hash: str,
                  case_retirements=None, branch_retirements=None,
                  parameter_retirements=None) -> bool:
    """Fail-closed static full-export association for frozen corpus loaders.

    A literal admission alone is insufficient: the reachable loader must read
    frozen bytes, pin their digest, guard corpus AST identity and export the
    complete module. Runtime qualification remains the named group's job.
    """
    trees = _adapter_modules(root, selector)
    reviewed = [] if case_retirements is None else case_retirements
    if not _case_retirements(root, path, inherited_hash, reviewed):
        return False
    declared = None
    reviewed_branches = [] if branch_retirements is None else branch_retirements
    if not _branch_retirements(root, path, inherited_hash, reviewed_branches):
        return False
    declared_branches = None
    reviewed_parameters = {} if parameter_retirements is None else parameter_retirements
    if not _parameter_retirements(root, path, inherited_hash, reviewed_parameters):
        return False
    declared_parameters = None
    exclusion_export = False
    admitted = False
    pinned = False
    frozen = False
    export = False
    corpus_guard = False
    hash_guard = False
    compile_frozen = False
    invokes_loader = False
    stem = PurePosixPath(path).stem
    aliases = {stem, path.removeprefix("tests/").removesuffix(".py")}
    for tree in trees:
        constants = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    if any(isinstance(target, ast.Name) and target.id in {
                        "CORPUS_EXCLUSIONS", "CORPUS_SELECTIONS", "CORPUS_BRANCH_RETIREMENTS",
                        "PARAMETER_RETIREMENTS"}
                           for target in node.targets):
                        return False
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = value
        selections = constants.get("CORPUS_SELECTIONS", {})
        matching_keys = aliases & set(selections) if isinstance(selections, dict) else set()
        for key in matching_keys:
            if selections[key] is not None:
                return False
            admitted = True
        exclusions = constants.get("CORPUS_EXCLUSIONS", {})
        if not isinstance(exclusions, dict):
            return False
        for excluded_stem, dispositions in exclusions.items():
            if not isinstance(dispositions, list) or not dispositions:
                return False
            source_path = (
                dispositions[0].get("source_path") if isinstance(dispositions[0], dict) else None)
            sha = (
                dispositions[0].get("source_sha256") if isinstance(dispositions[0], dict) else None)
            if (not _path(source_path) or excluded_stem not in {
                    PurePosixPath(source_path).stem,
                    source_path.removeprefix("tests/").removesuffix(".py")}
                    or not _case_retirements(root, source_path, sha, dispositions)):
                return False
        branches = constants.get("CORPUS_BRANCH_RETIREMENTS", {})
        if not isinstance(branches, dict):
            return False
        for key, dispositions in branches.items():
            if (not isinstance(dispositions, list) or not dispositions
                    or not isinstance(dispositions[0], dict)):
                return False
            source_path = dispositions[0].get("source_path")
            sha = dispositions[0].get("source_sha256")
            if (not _path(source_path) or key != PurePosixPath(source_path).stem
                    or not _branch_retirements(root, source_path, sha, dispositions)):
                return False
        parameters = constants.get("PARAMETER_RETIREMENTS", {})
        if not isinstance(parameters, dict):
            return False
        for key, dispositions in parameters.items():
            source_path = f"tests/{key}.py"
            if (key != "test_codex_replay_matrix" or not dispositions
                    or not _parameter_retirements(root, source_path,
                                                  PR35_CASE_SOURCE_SHA256[source_path],
                                                  dispositions)
                    or constants.get("REVIEW_AUTHORITY") != PR35_ROUND2_REVIEWER):
                return False
        for key in matching_keys:
            current = exclusions.get(key, [])
            if declared is not None and declared != current:
                return False
            declared = current
            current_branches = branches.get(key, [])
            if declared_branches is not None and declared_branches != current_branches:
                return False
            declared_branches = current_branches
            current_parameters = parameters.get(key, {})
            if declared_parameters is not None and declared_parameters != current_parameters:
                return False
            declared_parameters = current_parameters
        if ((constants.get("SOURCE_PATH") == path or constants.get("PATH") == path)
                and constants.get("SOURCE_SHA256") == inherited_hash):
            pinned = True
        suites = constants.get("SUITES", {})
        if isinstance(suites, dict) and any(suites.get(key) == inherited_hash for key in aliases):
            pinned = True
        sources = constants.get("SOURCES", {})
        if isinstance(sources, dict) and any(
                value in ([path, inherited_hash], (path, inherited_hash))
                for value in sources.values()):
            pinned = True
        for node in ast.walk(tree):
            # Literal metadata is authority, not mutable executable policy.
            if isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                target = node.target
                if isinstance(target, ast.Name) and target.id in {
                    "CORPUS_EXCLUSIONS", "CORPUS_SELECTIONS", "CORPUS_BRANCH_RETIREMENTS",
                    "PARAMETER_RETIREMENTS"}:
                    return False
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) \
                            and target.value.id in {
                                "CORPUS_EXCLUSIONS", "CORPUS_SELECTIONS",
                                "CORPUS_BRANCH_RETIREMENTS", "PARAMETER_RETIREMENTS"}:
                        return False
            if isinstance(node, ast.Call):
                name = (node.func.id if isinstance(node.func, ast.Name)
                        else node.func.attr if isinstance(node.func, ast.Attribute) else "")
                frozen |= name == "frozen_source"
                export |= name == "register_module"
                compile_frozen |= name == "compile" and len(node.args) >= 3 and any(
                    isinstance(arg, ast.Constant) and arg.value == "exec" for arg in node.args)
                invokes_loader |= name == "load" and any(
                    isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                    and arg.func.id == "globals" for arg in node.args)
                if name == "register_module":
                    for kw in node.keywords:
                        if kw.arg in {None, "selected"}:
                            return False
                        if kw.arg == "excluded":
                            if not _reviewed_exclusion_expression(kw.value):
                                return False
                            exclusion_export = True
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    if node.func.value.id in {
                            "CORPUS_EXCLUSIONS", "CORPUS_SELECTIONS",
                            "CORPUS_BRANCH_RETIREMENTS", "PARAMETER_RETIREMENTS"} \
                            and node.func.attr not in {"get", "items", "values"}:
                        return False
            if isinstance(node, (ast.If, ast.Assert)):
                condition = node.test
                calls = [n for n in ast.walk(condition) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Name) and n.func.id == "corpus"]
                guards = (isinstance(node, ast.Assert) or any(
                    isinstance(n, ast.Raise) for child in node.body for n in ast.walk(child)))
                comparisons = [n for n in ast.walk(condition) if isinstance(n, ast.Compare)]
                equality = ast.Eq if isinstance(node, ast.Assert) else ast.NotEq
                correct_operator = any(any(isinstance(op, equality) for op in n.ops)
                                       for n in comparisons)
                if len(calls) >= 2 and guards and correct_operator:
                    corpus_guard = True
                hash_calls = [n for n in ast.walk(condition) if isinstance(n, ast.Call)
                              and isinstance(n.func, ast.Attribute)
                              and n.func.attr in {"sha256", "hexdigest"}]
                digest_calls = [n for n in ast.walk(condition) if isinstance(n, ast.Call)
                                and isinstance(n.func, ast.Name) and n.func.id == "digest"]
                exact_digest = ast.parse(
                    "def digest(data):\n    return hashlib.sha256(data).hexdigest()\n").body[0]
                if digest_calls and any(
                        isinstance(n, ast.FunctionDef) and ast.dump(n) == ast.dump(exact_digest)
                        for n in tree.body):
                    hash_calls.extend(digest_calls)
                hash_guard |= bool(hash_calls and guards and correct_operator)
    return (admitted and pinned and frozen and export and corpus_guard and hash_guard
            and compile_frozen and invokes_loader and declared == reviewed
            and declared_branches == reviewed_branches
            and declared_parameters == reviewed_parameters
            and (not reviewed or exclusion_export))


def _check(root: Path) -> tuple[list[str], dict]:
    errors: list[str] = []
    report = {"original_population": 0, "mapped": 0, "restored": 0,
              "deferred": 0, "retired": 0, "by_step": {}, "classifications": {}}
    try:
        mapping = _json((root / MAP_PATH).read_bytes())
        plan = _json((root / PLAN_PATH).read_bytes())
        qualification = _json((root / QUALIFICATION_PATH).read_bytes())
        historical_bytes = _git_blob(root, SOURCE_MAIN, PLAN_PATH)
        qualification_bytes = _git_blob(root, SOURCE_MAIN, QUALIFICATION_PATH)
        merged_bytes = _git_blob(root, MERGED_MAIN, QUALIFICATION_PATH)
        if (_digest(historical_bytes) != HISTORICAL_PLAN_SHA256
                or _digest(qualification_bytes) != HISTORICAL_QUALIFICATION_SHA256):
            raise ValueError("pinned historical accounting object hash changed")
        if _digest(merged_bytes) != MERGED_QUALIFICATION_SHA256:
            raise ValueError("pinned merged qualification object hash changed")
        merged_qualification = _json(merged_bytes)
        historical = _json(historical_bytes)
        historical_qualification = _json(qualification_bytes)
        if not all(isinstance(item, dict) for item in
                   (mapping, plan, qualification, historical, historical_qualification,
                    merged_qualification)):
            raise ValueError("mapping/plan/qualification must be JSON objects")
        archive_bytes = (root / "maintenance/odin-v4.13.0.tar.gz").read_bytes()
        if _digest(archive_bytes) != ARCHIVE_SHA256:
            raise ValueError("immutable original archive hash changed")
        originals = {}
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            for member in archive:
                if not member.name.startswith("tests/") or not member.isfile():
                    continue
                if not _path(member.name, python=False) or member.name in originals:
                    raise ValueError("duplicate/noncanonical original archive test path")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("unreadable original archive member")
                originals[member.name] = stream.read()
    except (OSError, ValueError, TypeError, KeyError, tarfile.TarError,
            subprocess.SubprocessError) as exc:
        return [f"input: {exc}"], report

    if type(mapping.get("schema_version")) is not int or mapping["schema_version"] != 1:
        errors.append("mapping: unsupported schema_version")
    for key, value in (("baseline", BASELINE), ("source_main", SOURCE_MAIN),
                       ("work_order", WORK_ORDER)):
        if mapping.get(key) != value:
            errors.append(f"mapping: {key} differs from pinned authority")
    population = _strings(historical.get("phase2"), "historical phase2", errors)
    expected = set(population)
    digest = _digest(("\n".join(sorted(expected)) + "\n").encode())
    if len(population) != 326 or len(expected) != 326 or digest != POPULATION_SHA256:
        errors.append("historical Phase 2 membership/hash is not the original 326")
    report["original_population"] = len(expected)
    if mapping.get("original_population") != {"count": 326, "sha256": POPULATION_SHA256}:
        errors.append("mapping: original_population count/hash mismatch")
    original_entries = _indexed(historical.get("entries"), "historical plan", errors)
    entries = _indexed(plan.get("entries"), "current test-plan", errors)
    if (
        len(originals) != 869
        or set(entries) != set(originals)
        or set(original_entries) != set(originals)
    ):
        errors.append("test-plan: exact original 869-path membership required")
    if plan.get("schema_version") != 1 or plan.get("baseline") != historical.get("baseline"):
        errors.append("test-plan: schema/baseline mismatch")
    classified = {kind: set() for kind in KINDS}
    for path, entry in entries.items():
        kind = entry.get("classification")
        if kind not in classified:
            errors.append(f"test-plan: unknown classification for {path}")
            continue
        classified[kind].add(path)
        if path not in originals:
            continue
        sha = _digest(originals[path])
        if entry.get("sha256") != sha or original_entries.get(path, {}).get("sha256") != sha:
            errors.append(f"test-plan: immutable inherited_sha256 mismatch {path}")
        if kind != "excluded" or (root / path).exists() or (root / path).is_symlink():
            try:
                if _digest(_regular(root, path).read_bytes()) != sha:
                    errors.append(f"original bytes changed: {path}")
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
    counts = plan.get("counts", {})
    if not isinstance(counts, dict):
        errors.append("test-plan: counts must be an object")
        counts = {}
    for kind, paths in classified.items():
        array = _strings(plan.get(kind), f"test-plan {kind}", errors, empty=True)
        if set(array) != paths:
            errors.append(f"test-plan: {kind} array differs from entry classifications")
        if type(counts.get(kind)) is not int or counts[kind] != len(paths):
            errors.append(f"test-plan: stale {kind} count")
    report["classifications"] = {kind: len(paths) for kind, paths in classified.items()}
    restored_array = _strings(plan.get("phase2_restored", []), "test-plan phase2_restored",
                              errors, empty=True)
    restored_paths = set(restored_array)
    retired_paths = set(_strings(plan.get("phase2_retired", []),
                                 "test-plan phase2_retired", errors, empty=True))
    if (classified["phase2"] & restored_paths or classified["phase2"] & retired_paths
            or restored_paths & retired_paths
            or classified["phase2"] | restored_paths | retired_paths != expected):
        errors.append("test-plan: phase2/restored/retired must preserve exact historical 326")
    if retired_paths != classified["retired"]:
        errors.append("test-plan: phase2_retired must match retired classification")
    if not restored_paths <= classified["safe_pass_now"]:
        errors.append("test-plan: every phase2_restored suite must be safe_pass_now")
    if "phase2_restored" in counts and (
        type(counts["phase2_restored"]) is not int
        or counts["phase2_restored"] != len(restored_paths)
    ):
        errors.append("test-plan: stale phase2_restored count")
    if "phase2_retired" in counts and (
        type(counts["phase2_retired"]) is not int
        or counts["phase2_retired"] != len(retired_paths)
    ):
        errors.append("test-plan: stale phase2_retired count")
    if set(counts) - set(KINDS) - {"phase2_restored", "phase2_retired"}:
        errors.append("test-plan: unknown classification count")

    groups = qualification.get("groups")
    old_groups = historical_qualification.get("groups", [])
    if not isinstance(groups, list):
        errors.append("qualification: groups must be a list")
        groups = []
    named = {}
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("name"), str):
            errors.append("qualification: malformed group")
            continue
        name = group["name"]
        if name in named:
            errors.append(f"qualification: duplicate group {name}")
        named[name] = group
        _strings(group.get("files"), f"qualification {name} files", errors)
    old_names = {group["name"] for group in old_groups}
    merged_groups = merged_qualification["groups"]
    merged_names = {group["name"] for group in merged_groups}
    restoration_names = set(RESTORATION_GROUPS.values()) - {"phase2-core-transport"}
    additions = set(named) - merged_names
    if (not old_names <= merged_names or not merged_names <= set(named)
            or additions - restoration_names - {STEP6A_GROUP}):
        errors.append("qualification: preserve all historical and merged main named groups")
    if STEP6A_GROUP in named:
        group = named[STEP6A_GROUP]
        if (set(group) != {"name", "files", "reason"}
                or set(group.get("files", [])) != STEP6A_FILES
                or group.get("reason") != STEP6A_REASON):
            errors.append(f"qualification: exact reviewed files/reason required for {STEP6A_GROUP}")
        for selector in STEP6A_FILES:
            try:
                _regular(root, selector)
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
    replacements = {}
    for name, (original, adapter, sha) in MERGED_SELECTOR_ADAPTERS.items():
        selected_by = {group_name for group_name, group in named.items()
                       if adapter in group.get("files", [])}
        if not selected_by:
            continue
        group = named.get(name, {})
        if (selected_by != {name} or original in group.get("files", [])
                or any(group.get(key) for key in (
                    "exclude_expression", "include_expression", "args", "pytest_args",
                    "exclusions"))):
            errors.append(
                f"qualification: exact full-suite adapter association required for {adapter}")
            continue
        try:
            if _digest(_regular(root, adapter).read_bytes()) != sha:
                raise ValueError(f"reviewed adapter bytes changed: {adapter}")
            if _regular(root, original).read_bytes() != originals[original]:
                raise ValueError(f"adapter original bytes changed: {original}")
        except (OSError, ValueError, KeyError) as exc:
            errors.append(str(exc))
            continue
        replacements[name] = (original, adapter)
    for group in merged_groups:
        required = set(group["files"])
        if group["name"] in replacements:
            original, adapter = replacements[group["name"]]
            required.remove(original)
            required.add(adapter)
        if not required <= set(named.get(group["name"], {}).get("files", [])):
            errors.append(f"qualification: lost merged main selectors in {group['name']}")
    if "phase2-core-transport" not in named:
        errors.append("qualification: phase2-core-transport group missing")

    rows = mapping.get("entries")
    mapped = _indexed(rows, "mapping", errors)
    if set(mapped) != expected:
        missing, orphan = sorted(expected - set(mapped)), sorted(set(mapped) - expected)
        errors.append(f"mapping: historical membership mismatch missing={missing} orphan={orphan}")
    if isinstance(rows, list) and all(
        isinstance(row, dict) and _path(row.get("path")) for row in rows
    ):
        if [row["path"] for row in rows] != sorted(row["path"] for row in rows):
            errors.append("mapping: entries must be sorted by path")
    report["mapped"] = len(mapped)
    by_step = {str(step): {"total": 0, "restored": 0, "deferred": 0, "retired": 0}
               for step in (*range(1, 8), "Phase 3")}
    status_counts = Counter()
    mapped_restored = set()
    mapped_retired = set()
    for path, row in mapped.items():
        step, status = row.get("step"), row.get("status")
        if not (type(step) is int and 1 <= step <= 7 or step == "Phase 3"):
            errors.append(f"mapping: invalid step for {path}")
        else:
            by_step[str(step)]["total"] += 1
            if status in {"restored", "deferred", "retired"}:
                by_step[str(step)][status] += 1
        if status not in {"restored", "deferred", "retired"}:
            errors.append(f"mapping: invalid status for {path}")
            continue
        status_counts[status] += 1
        if row.get("inherited_sha256") != original_entries.get(path, {}).get("sha256"):
            errors.append(f"mapping: inherited_sha256 mismatch for {path}")
        for field in ("reason", "qualification_group"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                errors.append(f"mapping: missing {field} for {path}")
        _strings(row.get("surfaces"), f"mapping {path} surfaces", errors)
        if row.get("historical_classification", "phase2") != "phase2":
            errors.append(f"mapping: historical classification changed for {path}")
        if status == "retired":
            mapped_retired.add(path)
            retirement = row.get("retirement", {})
            expected_reviewer = (RETIREMENT_REVIEWER if path in RETIRABLE_SUITES else PR35_REVIEWER)
            expected_reason = {**RETIREMENT_REASONS, **PR35_RETIREMENT_REASONS}.get(path)
            expected_step = (
                1 if path in RETIRABLE_SUITES else PR35_RETIREMENTS.get(path, (None,))[0])
            if (expected_reason is None or type(step) is not int or step != expected_step
                    or not isinstance(retirement, dict)
                    or retirement != {"reviewer": expected_reviewer, "reason": expected_reason}
                    or row.get("reason") != expected_reason
                    or entries.get(path, {}).get("reason") != expected_reason):
                errors.append(f"mapping: retired suite needs exact reviewed disposition: {path}")
            if path not in retired_paths or path not in classified["retired"]:
                errors.append(f"mapping: retired suite must be retired in test-plan: {path}")
            if entries.get(path, {}).get("retirement") != retirement:
                errors.append(f"mapping: retired review differs from test-plan: {path}")
            if (row.get("blocked_on", "missing") is not None or "restoration" in row
                    or row.get("qualification_group") != "not-applicable-retired"):
                errors.append(
                    f"mapping: retired suite cannot claim restoration/qualification: {path}")
            if any(any(selector == path or selector.startswith(path + "::")
                       for selector in group.get("files", [])) for group in groups):
                errors.append(f"mapping: retired suite cannot be selected as passing: {path}")
            continue
        if status == "deferred":
            if path not in classified["phase2"] or path in restored_paths:
                errors.append(f"mapping: deferred suite no longer classified phase2: {path}")
            if not isinstance(row.get("blocked_on"), str) or not row["blocked_on"].strip():
                errors.append(f"mapping: deferred suite needs clear blocker: {path}")
            if "restoration" in row:
                errors.append(f"mapping: deferred suite carries restoration: {path}")
            continue
        mapped_restored.add(path)
        if type(step) is not int or step not in RESTORATION_GROUPS:
            errors.append(f"mapping: restored suite must belong to qualified steps 1 to 5: {path}")
        elif row.get("qualification_group") != RESTORATION_GROUPS[step]:
            errors.append(f"mapping: restored suite must use its owning step group: {path}")
        if row.get("blocked_on", "missing") is not None:
            errors.append(f"mapping: restored suite must have blocked_on null: {path}")
        if path not in classified["safe_pass_now"] or path not in restored_paths:
            errors.append(
                f"mapping: restored suite must be safe_pass_now and phase2_restored: {path}"
            )
        group = named.get(row.get("qualification_group"))
        if group is None:
            errors.append(f"mapping: restored suite names nonexistent qualification group: {path}")
            continue
        if any(group.get(key) for key in ("exclude_expression", "include_expression", "args",
                                           "pytest_args", "exclusions")):
            errors.append(
                f"mapping: restored suite group cuts assertions with selection/exclusions: {path}"
            )
        restoration = row.get("restoration", {"mode": "direct-original", "selectors": [path],
                                               "reason": row.get("reason")})
        if not isinstance(restoration, dict):
            errors.append(f"mapping: malformed restoration: {path}")
            continue
        mode = restoration.get("mode")
        case_retirements = restoration.get("case_retirements", [])
        branch_retirements = restoration.get("branch_retirements", [])
        parameter_retirements = restoration.get("parameter_retirements", {})
        try:
            valid_cases = _case_retirements(root, path, row.get("inherited_sha256", ""),
                                           case_retirements)
            valid_branches = _branch_retirements(root, path, row.get("inherited_sha256", ""),
                                                branch_retirements)
        except (OSError, ValueError, TypeError, SyntaxError):
            valid_cases = False
            valid_branches = False
        if not valid_cases or (case_retirements and mode != "frozen-adapter"):
            errors.append(f"mapping: invalid reviewed case retirements: {path}")
        if (not _parameter_retirements(root, path, row.get("inherited_sha256", ""),
                                      parameter_retirements)
                or (parameter_retirements and mode != "frozen-adapter")):
            errors.append(f"mapping: invalid reviewed parameter retirements: {path}")
        if not valid_branches or (branch_retirements and mode != "frozen-adapter"):
            errors.append(f"mapping: invalid reviewed branch retirements: {path}")
        selectors = _strings(restoration.get("selectors"), f"restoration {path} selectors", errors)
        if not isinstance(restoration.get("reason"), str) or not restoration["reason"].strip():
            errors.append(f"mapping: restoration needs reason: {path}")
        if mode not in {"direct-original", "frozen-adapter"}:
            errors.append(f"mapping: unknown restoration mode: {path}")
        for selector in selectors:
            if not _path(selector) or selector not in group.get("files", []):
                errors.append(
                    f"mapping: whole suite selector not selected in named group: {path}: {selector}"
                )
                continue
            try:
                _regular(root, selector)
                if mode == "direct-original" and selectors != [path]:
                    errors.append(
                        f"mapping: direct-original must select entire original suite: {path}"
                    )
                if mode == "frozen-adapter" and not _full_adapter(
                    root, selector, path, row.get("inherited_sha256", ""), case_retirements,
                    branch_retirements, parameter_retirements
                ):
                    errors.append(
                        f"mapping: adapter lacks immutable full-suite corpus association: {path}"
                    )
            except (OSError, ValueError, SyntaxError, TypeError) as exc:
                errors.append(f"mapping: invalid executable association {path}: {exc}")
        for neutral in plan.get("safe_neutral_case_selections", []):
            if (
                isinstance(neutral, dict)
                and neutral.get("path") == path
                and neutral.get("exclude_expression")
            ):
                errors.append(
                    f"mapping: restored suite still has partial neutral exclusion: {path}"
                )
    if mapped_restored != restored_paths:
        errors.append("mapping: restored rows differ from phase2_restored historical marker")
    if mapped_retired != retired_paths:
        errors.append("mapping: retired rows differ from phase2_retired historical marker")
    report.update({"restored": status_counts["restored"], "deferred": status_counts["deferred"],
                   "retired": status_counts["retired"], "by_step": by_step})
    if "counts" in mapping:
        expected_counts = {"total": len(mapped), "restored": report["restored"],
                           "deferred": report["deferred"], "retired": report["retired"],
                           "by_step": by_step}
        if mapping["counts"] != expected_counts:
            errors.append("mapping: stale recomputed counts")
    case_manifest = root / "maintenance/phase2-step8-part5-cases.json"
    if case_manifest.exists() or mapping.get("case_dispositions"):
        try:
            from scripts.maintenance import phase2_part5
        except ModuleNotFoundError:
            import phase2_part5
        case_errors, case_report = phase2_part5.validate(root)
        errors.extend(f"part5 cases: {error}" for error in case_errors)
        report["part5_case_dispositions"] = case_report
    return errors, report


def _evaluate(root: Path) -> tuple[list[str], dict]:
    try:
        return _check(root)
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            subprocess.SubprocessError) as exc:
        return [f"malformed accounting input: {exc}"], {}


def validate(root: Path | str = ROOT) -> list[str]:
    """Return all detected mapping/accounting errors; an empty list is valid."""
    return _evaluate(Path(root))[0]


def record_review_retirements(root: Path) -> None:
    """Record only the five explicit #26 dispositions; never run or rewrite suites."""
    mapping = _json((root / MAP_PATH).read_bytes())
    plan = _json((root / PLAN_PATH).read_bytes())
    rows = {row["path"]: row for row in mapping["entries"]}
    entries = {row["path"]: row for row in plan["entries"]}
    for path, reason in RETIREMENT_REASONS.items():
        row, entry = rows[path], entries[path]
        if (row["status"] not in {"deferred", "retired"} or row["step"] != 1
                or entry["classification"] not in {"phase2", "retired"}
                or _digest(_regular(root, path).read_bytes()) != row["inherited_sha256"]
                or entry["sha256"] != row["inherited_sha256"]):
            raise ValueError(f"retirement requires original held step-1 bytes: {path}")
    for path, reason in RETIREMENT_REASONS.items():
        row, entry = rows[path], entries[path]
        row.update(status="retired", reason=reason, blocked_on=None,
                   qualification_group="not-applicable-retired",
                   retirement={"reviewer": RETIREMENT_REVIEWER, "reason": reason})
        row.pop("pending_contract_disposition", None)
        entry.update(classification="retired", reason=reason,
                     retirement={"reviewer": RETIREMENT_REVIEWER, "reason": reason})
    plan["phase2"] = sorted(path for path in plan["phase2"] if path not in RETIRABLE_SUITES)
    plan["retired"] = plan["phase2_retired"] = sorted(RETIRABLE_SUITES)
    plan["counts"]["phase2"] = len(plan["phase2"])
    plan["counts"]["retired"] = len(plan["retired"])
    plan["execution_status"] = (
        "Historical eligibility inventory, not whole-product parity or acceptance. "
        "Nine whole inherited suites restored; five retired by Claude, review of #26, "
        "never passing. All 326 original paths remain in phase2 plus phase2_restored "
        "plus phase2_retired with original hashes. Merged main retains 30 qualification "
        "groups including phase2-step5-profile-management. Historical116/259 evidence unchanged."
    )
    # Preserve the compact one-row-per-suite map, rather than rewriting unrelated rows.
    text = (root / MAP_PATH).read_text()
    original = _json(text)
    for before, after in zip(original["entries"], mapping["entries"], strict=True):
        if before != after:
            compact = json.dumps(before, separators=(",", ":"))
            if compact in text:
                text = text.replace(compact, json.dumps(after, separators=(",", ":")), 1)
            else:
                text = text.replace(json.dumps(before), json.dumps(after), 1)
    if _json(text) != mapping:
        raise ValueError("suite map compact serialization changed; no data written")
    for path, content in ((MAP_PATH, text), (PLAN_PATH, json.dumps(plan, indent=2) + "\n")):
        target = root / path
        replacement = target.with_suffix(target.suffix + ".tmp")
        replacement.write_text(content)
        replacement.replace(target)


def record_pr35_review_retirements(root: Path) -> None:
    """Record precisely group A, preserving #26 and all original test bytes."""
    errors = validate(root)
    if errors:
        raise ValueError(f"retirement requires valid original accounting: {errors}")
    mapping = _json((root / MAP_PATH).read_bytes())
    plan = _json((root / PLAN_PATH).read_bytes())
    rows = {row["path"]: row for row in mapping["entries"]}
    entries = {entry["path"]: entry for entry in plan["entries"]}
    for path, (step, _) in PR35_RETIREMENTS.items():
        row, entry = rows[path], entries[path]
        if (row["status"] not in {"deferred", "retired"} or row["step"] != step
                or type(row["step"]) is not int
                or entry["classification"] not in {"phase2", "retired"}
                or _digest(_regular(root, path).read_bytes()) != row["inherited_sha256"]
                or entry["sha256"] != row["inherited_sha256"]):
            raise ValueError(f"retirement requires original held reviewed step bytes: {path}")
    for path, reason in PR35_RETIREMENT_REASONS.items():
        disposition = {"reviewer": PR35_REVIEWER, "reason": reason}
        rows[path].update(status="retired", reason=reason, blocked_on=None,
                          qualification_group="not-applicable-retired",
                          retirement=disposition.copy())
        rows[path].pop("pending_contract_disposition", None)
        entries[path].update(classification="retired", reason=reason,
                             retirement=disposition.copy())
    retired = set(plan.get("phase2_retired", [])) | set(PR35_RETIREMENTS)
    plan["phase2"] = sorted(set(plan["phase2"]) - set(PR35_RETIREMENTS))
    plan["phase2_retired"] = plan["retired"] = sorted(retired)
    plan["counts"]["phase2"] = len(plan["phase2"])
    plan["counts"]["retired"] = len(retired)
    if "phase2_retired" in plan["counts"]:
        plan["counts"]["phase2_retired"] = len(retired)
    mapping.pop("counts", None)
    plan["execution_status"] = (
        "Historical eligibility inventory, not whole-product parity or acceptance. "
        "Five whole suites retired by Claude, review of #26; exactly 21 additional "
        "group-A suites retired by Claude, review of #35, never passing. All 869 "
        "original test paths/bytes/hashes and historical 326 membership preserved. "
        "Case retirements in restored suites require exact review/source provenance."
    )
    # Keep the compact one-row-per-suite representation where present.
    before = (root / MAP_PATH).read_text()
    text = before
    original = _json(before)
    for old, new in zip(original["entries"], mapping["entries"], strict=True):
        if old != new:
            for separators in ((",", ":"), None):
                encoded = json.dumps(old, separators=separators)
                if encoded in text:
                    text = text.replace(encoded, json.dumps(new, separators=separators), 1)
                    break
    if _json(text) != mapping:
        text = json.dumps(mapping, indent=2) + "\n"
    for path, content in ((MAP_PATH, text), (PLAN_PATH, json.dumps(plan, indent=2) + "\n")):
        target = root / path
        replacement = target.with_suffix(target.suffix + ".tmp")
        replacement.write_text(content)
        replacement.replace(target)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "report", "record-review-retirements",
                                            "record-pr35-review-retirements"),
                        nargs="?", default="check")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if args.command == "record-review-retirements":
        record_review_retirements(args.root)
    elif args.command == "record-pr35-review-retirements":
        record_pr35_review_retirements(args.root)
    errors, counters = _evaluate(args.root)
    print(json.dumps({"command": args.command, "valid": not errors,
                      "errors": errors, "counts": counters}, indent=2, sort_keys=True))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
