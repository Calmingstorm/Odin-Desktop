"""Root surface strip and upstream safety-byte preservation."""

import ast
from pathlib import Path

import pytest

from scripts.maintenance.inventory import baseline_blobs

ROOT = Path(__file__).resolve().parents[1]


def baseline(path):
    return baseline_blobs(ROOT)[path].decode()


def functions(text):
    return {
        node.name: ast.get_source_segment(text, node)
        for node in ast.parse(text).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def test_containment_finalizers_are_source_identical():
    old = functions(baseline("src/__main__.py"))
    new = functions((ROOT / "src/__main__.py").read_text())
    for name in (
        "_enable_process_containment", "_safe_repr", "_finalize_loop",
        "_FinalizeWatchdog", "_arm_finalize_watchdog", "_disarm_finalize_watchdog",
        "_finalize_and_exit", "_emergency_exit",
    ):
        assert new[name] == old[name], name


def test_response_guard_only_approved_wording_changes():
    old = baseline("src/discord/response_guards.py")
    expected = old.replace(
        "# Additional patterns for scrubbing LLM responses before Discord delivery.",
        "# Additional patterns for scrubbing LLM responses before conversation delivery.",
    ).replace(
        "Scrub potential secrets from LLM responses before sending to Discord.",
        "Scrub potential secrets from LLM responses before sending to the conversation.",
    )
    assert (ROOT / "src/discord/response_guards.py").read_text() == expected


@pytest.mark.parametrize("path", [
    "completion", "housekeeping", "llm_gateway", "mcp_dispatch", "turn_recorder",
    "steer_notifications", "scheduled_context", "tool_catalog",
])
def test_retained_neutral_modules_byte_identical(path):
    source = f"src/discord/{path}.py"
    expected = baseline(source)
    if path == "tool_catalog":
        # Readiness-filtered publication cannot reserve the complete static
        # namespace. This reviewed pending adaptation is exact, not a blanket
        # exemption for the real retained catalog or its merge/cache algorithms.
        substitutions = (
            (
                '        static_names = {t["name"] for t in builtin}\n'
                '        if computer_cfg is not None and computer_cfg.enabled:\n'
                '            static_names.update({"computer_session", "computer_observe", '
                '"computer_act"})\n',
                '        from ..tools.builtin_policy import BUILTIN_TOOL_NAMES\n\n'
                '        static_names = set(BUILTIN_TOOL_NAMES)\n',
            ),
            (
                '        # analyze_pdf: PyMuPDF lives in the optional `pdf` extra, and no\n'
                '        # install path used to install extras — so the tool was advertised on\n'
                '        # every install while its dependency was present on none of them, and\n'
                '        # calls died with "No module named \'fitz\'". Structural availability\n'
                '        # only; the handler still converts a load failure '
                'into a clean result,\n'
                '        # because find_spec proves the module is importable, not that the\n'
                '        # native library loads.\n',
                '        # Required bundled dependencies still need a structural readiness check.\n'
                '        # Importability is not proof the native library '
                'or packaged assets load.\n',
            ),
            (
                '                "analyze_pdf hidden from the tool catalog: PyMuPDF is not "\n'
                '                "installed. Install the \'pdf\' extra to enable it "\n'
                '                "(pip install \'.[pdf]\')."\n',
                '                "analyze_pdf hidden from the tool catalog: required bundled "\n'
                '                "PyMuPDF is unavailable; repair the desktop installation."\n',
            ),
        )
        for before, after in substitutions:
            assert expected.count(before) == 1
            expected = expected.replace(before, after, 1)
    assert (ROOT / source).read_text() == expected


def test_root_entrypoints_gate_before_operations(monkeypatch):
    from src import __main__, cli, restart, setup_wizard
    from src.discord.delivery import DeliveryService

    monkeypatch.setattr(__main__.sys, "argv", ["desktop"])
    for entry in (__main__.main, cli.main):
        with pytest.raises(SystemExit) as rejected:
            entry()
        assert rejected.value.code == 2
    for entry in (setup_wizard.is_setup_needed, DeliveryService):
        with pytest.raises(RuntimeError, match="Phase 2"):
            entry()
    restart.reset()
    restart.block_reexec("unverified descendants")
    with pytest.raises(RuntimeError, match="unproven teardown"):
        restart.reexec()
    restart.reset()


def test_error_formatter_neutral_total_and_bounded():
    from src.error_presentation import format_user_facing_error, sanitize_error_text

    class BadStringError(Exception):
        def __str__(self):
            raise ValueError("unreadable")

    assert format_user_facing_error(BadStringError()) == "BadStringError"
    assert format_user_facing_error(ValueError("<html>invalid</html>")) == "ValueError"
    assert len(format_user_facing_error(ValueError("x" * 1000))) == 200
    assert sanitize_error_text("clean\x01detail\nignored") == "cleandetail"


def test_environment_private_writer_shared_contract(tmp_path):
    from src.setup_wizard import write_env_file

    path = tmp_path / "environment"
    write_env_file(path, "LOCAL_SETTING=example\n")
    assert path.read_text() == "LOCAL_SETTING=example\n"
    assert path.stat().st_mode & 0o777 == 0o600


def test_workspace_preflight_failure_is_closed_without_live_provisioning(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from src import __main__
    from src.tools import workspace

    def unavailable(*args, **kwargs):
        raise workspace.WorkspaceError("isolated fixture unavailable")

    monkeypatch.setattr(workspace, "provision_startup_workspace", unavailable)
    monkeypatch.setattr(__main__, "_command_protected_roots", lambda config: [])
    config = SimpleNamespace(tools=SimpleNamespace(local_working_dir="fixture"))
    assert __main__._provision_command_workspace(config, Mock()) is None


def test_removed_transport_and_models_absent():
    for path in (
        "src/database/repository.py", "src/models/guild.py", "src/models/user.py",
        "src/models/infraction.py", "src/models/reminder.py", "src/discord/client.py",
        "src/discord/connection_supervisor.py", "src/discord/channel_config.py",
        "src/discord/discordpy_adapter.py", "src/discord/helpers/cooldowns.py",
        "src/discord/cogs/scheduled_report_pagination.py",
        "src/discord/views/confirm.py", "src/discord/views/role_select.py",
        "src/packaging/validate.py",
    ):
        assert not (ROOT / path).exists(), path


def test_prompt_recent_actions_use_explicit_conversation_not_transport_object():
    import inspect

    from src.discord.prompts import PromptBuilder

    for method in (PromptBuilder.build_full_prompt, PromptBuilder.build_chat_prompt):
        assert "conversation_id" in inspect.signature(method).parameters
        assert "channel" not in inspect.signature(method).parameters
    source = inspect.getsource(PromptBuilder.build_full_prompt)
    assert "recent_entries(conversation_id)" in source
    assert "channel.id" not in source
