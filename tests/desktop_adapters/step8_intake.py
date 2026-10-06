"""Whole-suite frozen intake blocker audit, not a fabricated product adapter."""
from __future__ import annotations

import ast
import copy
import hashlib

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source

SUITES = {
    "characterization/test_intake_gating": (
        "607ebffddbd77754c3d81a2705297ef1dfe54f30194b01ec7ad5294cf2350808"
    ),
    "test_campaign_cli_coverage": (
        "fe47a4c99af2c48f8bf397a0634830b82c5afa50e74ab53eb0fb26864a434d0b"
    ),
    "test_channel_privacy_campaign": (
        "88e6a8d5c7dad7a3d74f168d39300e20ad4f576d19c4ff49858c7e0358908bb6"
    ),
    "test_chat_session": "aab21c70a29d895a95c8087ed2279c390954513058c08032db18cb310578b284",
    "test_intake_pipeline": "4468540aeb50a719a15b70f8c4d9b9e38ef69f13d82220c5c3e1667f2970d386",
    "test_native_channel_ops": "1b423e5691516937e288395633547d8ac907c0732408af12f4c1b7233799fe15",
    "test_sessions_review_regressions": (
        "68cb855877714567c839ac983b2294ae1121ee48e94e504a7e597605187f4535"
    ),
    "test_typing_resilience": "af3ca9c9d79e3996938dd257368d602746481e3967b3401e2006b16266d5d5ba",
    "test_web_chat": "64df3b00cc5a23bdc75238190c6e976bb0ce7278f81d230f299de8d8edd3f188",
}
CORPUS_SELECTIONS = {
    "characterization/test_intake_gating": None,
    "test_campaign_cli_coverage": None,
    "test_channel_privacy_campaign": None,
    "test_chat_session": None,
    "test_intake_pipeline": None,
    "test_native_channel_ops": None,
    "test_sessions_review_regressions": None,
    "test_typing_resilience": None,
    "test_web_chat": None,
}
CORPUS_EXCLUSIONS = {}
SETUP_HUNKS = {}
BLOCKERS = {
    "characterization/test_intake_gating": (
        "make_bot requires removed src.discord.client.OdinBot; "
        "MessageIntake.handle fails closed and lacks allowlist/mention/bot-buffering gates. "
        "RequestService has no guild/channel precedence or non-owner bot/webhook-origin "
        "admission matrix."
    ),
    "test_campaign_cli_coverage": (
        "src.cli delegates to diagnostic-only LocalClient.main: no piped/empty prompt "
        "submission, JSON/prose prompt output, prompt timeout, urllib request surface or "
        "legacy_server_arguments. Missing prompt client cannot be implemented in a test shim."
    ),
    "test_channel_privacy_campaign": (
        "MessageIntake.handle rejects before redaction; ChannelLogger requires "
        "conversation_id/owner_id/participant/role, not legacy guild/DM origin. No authentic "
        "delete-failure and user/own/bot/DM ingress equivalent preserves this whole suite."
    ),
    "test_chat_session": (
        "create_api_routes and process_web_chat fail closed. Desktop has one authenticated "
        "profile owner, not arbitrary token identities, tier/tool/host propagation or "
        "web:user:session visibility. Recreating routes and RBAC would fake product behavior."
    ),
    "test_intake_pipeline": (
        "MessageIntake lacks is_allowed_user/is_allowed_channel; handle and "
        "_process_attachments reject through _require_phase2_admission. Desktop "
        "submissions/attachments lack legacy allowlist, message deletion and notification "
        "semantics."
    ),
    "test_native_channel_ops": (
        "ChannelOpsTools only accepts read_visible_history and exposes "
        "_handle_read_conversation. Purge/read_channel/reaction/poll/set_permission are "
        "absent. Foreign-channel reads and tier mutations cannot be recreated by privileged "
        "shims; parent owns retirement review."
    ),
    "test_sessions_review_regressions": (
        "register_chat/register_sessions/process_web_chat fail closed. Whole suite includes "
        "identity-scoped route search and ephemeral execute lifetime; exporting pure "
        "session/search cases alone is forbidden. Desktop durable submission is not ephemeral "
        "HTTP execute or tier-based visibility."
    ),
    "test_typing_resilience": (
        "Whole suite invokes MessagePipeline._run_inner, which rejects through "
        "_require_phase2_admission, and expects legacy guest/Discord error delivery. No "
        "setup-only mapping preserves every indicator count, error-string and silence "
        "assertion without bypassing admission or selecting runner-only subsets."
    ),
    "test_web_chat": (
        "src.web.chat only exports fail-closed process_web_chat. "
        "WebMessage/_WebChannel/_WebAuthor/_WebSentMessage/_NoOpContextManager/"
        "MAX_CHAT_CONTENT_LEN are absent; EngineRequest/LocalChannel do not implement legacy "
        "base64 capture/presentation. Implementing missing classes in tests is forbidden."
    ),
}


class WholeSuiteBlockedError(RuntimeError):
    """No original execution or partial export is authorized."""


def prepare(stem, *, original=None, adapted=None):
    """Verify archive/retained bytes and the entire AST without importing tests."""
    if stem not in SUITES:
        raise ValueError("Unassigned intake suite")
    source = frozen_source(f"tests/{stem}.py")
    if hashlib.sha256(source).hexdigest() != SUITES[stem]:
        raise ValueError("Intake frozen source hash mismatch")
    pinned = ast.parse(source)
    original = copy.deepcopy(pinned) if original is None else original
    if dump(original) != dump(pinned):
        raise ValueError("Intake original AST drift")
    adapted = copy.deepcopy(original) if adapted is None else adapted
    if corpus(adapted) != corpus(original):
        raise ValueError("Intake assertion/signature/decorator/parameter drift")
    if dump(adapted) != dump(original):
        raise ValueError("Intake setup AST outside exact empty hunk allowlist")
    return original, adapted


def load(namespace, stem):
    """Fail before compile/exec/export. This is not an executable adapter."""
    prepare(stem)
    raise WholeSuiteBlockedError(BLOCKERS[stem])
