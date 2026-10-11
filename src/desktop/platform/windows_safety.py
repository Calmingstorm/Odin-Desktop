"""Bounded offline Windows PowerShell 5.1/cmd facts, not language proof.

Literal heads, quotes, comments, pipes, blocks, subexpressions and UTF-16LE shell
wrappers are recognized. Caller aliases/functions, splats, computed names, delayed
expansion and arbitrary program/.NET semantics are not resolved. Unknown programs
are not refused just for being unknown. Bounds: 256 KiB, 16 levels, 4096 segments.
The original signed audit path remains; its pinned POSIX label may differ from
Windows facts, but governor override notes remain in signed outcome summaries.
Fetch plus expression execution in one source is conservatively co-occurrence,
not proven dataflow. Literal download filenames are tracked only within this
source, case-insensitively, without resolving filesystem identities or variables.
Windows native argument reconstruction is bounded, not a full cmd/PS argv model.
Some unchanged callers discard governor notes; no universal audit annotation is
claimed. CRITICAL recognition bounds retain Odin's configured admin override.
"""
# ruff: noqa: E501
from __future__ import annotations

import base64
import binascii
import re
import shlex
from dataclasses import dataclass, field

from ...tools.risk_classifier import (
    _SUGGESTION_MAP,
    CommandFacts,
    CommandGovernor,
    CommandGovernorResult,
    RiskAssessment,
    RiskLevel,
    log,
)
from ...tools.risk_classifier import (
    assess_command as posix_facts,
)
from ...tools.risk_classifier import (
    detect_unconditional_git_force_push as posix_force_push,
)

MAX_SOURCE = 256 * 1024
MAX_DEPTH = 16
MAX_SEGMENTS = 4096
_RANK = {level: index for index, level in enumerate(RiskLevel)}
_ALIASES = {
    "rm": "remove-item", "ri": "remove-item", "del": "remove-item",
    "erase": "remove-item", "rd": "remove-item", "rmdir": "remove-item",
    "iex": "invoke-expression", "iwr": "invoke-webrequest", "irm": "invoke-restmethod",
    "curl": "invoke-webrequest", "wget": "invoke-webrequest", "cat": "get-content",
    "gc": "get-content", "type": "get-content", "sc": "set-content",
    "ac": "add-content", "kill": "stop-process", "spps": "stop-process",
    "start": "start-process", "saps": "start-process",
}
_SENSITIVE = re.compile(
    r"[\\/]\.(?:ssh|aws|azure|kube)(?:[\\/]|\b)|id_rsa|id_ed25519|"
    r"[\\/]\.config[\\/]gcloud[\\/]|[\\/]system32[\\/]config[\\/](sam|security|system)\b|"
    r"(?:hklm:|registry::hkey_local_machine)[\\/](?:sam|security)(?:[\\/]|$)|"
    r"[\\/]microsoft[\\/](credentials|vault|protect)[\\/]|"
    r"[\\/](login data|logins\.json|key4\.db|shadow|sudoers)\b", re.I)
_ROOT = re.compile(r"^(?:[a-z]:[\\/](?:\*(?:\.\*)?)?|[\\/](?:\*(?:\.\*)?)?|\$(?:env:)?(?:systemdrive|windir|systemroot)(?:[\\/]\*(?:\.\*)?)?)$", re.I)
_METADATA = re.compile(r"169\.254\.169\.254|169\.254\.170\.2|metadata\.google\.internal|100\.100\.100\.200|fd00:ec2::254", re.I)


class _BoundError(ValueError):
    pass


@dataclass
class _Word:
    value: str
    quoted: bool = False


@dataclass
class _Segment:
    words: list[_Word] = field(default_factory=list)
    upstream: _Segment | None = None
    called: bool = False


def _facts(level=RiskLevel.LOW, reason="no risky patterns detected", category="risk", exfil=False):
    return CommandFacts(RiskAssessment(level, reason), category, exfil, level, exfil)


