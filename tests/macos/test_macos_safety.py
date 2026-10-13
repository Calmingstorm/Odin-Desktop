"""The macOS governor: Odin's verdicts, raised for macOS's own programs, never lowered."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.desktop.platform import macos_safety
from src.tools.risk_classifier import CommandGovernor, RiskLevel


@pytest.mark.parametrize("command,reason", [
    ("diskutil eraseDisk APFS Blank disk4", "filesystem format"),
    ("sudo diskutil zeroDisk disk4", "filesystem format"),
    ("diskutil apfs deleteContainer disk5", "filesystem format"),
    ("newfs_apfs /dev/disk4s1", "filesystem format"),
    ("asr restore --source a.dmg --target /Volumes/X --erase", "filesystem format"),
    ("cat image > /dev/rdisk4", "write to block device"),
    ("sudo pfctl -d", "firewall disable"),
    ("pfctl -F all", "firewall flush"),
    ("socketfilterfw --setglobalstate off", "firewall disable"),
    ("osascript -e 'tell application \"System Events\" to shut down'", "system shutdown"),
    ("osascript -e 'tell app \"System Events\" to restart'", "system reboot"),
])
def test_macos_disk_firewall_and_power_commands_are_critical(command, reason):
    facts = macos_safety.assess_command(command)
    assert (facts.assessment.level, facts.assessment.reason) == (RiskLevel.CRITICAL, reason)
    assert facts.category == "destructive" and facts.floor_level == RiskLevel.CRITICAL


@pytest.mark.parametrize("command,reason", [
    ("launchctl bootout gui/501/com.example.agent", "service lifecycle change"),
    ("brew uninstall node", "package removal"),
    ("sudo dscl . -delete /Users/guest", "user/group deletion"),
    ("sudo sysadminctl -deleteUser guest", "user/group deletion"),
    ("dscl . -passwd /Users/me old new", "password change"),
    ("sudo pfctl -sr", "firewall rule change"),
    ("tmutil deletelocalsnapshots /", "backup deletion"),
    ("security delete-keychain build.keychain", "keychain deletion"),
])
def test_macos_service_package_account_and_data_commands_are_high(command, reason):
    facts = macos_safety.assess_command(command)
    assert (facts.assessment.level, facts.assessment.reason) == (RiskLevel.HIGH, reason)


@pytest.mark.parametrize("command,level", [
    ("rm -rf /", RiskLevel.CRITICAL),          # Odin's own verdict stays
    ("diskutil list", RiskLevel.LOW),
    ("brew install jq", RiskLevel.LOW),
    ("security find-generic-password -s x -w", RiskLevel.LOW),  # a read, as on Linux
    ("launchctl list", RiskLevel.LOW),
    ("", RiskLevel.LOW),
])
def test_odins_verdicts_are_never_lowered_and_reads_are_not_raised(command, level):
    assert macos_safety.assess_command(command).assessment.level == level


def test_a_raised_high_never_hides_odins_critical():
    facts = macos_safety.assess_command("brew uninstall jq; rm -rf /")
    assert facts.assessment.level == RiskLevel.CRITICAL


def _executor(owner: bool, address: str):
    governor = CommandGovernor()
    registry = SimpleNamespace(get=lambda alias, targetable_only=True: SimpleNamespace(
        alias=alias, address=address))
    manager = SimpleNamespace(is_owner=lambda user: owner)
    return SimpleNamespace(command_governor=governor, host_registry=registry,
                           _permission_manager=manager, _current_user_id="owner")


def test_this_computer_meets_the_macos_checker_with_odins_admin_override():
    allowed, denial, note = macos_safety.govern_command(_executor(False, "127.0.0.1"),
                                                        "diskutil eraseDisk APFS X disk4",
                                                        "localhost")
    assert not allowed and "filesystem format" in denial
    allowed, denial, note = macos_safety.govern_command(_executor(True, "127.0.0.1"),
                                                        "diskutil eraseDisk APFS X disk4",
                                                        "localhost")
    assert allowed and note.startswith("[governor: allowed — critical risk, filesystem format")


def test_a_remote_host_keeps_odins_own_governor():
    from src.tools.executor import ToolExecutor

    assert ToolExecutor._govern_command.darwin_target == \
        "src.desktop.platform.macos_safety:govern_command"
    allowed, _, note = macos_safety.govern_command(_executor(False, "192.0.2.10"),
                                                   "diskutil eraseDisk APFS X disk4", "box")
    assert allowed and note == ""  # Odin's POSIX checker does not know diskutil
    no_governor = SimpleNamespace(command_governor=None)
    assert macos_safety.govern_command(no_governor, "anything", "localhost") == (True, "", "")
