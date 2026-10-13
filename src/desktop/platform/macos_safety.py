"""macOS: Odin's command governor with macOS's own command families.

macOS runs POSIX shells, so Odin's own assessment applies unchanged: its text patterns, its
structural shapes and its exfiltration rules. What it cannot know are macOS's own programs, so
this module raises Odin's assessment for those, each at the level Odin gives its Linux
counterpart and never stricter (D17): erasing or formatting a disk (diskutil, newfs_*, asr) as
mkfs, writing a raw disk device, disabling or flushing the pf firewall as ufw/iptables, a scripted
shutdown or restart as shutdown/reboot, launchctl as systemctl, Homebrew removal as apt removal,
directory-service user deletion and password changes as userdel/passwd, Time Machine and keychain
deletion as data deletion. Reading a credential is not raised, as on Linux. The checker is used
for commands run on this computer; remote hosts keep Odin's own governor. The signed audit label
stays Odin's pinned POSIX classification, which can be lower than these facts; the governor's
override notes still reach the outcome summaries (as on Windows).
"""
# ruff: noqa: E501
from __future__ import annotations

import re

from ...tools.risk_classifier import (
    _SUGGESTION_MAP,
    CommandFacts,
    CommandGovernor,
    CommandGovernorResult,
    RiskAssessment,
    RiskLevel,
    detect_unconditional_git_force_push,
    log,
)
from ...tools.risk_classifier import assess_command as posix_facts

_RANK = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}
_CRITICAL = [
    (re.compile(r"\bdiskutil\s+(?:\S+\s+)*?(?:eraseDisk|eraseVolume|zeroDisk|randomDisk|secureErase|partitionDisk|reformat|eraseCD)\b"), "filesystem format"),
    (re.compile(r"\bdiskutil\s+(?:apfs|ap)\s+(?:deleteContainer|eraseVolume|deleteVolume|deleteVolumeGroup)\b"), "filesystem format"),
    (re.compile(r"\bnewfs_[a-z0-9]+\b"), "filesystem format"),
    (re.compile(r"\basr\s+.*--erase\b"), "filesystem format"),
    (re.compile(r">\s*/dev/r?disk\d"), "write to block device"),
    (re.compile(r"\bpfctl\s+(?:\S+\s+)*?-[a-zA-Z]*d\b"), "firewall disable"),
    (re.compile(r"\bpfctl\s+(?:\S+\s+)*?-F\b"), "firewall flush"),
    (re.compile(r"\bsocketfilterfw\s+.*--setglobalstate\s+off\b"), "firewall disable"),
    (re.compile(r"\bosascript\b.*\bshut\s*down\b", re.IGNORECASE), "system shutdown"),
    (re.compile(r"\bosascript\b.*\brestart\b", re.IGNORECASE), "system reboot"),
]
_HIGH = [
    (re.compile(r"\blaunchctl\s+(?:bootout|unload|disable|kill|stop|remove)\b"), "service lifecycle change"),
    (re.compile(r"\bbrew\s+(?:uninstall|remove|rm|autoremove)\b"), "package removal"),
    (re.compile(r"\bdscl\s+\S+\s+-delete\s+/(?:Users|Groups)\b"), "user/group deletion"),
    (re.compile(r"\bsysadminctl\s+.*-deleteUser\b"), "user/group deletion"),
    (re.compile(r"\bdscl\s+\S+\s+-passwd\b"), "password change"),
    (re.compile(r"\bsysadminctl\s+.*-resetPasswordFor\b"), "password change"),
    (re.compile(r"\bpfctl\b"), "firewall rule change"),
    (re.compile(r"\bsocketfilterfw\b"), "firewall configuration"),
    (re.compile(r"\btmutil\s+(?:delete|deletelocalsnapshots|deleteinprogress|disable)\b"), "backup deletion"),
    (re.compile(r"\bsecurity\s+delete-keychain\b"), "keychain deletion"),
]


def _macos_family(command: str) -> RiskAssessment | None:
    for level, patterns in ((RiskLevel.CRITICAL, _CRITICAL), (RiskLevel.HIGH, _HIGH)):
        for pattern, reason in patterns:
            if pattern.search(command):
                return RiskAssessment(level, reason)
    return None


def assess_command(command: str) -> CommandFacts:
    """Odin's facts, raised (never lowered) by a macOS family match."""
    facts = posix_facts(command)
    family = _macos_family(command) if command else None
    if family is None or _RANK[family.level] <= _RANK[facts.assessment.level]:
        return facts
    category = "destructive" if family.level == RiskLevel.CRITICAL else facts.category
    floor = family.level if _RANK[family.level] > _RANK[facts.floor_level] else facts.floor_level
    return facts._replace(assessment=family, category=category, floor_level=floor)