def _segments(source: str, shell="powershell", depth=0) -> list[_Segment]:
    if len(source) > MAX_SOURCE or depth > MAX_DEPTH:
        raise _BoundError
    result = []
    current = _Segment()
    word = []
    started = quoted = False
    quote = None
    index = 0

    def finish_word():
        nonlocal started, quoted
        if started:
            current.words.append(_Word("".join(word), quoted))
        word.clear()
        started = quoted = False

    def finish(pipe=False):
        nonlocal current
        finish_word()
        if current.words:
            result.append(current)
        if len(result) > MAX_SEGMENTS:
            raise _BoundError
        current = _Segment(upstream=current if pipe else None)

    while index < len(source):
        char = source[index]
        if shell == "powershell" and quote != "'" and source.startswith("$(", index):
            end, nesting, inner = index + 2, 1, None
            while end < len(source) and nesting:
                c = source[end]
                if c == "`" and inner != "'":
                    end += 2
                    continue
                if inner:
                    if c == inner:
                        inner = None
                elif c in "\"'":
                    inner = c
                elif c == "(":
                    nesting += 1
                elif c == ")":
                    nesting -= 1
                end += 1
            if nesting:
                raise _BoundError
            result.extend(_segments(source[index + 2:end - 1], shell, depth + 1))
            word.append("$expression")
            started = True
            index = end
            continue
        if char == ("^" if shell == "cmd" else "`") and quote != "'" and index + 1 < len(source):
            if source[index + 1] not in "\r\n":
                word.append(source[index + 1])
                started = True
            index += 2
            continue
        if quote:
            if char == quote:
                if quote == "'" and shell == "powershell" and source[index:index + 2] == "''":
                    word.append("'")
                    index += 2
                    continue
                quote = None
            else:
                word.append(char)
            index += 1
            continue
        if shell == "powershell" and source.startswith("<#", index):
            end = source.find("#>", index + 2)
            if end < 0:
                raise _BoundError
            index = end + 2
            continue
        if shell == "powershell" and char == "#" and not started:
            end = source.find("\n", index)
            index = len(source) if end < 0 else end
            continue
        if char in ('"', "'") and (shell != "cmd" or char == '"'):
            quote = char
            started = quoted = True
        elif char in ";|&\n\r{}()":
            if char == "&" and current.words and current.words[-1].value == "=":
                current.called = True
                index += 1
                continue
            if char == "&" and started and word and word[-1] == "=":
                finish_word()
                current.words[-1].value = current.words[-1].value[:-1]
                current.words.append(_Word("="))
                current.called = True
                index += 1
                continue
            if char == "&" and not current.words and not started:
                current.called = True
            else:
                finish(char == "|")
        elif char.isspace():
            finish_word()
        else:
            word.append(char)
            started = True
        index += 1
    if quote:
        raise _BoundError
    finish()
    if len(result) > MAX_SEGMENTS:
        raise _BoundError
    return result


def _head(segment: _Segment, shell: str):
    if segment.words and shell == "powershell":
        words = segment.words
        if len(words) >= 3 and words[0].value.startswith("$") and words[1].value == "=":
            segment = _Segment(words=words[2:], upstream=segment.upstream, called=segment.called)
        elif len(words) >= 2 and re.fullmatch(r"\$[\w:]+=[^=].*", words[0].value):
            segment = _Segment(words=[_Word(words[0].value.split("=", 1)[1]), *words[1:]],
                               upstream=segment.upstream, called=segment.called)
    if not segment.words or segment.words[0].quoted and not segment.called and shell != "cmd":
        return "", []
    name = segment.words[0].value.lower().replace("/", "\\").rsplit("\\", 1)[-1]
    if shell == "cmd":
        name = name.lstrip("@")
        match = re.fullmatch(r"(@?(?:del|erase|rd|rmdir))((?:/[a-z])+)", segment.words[0].value, re.I)
        if match:
            segment = _Segment(words=[_Word(match[1].lstrip("@")),
                                     *[_Word(a) for a in re.findall(r"/[a-z]", match[2], re.I)],
                                     *segment.words[1:]], called=segment.called)
            name = match[1].lstrip("@").lower()
    if name.endswith((".exe", ".com")):
        name = name[:-4]
    elif shell != "cmd":
        name = _ALIASES.get(name, name)
    return name, [w.value for w in segment.words[1:]]


def _param(args, name, minimum=2):
    return any(a.startswith("-") and len(p := a.lstrip("-").split(":", 1)[0].lower()) >= minimum
               and name.startswith(p) and not a.lower().endswith(":$false") for a in args)


def _value(args, name):
    for i, arg in enumerate(args):
        if arg.startswith("-") and name.startswith(arg[1:].lower()) and len(arg) > 2:
            return args[i + 1] if i + 1 < len(args) else None
    return None


def _scan(command, shell="powershell", depth=0):
    if depth > MAX_DEPTH:
        raise _BoundError
    findings = [_facts()]
    force = None
    segments = _segments(command, shell, depth)
    fetched = any(_head(s, shell)[0] in {"invoke-webrequest", "invoke-restmethod", "curl", "wget"} for s in segments)
    downloads = set()
    for segment in segments:
        name, args = _head(segment, shell)
        lower = [a.lower() for a in args]
        text = " ".join(args)
        sensitive = bool(_SENSITIVE.search(text))
        upstream, upstream_args = _head(segment.upstream, shell) if segment.upstream else ("", [])

        def add(level, reason, category="risk", exfil=False):
            findings.append(_facts(level, reason, category, exfil))

        if name in {"invoke-webrequest", "invoke-restmethod", "curl", "wget", "start-bitstransfer"}:
            destination = _value(args, "outfile") or _value(args, "destination")
            if name in {"curl", "wget"}:
                for i, a in enumerate(args[:-1]):
                    if a in {"-o", "-O", "--output"}:
                        destination = args[i + 1]
            if destination and re.search(r"https?://", text, re.I):
                downloads.add(destination.casefold())
        if downloads and (segment.called and segment.words[0].value.casefold() in downloads
                          or name in {"powershell", "pwsh"} and any(a.casefold() in downloads for a in args)
                          or name in {"invoke-expression", "start-process", "python", "python3", "node", "wscript", "cscript"} and any(a.casefold() in downloads for a in args)):
            add(RiskLevel.CRITICAL, "downloaded script execution", "remote_execution", True)

        if name in {"powershell", "pwsh", "cmd", "invoke-expression", "start-process"}:
            nested, nested_shell = None, shell
            if name == "cmd":
                for i, arg in enumerate(lower):
                    if arg in {"/c", "/k"}:
                        nested, nested_shell = " ".join(args[i + 1:]), "cmd"
                        break
                    if arg.startswith(("/c", "/k")) and len(arg) > 2:
                        nested, nested_shell = " ".join([args[i][2:], *args[i + 1:]]), "cmd"
                        break
            elif name in {"powershell", "pwsh"}:
                for i, arg in enumerate(lower):
                    p = arg.lstrip("-")
                    if arg.startswith("-") and (p == "e" or "encodedcommand".startswith(p) and len(p) >= 2):
                        try:
                            nested = base64.b64decode(args[i + 1], validate=True).decode("utf-16-le")
                        except (IndexError, ValueError, binascii.Error, UnicodeError):
                            add(RiskLevel.CRITICAL, "opaque encoded shell command")
                        break
                    if arg.startswith("-") and (p == "c" or "command".startswith(p) and len(p) >= 2):
                        nested = " ".join(args[i + 1:])
                        break
                if nested is None:
                    add(RiskLevel.HIGH, "arbitrary script execution")
            elif name == "start-process":
                cleaned = [a.replace(",", " ") for a in args if a.lower() not in {"-filepath", "-argumentlist", "-wait", "-nonewwindow"}]
                if cleaned and not cleaned[0].startswith("$"):
                    nested = " ".join(cleaned)
                add(RiskLevel.HIGH, "process launch")
            elif upstream in {"invoke-webrequest", "invoke-restmethod", "curl", "wget", "get-content"}:
                add(RiskLevel.CRITICAL, "pipe remote script to shell", "remote_execution", True)
            elif re.search(r"download(?:string|file)|https?://|frombase64string", text, re.I):
                add(RiskLevel.CRITICAL, "remote/decoded expression execution", "remote_execution", True)
            elif args and not args[0].startswith("$"):
                nested = " ".join(args[1:] if _param(args[:1], "command", 1) else args)
            else:
                add(RiskLevel.CRITICAL, "opaque expression execution", "remote_execution", fetched)
            if name == "invoke-expression" and fetched:
                add(RiskLevel.CRITICAL, "pipe remote script to shell", "remote_execution", True)
            if nested is not None:
                facts, nested_force = _scan(nested, nested_shell, depth + 1)
                findings.append(facts)
                force = force or nested_force
            continue
        if not name:
            continue
        if name in {"remove-item", "del", "erase", "rd", "rmdir"}:
            targets = [re.sub(r"^-(?:path|literalpath):|^filesystem::", "", a.strip(), flags=re.I).rstrip(".")
                       for arg in args for a in arg.split(",")]
            if any(_ROOT.fullmatch(a) or re.fullmatch(r"%(systemdrive|systemroot|windir)%(?:[\\/]\*(?:\.\*)?)?", a, re.I) for a in targets):
                add(RiskLevel.CRITICAL, "recursive delete on root", "destructive")
            elif _param(args, "recurse", 1) or "/s" in lower:
                add(RiskLevel.HIGH, "recursive delete", "destructive")
            elif _param(args, "force", 1) or "/f" in lower or "/q" in lower:
                add(RiskLevel.HIGH, "forced delete", "destructive")
            else:
                add(RiskLevel.MEDIUM, "file deletion")
        elif name in {"format-volume", "format", "clear-disk", "initialize-disk", "diskpart", "sdelete"} or name == "cipher" and any(a.startswith("/w") for a in lower):
            add(RiskLevel.CRITICAL, "filesystem format" if name.startswith("format") else "raw disk write", "destructive")
        elif name in {"stop-computer", "restart-computer", "shutdown"} and "/a" not in lower:
            add(RiskLevel.CRITICAL, "system reboot" if name == "restart-computer" or "/r" in lower else "system shutdown", "destructive")
        elif name in {"stop-service", "restart-service", "set-service", "stop-process", "taskkill", "remove-localuser", "remove-localgroup", "icacls", "takeown"}:
            add(RiskLevel.HIGH, "service lifecycle change" if "service" in name else "process/account/permission change")
        elif name in {"set-netfirewallprofile", "netsh"}:
            if name == "set-netfirewallprofile" and "false" in text.lower() or name == "netsh" and "firewall" in text.lower() and ("off" in lower or "reset" in lower):
                add(RiskLevel.CRITICAL, "firewall disable", "destructive")
            else:
                add(RiskLevel.HIGH, "firewall configuration")
        elif name == "reg" and lower and lower[0] in {"delete", "add", "import"}:
            add(RiskLevel.HIGH, "registry modification")
        elif name in {"set-content", "clear-content", "add-content", "out-file", "new-item", "copy-item", "move-item", "set-itemproperty", "remove-itemproperty"}:
            add(RiskLevel.MEDIUM, "file/registry mutation")
        if name in {"get-content", "type", "get-item", "get-itemproperty", "reg", "cmdkey", "vaultcmd", "mimikatz", "procdump"}:
            if sensitive or name in {"cmdkey", "vaultcmd", "mimikatz"} or name == "procdump" and "lsass" in text.lower() or name == "reg" and re.search(r"hklm[\\/](sam|security)\b", text, re.I):
                add(RiskLevel.CRITICAL, "credential store access", "credential_access", True)
        if name in {"invoke-webrequest", "invoke-restmethod", "curl", "wget", "bitsadmin", "start-bitstransfer", "certutil"}:
            if _METADATA.search(text):
                add(RiskLevel.CRITICAL, "cloud metadata request", "credential_access", True)
            upload = (_param(args, "infile") or _param(args, "body") or "upload" in lower or "/upload" in lower
                      or any(a in {"-t", "--upload-file", "-d", "--data", "--data-binary", "--json", "-f", "--form"}
                             or a.startswith(("--upload-file=", "--data=", "--data-binary=", "--form=", "--json="))
                             or len(a) > 2 and a[:2] in {"-t", "-d", "-f"} and not a.startswith("--") for a in lower))
            if upload and (sensitive or _SENSITIVE.search(" ".join(upstream_args))):
                add(RiskLevel.CRITICAL, "sensitive file upload", "exfiltration", True)
            elif upload:
                add(RiskLevel.MEDIUM, "HTTP data upload")
        if name in {"scp", "sftp", "rclone", "azcopy", "aws", "az", "gsutil"} and sensitive:
            add(RiskLevel.CRITICAL, "sensitive file upload", "exfiltration", True)
        if name in {"copy-item", "move-item", "copy", "move", "robocopy", "xcopy"} and sensitive and any(a.startswith("\\\\") for a in args):
            add(RiskLevel.CRITICAL, "sensitive file upload", "exfiltration", True)
        if name in {"ssh", "psexec", "winrs", "invoke-command", "enter-pssession"}:
            add(RiskLevel.HIGH, "remote command execution", "remote_execution")
        if name in {"git", "docker", "dd", "mkfs", "sqlcmd", "mysql", "psql", "nc", "ncat"}:
            canonical = " ".join(shlex.quote(a) for a in [name, *args])
            findings.append(posix_facts(canonical))
            if name == "git":
                force = force or posix_force_push(canonical)
        if name in {"robocopy", "xcopy"} and any(a in {"/mir", "/purge"} for a in lower):
            add(RiskLevel.HIGH, "recursive synchronization deletes destination", "destructive")
        if name in {"python", "python3", "py", "node", "ruby", "perl", "wscript", "cscript", "mshta", "rundll32"}:
            add(RiskLevel.HIGH, "arbitrary script execution")
            if re.search(r"https?://|socket.*connect|downloadstring|invoke-expression", text, re.I):
                add(RiskLevel.CRITICAL, "remote script execution", "remote_execution", True)
    return max(findings, key=lambda f: (_RANK[f.assessment.level], f.exfil)), force