class MacOSCommandGovernor(CommandGovernor):
    """Odin's governor policy, unchanged, over the macOS assessment (check lifted verbatim)."""

    def check(
        self,
        command: str,
        *,
        user_tier: str | None = None,
        host: str | None = None,
    ) -> CommandGovernorResult:
        """Check a command against the policy.

        Args:
            command: The shell command string.
            user_tier: Permission tier of the caller (admin/user/guest).
            host: Target host alias for per-host policy overrides.
        """
        if not command or not command.strip():
            return CommandGovernorResult(True, RiskLevel.LOW, "empty command")

        is_admin = user_tier == "admin"
        force_form = detect_unconditional_git_force_push(command)
        facts = assess_command(command)  # macOS families included
        assessment = facts.assessment

        host_policy = self._host_overrides.get(host, "") if host else ""
        # An elevation must not turn a historical strict-host HIGH denial into
        # an admin-overridden CRITICAL allow. Preserve the old exfil precedence
        # only when its raw floor actually matched and that flag is enabled.
        if (host_policy == "strict" and facts.floor_level == RiskLevel.HIGH
                and assessment.level == RiskLevel.CRITICAL
                and not (self._block_exfil and facts.floor_exfil) and force_form is None):
            result = CommandGovernorResult(
                False, assessment.level,
                f"{assessment.reason} (host '{host}' is strict-mode)",
                _SUGGESTION_MAP.get(assessment.reason, ""),
            )
            self._stats.record_block(command, result)
            log.warning("Governor BLOCKED (strict host %s): %s — %s", host,
                        assessment.reason, command[:200])
            return result

        if self._block_exfil and facts.exfil:
            reason = assessment.reason
            if is_admin and self._admin_can_override and force_form is None:
                log.warning(
                    "Governor ALLOWED (admin override, exfil): %s — %s", reason, command[:200],
                )
                self._stats.record_allow(command, assessment)
                return CommandGovernorResult(
                    True, RiskLevel.CRITICAL, f"{reason} (admin override)"
                )
            result = CommandGovernorResult(
                False, RiskLevel.CRITICAL, reason, _SUGGESTION_MAP.get(reason, ""),
            )
            self._stats.record_block(command, result)
            log.warning("Governor BLOCKED (exfil): %s — %s", reason, command[:200])
            return result

        # Precedence: exfil → critical (admin-overridable) → strict-host (HIGH only)
        if self._block_critical and assessment.level == RiskLevel.CRITICAL:
            if is_admin and self._admin_can_override and force_form is None:
                log.warning(
                    "Governor ALLOWED (admin override, critical): %s — %s",
                    assessment.reason,
                    command[:200],
                )
                self._stats.record_allow(command, assessment)
                return CommandGovernorResult(
                    True, RiskLevel.CRITICAL, f"{assessment.reason} (admin override)"
                )
            result = CommandGovernorResult(
                False,
                RiskLevel.CRITICAL,
                assessment.reason,
                _SUGGESTION_MAP.get(assessment.reason, ""),
            )
            self._stats.record_block(command, result)
            log.warning("Governor BLOCKED (critical): %s — %s", assessment.reason, command[:200])
            return result

        if force_form is not None:
            reason = f"unconditional git force push ({force_form})"
            result = CommandGovernorResult(
                False,
                RiskLevel.HIGH,
                reason,
                _SUGGESTION_MAP["unconditional git force push"],
            )
            self._stats.record_block(command, result)
            log.warning(
                "Governor BLOCKED (git force push): %s — %s",
                reason,
                command[:200],
            )
            return result

        if host_policy == "strict" and (
            assessment.level == RiskLevel.HIGH or facts.floor_level == RiskLevel.HIGH
        ):
            result = CommandGovernorResult(
                False,
                assessment.level,
                f"{assessment.reason} (host '{host}' is strict-mode)",
                _SUGGESTION_MAP.get(assessment.reason, ""),
            )
            self._stats.record_block(command, result)
            log.warning(
                "Governor BLOCKED (strict host %s): %s — %s", host, assessment.reason, command[:200]
            )
            return result

        if assessment.level == RiskLevel.HIGH:
            self._stats.record_allow(command, assessment)
            log.info("Governor ALLOWED (high risk): %s — %s", assessment.reason, command[:120])

        return CommandGovernorResult(True, assessment.level, assessment.reason)


def govern_command(self, command: str, host: str | None = None) -> tuple[bool, str, str]:
    """``ToolExecutor._govern_command`` on macOS: this computer's commands meet the macOS
    checker; remote hosts and a disabled governor keep Odin's own path."""
    from ...tools.executor import ToolExecutor, _host_lease_ctx
    from ...tools.ssh import is_local_address

    original = ToolExecutor._govern_command.linux_original
    baseline = getattr(self, "command_governor", None)
    if not baseline:
        return original(self, command, host)
    active = _host_lease_ctx.get()
    target = (active.target if active is not None
              and host in {active.target.alias, active.target.address} else None)
    if target is None and host is not None:
        registry = getattr(self, "host_registry", None)
        target = registry.get(host, targetable_only=True) if registry is not None else None
    if not (target is not None and is_local_address(target.address)
            or target is None and host is not None and is_local_address(host)):
        return original(self, command, host)
    governor = MacOSCommandGovernor.__new__(MacOSCommandGovernor)
    governor.__dict__.update(baseline.__dict__)
    manager = getattr(self, "_permission_manager", None)
    check = governor.check(command, user_tier="admin" if manager is not None and manager.is_owner(
        self._current_user_id) else None, host=host)
    if not check.allowed:
        return False, check.denial_message(), ""
    note = ""
    if check.risk.value in ("high", "critical"):
        note = f"[governor: allowed — {check.risk.value} risk, {check.reason}]\n"
    return True, "", note