def assess_command(command: str) -> CommandFacts:
    if not command or not command.strip():
        return _facts(reason="empty command")
    try:
        return _scan(command)[0]
    except _BoundError:
        return _facts(RiskLevel.CRITICAL, "Windows command recognition bound or malformed quoting")


def detect_unconditional_git_force_push(command: str) -> str | None:
    try:
        return _scan(command)[1]
    except _BoundError:
        return None


def classify_command(command: str) -> RiskAssessment:
    return assess_command(command).assessment


class WindowsCommandGovernor(CommandGovernor):
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
        facts = assess_command(command)
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
    """Dispatch by target address; preserve original remote and disabled paths."""
    from ...tools.executor import ToolExecutor, _host_lease_ctx
    from ...tools.ssh import is_local_address

    original = getattr(ToolExecutor._govern_command, "linux_original", ToolExecutor._govern_command)
    baseline = getattr(self, "command_governor", None)
    if not baseline:
        return True, "", ""
    active = _host_lease_ctx.get()
    target = active.target if active is not None and host in {active.target.alias, active.target.address} else None
    if target is None and host is not None:
        registry = getattr(self, "host_registry", None)
        target = registry.get(host, targetable_only=True) if registry is not None else None
    if not (target is not None and is_local_address(target.address)
            or target is None and host is not None and is_local_address(host)):
        return original(self, command, host)
    governor = WindowsCommandGovernor.__new__(WindowsCommandGovernor)
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
