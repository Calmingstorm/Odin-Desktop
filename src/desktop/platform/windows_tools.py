"""Windows variants of Odin's tool functions (phase 3: execution on this computer).

Each replaces one function routed by ``@windows_variant`` and is the Linux body
with only its POSIX steps replaced: commands run under Windows PowerShell in a
job (``windows_exec``), ``read_file`` and ``apply_patch`` reach this computer
without a POSIX shell (``windows_read``, ``windows_patch``), background jobs are
job objects (``windows_jobs``), and this computer is a Windows host.
``tests/test_desktop_platform_variants.py`` pins each Linux original, so a
change there forces a review here.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ...tools.ssh import is_local_address
from .windows_exec import (
    default_interpreter,
    interpreters_for,
    local_host_test,
    run_local_command,
    run_local_script,
    supported_host_os,
    unsupported_interpreter,
)
from .windows_helpers import probe
from .windows_jobs import WindowsProcessRegistry, create_job_shell
from .windows_patch import apply_on_host
from .windows_read import is_absolute, read_on_host
from .windows_remote import run_ssh_command as remote_ssh
from .windows_ssh import known_hosts_option
from .windows_validate import VALIDATION_HOSTS, local_alias

if TYPE_CHECKING:
    from pathlib import Path

    from ...health.startup import DiagnosticResult
    from ...tools.hosts import HostLease
    from ...tools.hosts.control import HostCandidate


# Lifted from the Linux original.
async def handle_read_file(self, inp: dict) -> str | tuple[str, int]:
    from src.tools.handlers.files_docs import _READ_FILE_BODY_MAX_CHARS, _READ_FILE_RAW_BODY_MAX_BYTES, _READ_FILE_RESULT_MAX_CHARS, base64, binascii, json, scrub_output_secrets, shlex  # noqa: E501, I001
    path = inp.get("path")
    host = inp.get("host")
    if not path:
        return "Error: 'path' is required for read_file."
    if not isinstance(path, str) or not is_absolute(path):
        return f"Error: read_file requires an absolute path, got {path!r}."
    if not host:
        return "Error: 'host' is required for read_file."

    raw_lines = inp.get("lines", 200)
    # Validate here as well as in the JSON schema: skills and internal
    # callers can invoke handlers without schema validation.
    if type(raw_lines) is not int or raw_lines <= 0:  # bool is not a count
        return "Error: 'lines' must be a positive integer count (maximum 1000)."
    if raw_lines > 1000:
        return "Error: 'lines' must not exceed 1000."
    lines = raw_lines

    raw_start = inp.get("start_line", 1)
    if type(raw_start) is not int or raw_start <= 0:  # bool is not a line number
        return "Error: 'start_line' must be a positive one-based integer."
    if raw_start > 2**53 - 1:
        return "Error: 'start_line' must not exceed 9007199254740991."
    start_line = raw_start
    start_label = f"n{start_line}"

    raw_mode = inp.get("raw", False)
    if type(raw_mode) is not bool:
        return "Error: 'raw' must be a boolean."

    from src.tools.output_delivery import get_delivery_budget

    result_budget = min(_READ_FILE_RESULT_MAX_CHARS, get_delivery_budget(self.config))
    # Reserve the complete framing at the source. The default allocations
    # remain unchanged; smaller configured delivery caps return fewer whole
    # source lines, never a downstream splice through content or metadata.
    numbered_budget = min(_READ_FILE_BODY_MAX_CHARS, result_budget - 256)
    raw_budget = min(_READ_FILE_RAW_BODY_MAX_BYTES, result_budget - 600)

    # Bound output at the SOURCE. _run_on_host eventually passes through
    # ssh._truncate_output(), whose 16K head+tail splice would destroy the
    # contiguity and interval guarantees of a selected range. This awk
    # program emits only a contiguous prefix of the requested range. It
    # also probes one following record so a full-count result can say
    # whether more source lines exist. Numbered mode renders source numbers
    # and a trailing cursor; raw mode puts the interval/cursor in a framed
    # envelope without altering the framed source content.
    numbered_awk_program = r"""BEGIN {
used = 0
selected = 0
returned = 0
last_returned = 0
continuation = 0
oversize_line = 0
}
NR < start { next }
selected >= count { continuation = NR; exit }
{
selected++
prefix = sprintf("%.0f: ", NR)
line = prefix $0
separator = (returned > 0 ? "\n" : "")
needed = length(separator) + length(line)
if (used + needed > budget) {
    if (returned == 0) {
        oversize_line = NR
        exit
    }
    continuation = NR
    exit
}
if (returned > 0) printf "\n"
printf "%s", line
used += needed
returned++
last_returned = NR
}
END {
if (returned > 0) printf "\n\n"
if (oversize_line > 0) {
    printf "Error: source line %.0f exceeds the read_file output budget; " \
        "no lines returned.", oversize_line
} else if (returned == 0) {
    printf "[returned empty range starting at start_line=%s]", substr(start_label, 2)
} else if (continuation > 0) {
    printf "[returned %.0f-%.0f, continue at start_line=%.0f]", \
        start, last_returned, continuation
} else {
    printf "[returned %.0f-%.0f]", start, last_returned
}
}"""
    # Raw mode base64-encodes selected bytes only across the host command's
    # text transport, then the handler restores visible UTF-8 source inside
    # a length-framed public envelope. Direct source bytes would otherwise
    # be damaged by the host transport's UTF-8 replacement decode. The
    # public frame keeps numbering and cursor metadata outside the content;
    # its byte count makes boundaries unambiguous even when source text
    # contains the marker literals.
    raw_awk_program = r"""BEGIN {
used = 0
selected = 0
returned = 0
last_returned = 0
continuation = 0
oversize_line = 0
pending = 0
}
NR < start { next }
pending {
if (returned == 0) oversize_line = pending_nr
else continuation = pending_nr
pending = 0
exit
}
selected >= count { continuation = NR; exit }
{
selected++
line_bytes = length($0)
needed = line_bytes + 1
if (used + needed > budget) {
    # The sole undecidable case is a final, unterminated line for which
    # the synthetic newline would be the only byte over budget.
    if (used + line_bytes <= budget) {
        pending = 1
        pending_nr = NR
        pending_line = $0
        next
    }
    if (returned == 0) oversize_line = NR
    else continuation = NR
    exit
}
returned++
body[returned] = $0
used += needed
last_returned = NR
}
END {
if (pending) {
    if (final_newline == 0) {
        returned++
        body[returned] = pending_line
        used += length(pending_line)
        last_returned = pending_nr
    } else if (returned == 0) {
        oversize_line = pending_nr
    } else {
        continuation = pending_nr
    }
} else if (returned > 0 && continuation == 0 && final_newline == 0) {
    # Every accepted record was budgeted with a newline.  At EOF, the last
    # record has none when the source's final byte was not LF.
    used--
}

if (oversize_line > 0) {
    printf "ERROR\t%.0f\n", oversize_line > metadata
    exit
}

printf "ODIN_READ_FILE_RAW_META_V1\t%s\t%.0f\t", \
    substr(start_label, 2), count > metadata
if (returned > 0) printf "%.0f\t%.0f\t", start, last_returned >> metadata
else printf "-\t-\t" >> metadata
if (continuation > 0) {
    printf "%.0f\t%.0f\n", continuation, used >> metadata
} else {
    printf "-\t%.0f\n", used >> metadata
}

for (i = 1; i <= returned; i++) {
    printf "%s", body[i]
    if (i < returned || continuation > 0 || final_newline != 0) printf "\n"
}
}"""
    safe_path = shlex.quote(str(path))
    if raw_mode:
        # The command's stdout is internal ASCII base64 plus one terminal metadata
        # line. The source bytes live only in a private temporary file, so
        # the text-only host transport never decodes or rewrites them.
        command = (
            # Every artifact is independently and atomically allocated.
            # Predictable suffixes both inherited the service umask and
            # allowed a local attacker to pre-create a sidecar between
            # mktemp and the first redirect.
            "metadata=$(mktemp) || exit 1; "
            'body=$(mktemp) || { rm -f -- "$metadata"; exit 1; }; '
            'encoded=$(mktemp) || { rm -f -- "$metadata" "$body"; exit 1; }; '
            'trap \'rm -f -- "$metadata" "$body" "$encoded"\' EXIT; '
            'chmod 600 -- "$metadata" "$body" "$encoded" || exit 1; '
            f"final_newline=$(tail -c 1 < {safe_path} 2>/dev/null | wc -l); "
            f"LC_ALL=C awk -v start={start_line} "
            f"-v start_label={shlex.quote(start_label)} "
            f"-v count={lines} -v budget={raw_budget} "
            f'-v final_newline="$final_newline" '
            '-v metadata="$metadata" '
            f'{shlex.quote(raw_awk_program)} < {safe_path} > "$body"; '
            "status=$?; "
            'if [ $status -ne 0 ]; then cat -- "$metadata"; '
            'rm -f -- "$body"; exit $status; fi; '
            'base64 < "$body" > "$encoded"; status=$?; '
            "if [ $status -ne 0 ]; then exit $status; fi; "
            "tr -d '\\r\\n' < \"$encoded\"; status=$?; "
            "printf '\\n'; cat -- \"$metadata\"; exit $status"
        )
    else:
        command = (
            f"awk -v start={start_line} -v start_label={shlex.quote(start_label)} "
            f"-v count={lines} -v budget={numbered_budget} "
            f"{shlex.quote(numbered_awk_program)} < {safe_path}"
        )
    # Windows: a local read runs in Python, printing what the awk command prints.
    raw = await read_on_host(
        self, host, command, path=path, start=start_line, start_label=start_label,
        count=lines, budget=raw_budget if raw_mode else numbered_budget, raw_mode=raw_mode)
    is_tuple = isinstance(raw, tuple)
    if is_tuple:
        text, code = str(raw[0]), int(raw[1])
    else:
        text, code = str(raw), None

    if raw_mode and (code == 0 or code is None):
        raw_transport = text.strip("\n")
        if raw_transport.startswith("ERROR\t"):
            try:
                oversize_line = int(raw_transport.split("\t", 1)[1])
            except ValueError:
                return "Error: read_file raw transport returned an invalid envelope.", 1
            return (
                f"Error: source line {oversize_line} exceeds the read_file "
                "output budget; no lines returned.",
                1,
            )
        try:
            metadata_prefix = "ODIN_READ_FILE_RAW_META_V1\t"
            marker = "\n" + metadata_prefix
            if marker in text:
                encoded, metadata_line = text.rstrip("\n").rsplit("\n", 1)
            elif text.startswith(metadata_prefix):
                encoded, metadata_line = "", text.rstrip("\n")
            else:
                raise ValueError("missing raw metadata")
            fields = metadata_line.split("\t")
            if len(fields) != 7 or fields[0] != "ODIN_READ_FILE_RAW_META_V1":
                raise ValueError("missing raw metadata")
            requested_start = int(fields[1])
            requested_lines = int(fields[2])
            returned_start = None if fields[3] == "-" else int(fields[3])
            returned_end = None if fields[4] == "-" else int(fields[4])
            continuation = None if fields[5] == "-" else int(fields[5])
            content_bytes = int(fields[6])
            content = base64.b64decode(encoded, validate=True)
            if len(content) != content_bytes:
                raise ValueError("raw content length mismatch")
            # Raw transport must not bypass the standard secret-output
            # boundary merely because its internal bytes are base64 encoded.
            # Raw mode is a UTF-8 text contract; reject other encodings and
            # redact recognized textual secrets before framing the public
            # model-facing content.
            source_text = content.decode("utf-8", errors="strict")
            scrubbed_text = scrub_output_secrets(source_text)
            scrubbed_content = scrubbed_text.encode("utf-8")
            content_bytes = len(scrubbed_content)
        except UnicodeDecodeError:
            return "Error: read_file raw mode requires UTF-8 text content.", 1
        except (ValueError, TypeError, binascii.Error):
            return "Error: read_file raw transport returned an invalid envelope.", 1
        metadata = {
            "requested_start_line": requested_start,
            "requested_lines": requested_lines,
            "returned_start_line": returned_start,
            "returned_end_line": returned_end,
            "truncated": continuation is not None,
            "continue_at_start_line": continuation,
            "content_encoding": "utf-8",
            "content_bytes": content_bytes,
            "content_redacted": scrubbed_text != source_text,
        }
        header = json.dumps(metadata, ensure_ascii=True, separators=(",", ":"))
        text = (
            f"<<<ODIN_READ_FILE_RAW_V1 {header}>>>\n"
            "<<<ODIN_READ_FILE_RAW_CONTENT_V1>>>\n"
            f"{scrubbed_text}"
            "<<<ODIN_READ_FILE_RAW_END_V1>>>"
        )

    # The generic transport's defensive 16K truncator keeps head+tail.
    # Never infer transport truncation from payload content: a source file
    # may legitimately contain the transport marker literal. The source
    # program is already bounded below this threshold, so only the actual
    # returned length is a trustworthy overrun signal here.
    if len(text) > result_budget:
        return "Error: read_file envelope exceeds the delivery budget; no lines returned.", 1
    # The source-budget guard is a handler failure even though awk itself
    # completed normally. Preserve a typed nonzero result through the
    # executor rather than letting an "Error:" string ride exit code 0.
    if code == 0 and text.startswith("Error: source line "):
        return text, 1
    if is_tuple:
        assert code is not None
        return text, code
    return text


# Lifted from the Linux original.
def check_host_inventory_compat(tools_config: Any) -> DiagnosticResult:
    """Warn about legacy host shapes without turning an upgrade into an outage."""
    from src.health.startup import DiagnosticResult, re  # noqa: I001
    hosts = getattr(tools_config, "hosts", {})
    if not hosts:
        return DiagnosticResult(
            name="host_inventory_compat",
            passed=True,
            detail="No managed hosts configured — skipped",
        )
    alias_pattern = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    issues: list[str] = []
    for alias, host in hosts.items():
        if not alias_pattern.fullmatch(alias):
            issues.append(f"tools.hosts alias {alias!r} is not editable in the Hosts panel")
        if getattr(host, "os", "linux") not in supported_host_os(getattr(host, "address", "")):
            issues.append(
                f"tools.hosts.{alias}.os={getattr(host, 'os', '')!r} is legacy-only"
            )
        if (
            getattr(host, "trust_mode", "legacy") in {"pinned", "tofu", "ca"}
            and not getattr(host, "host_keys", [])
        ):
            issues.append(f"tools.hosts.{alias} has no usable pinned host key")
    configured = set(hosts)
    dangling = set(
        getattr(getattr(tools_config, "governor", None), "host_overrides", {})
    ) - configured
    if dangling:
        issues.append(
            "tools.governor.host_overrides names unknown hosts: "
            + ", ".join(sorted(dangling))
        )
    default_host = getattr(tools_config, "default_host", "")
    if default_host and default_host not in configured:
        issues.append(f"tools.default_host names unknown host {default_host!r}")
    if issues:
        return DiagnosticResult(
            name="host_inventory_compat",
            passed=False,
            detail="; ".join(issues),
            recommendation=(
                "Existing entries remain loaded. Normalize them through config.yml or the "
                "Hosts and Host Access panels before relying on omitted-host execution."
            ),
            metadata={"issue_count": len(issues)},
        )
    return DiagnosticResult(
        name="host_inventory_compat",
        passed=True,
        detail="Managed-host inventory and explicit defaults are coherent",
        metadata={"host_count": len(hosts)},
    )


# Lifted from the Linux original.
def validate_host_details(alias: Any, body: Mapping[str, Any]) -> dict[str, Any]:
    from src.tools.hosts.control import HostTrustError, _ALIAS_RE, _HOSTNAME_RE, _USER_RE, _clean_line, ipaddress, scrub_output_secrets  # noqa: E501, I001
    name = _clean_line(alias, "alias", 64, required=True)
    if not _ALIAS_RE.fullmatch(name) or name.startswith("-"):
        raise HostTrustError("alias must start with a letter and use letters, digits, . _ or -")
    address = _clean_line(body.get("address", ""), "address", 253, required=True)
    if address.startswith("-") or any(char in address for char in "[]/@ "):
        raise HostTrustError("address is not a plain hostname or IP address")
    try:
        ipaddress.ip_address(address)
    except ValueError:
        if not _HOSTNAME_RE.fullmatch(address):
            raise HostTrustError("address is not a valid hostname or IP address")
    ssh_user = _clean_line(body.get("ssh_user", "root"), "ssh_user", 64, required=True)
    if not _USER_RE.fullmatch(ssh_user) or ssh_user.startswith("-"):
        raise HostTrustError("ssh_user is invalid")
    host_os = _clean_line(body.get("os", "linux"), "os", 16, required=True).lower()
    if host_os not in supported_host_os(address):
        raise HostTrustError("os must be 'linux' or 'macos' ('windows' is for this computer only)")
    port = body.get("port", 22)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise HostTrustError("port must be an integer between 1 and 65535")
    description = _clean_line(body.get("description", ""), "description", 200)
    description = scrub_output_secrets(description)
    trust_mode = _clean_line(body.get("trust_mode", "pinned"), "trust_mode", 16).lower()
    if trust_mode not in {"legacy", "pinned", "ca", "tofu"}:
        raise HostTrustError("trust_mode must be legacy, pinned, ca, or tofu")
    return {
        "alias": name,
        "address": address,
        "ssh_user": ssh_user,
        "os": host_os,
        "port": port,
        "description": description,
        "enabled": bool(body.get("enabled", True)),
        "trust_mode": trust_mode,
    }


# Lifted from the Linux original.
async def host_test(self, token: str) -> HostCandidate:
    from src.tools.hosts.control import _TEST_TIMEOUT, _is_host_key_mismatch, _run_argv, is_local_address, replace, sanitized_diagnostic, time  # noqa: E501, I001
    candidate = self.get(token)
    if is_local_address(candidate.address):
        argv = None  # Windows: this computer is checked through its command runner
    else:
        legacy = candidate.trust_mode == "legacy"
        key_alias = (
            candidate.address if candidate.trust_mode == "ca"
            else f"odin-{candidate.host_id}"
        )
        known_hosts = (
            self.registry.effective_legacy_known_hosts_path
            if legacy
            else self.registry.materialize_trust(
                candidate.host_id,
                key_alias,
                candidate.trust_mode,
                candidate.host_keys,
            )
        )
        remote = (
            "printf 'odin-host-test '; "
            "case \"$(uname -s)\" in Linux) echo linux;; "
            "Darwin) echo macos;; *) echo unknown;; esac"
        )
        argv = [
            "ssh",
            "-i",
            self.registry.effective_key_path,
            "-o",
            known_hosts_option(known_hosts),
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "PreferredAuthentications=publickey",
            "-o",
            "ControlMaster=no",
            *(
                []
                if legacy
                else ["-o", f"HostKeyAlias={key_alias}"]
            ),
            "-o",
            "ConnectTimeout=10",
            "-p",
            str(candidate.port),
            "--",
            f"{candidate.ssh_user}@{candidate.address}",
            remote,
        ]
    try:
        code, output = await (local_host_test(_TEST_TIMEOUT) if argv is None
                              else _run_argv(argv, _TEST_TIMEOUT))
    except TimeoutError:
        result = {"ok": False, "checked_at": time.time(), "detail": "connection test timed out"}
    else:
        text = sanitized_diagnostic(output)
        observed = text.rsplit(" ", 1)[-1].strip() if text else ""
        ok = code == 0 and text.startswith("odin-host-test ") and observed == candidate.os
        if ok:
            detail = "authentication and platform verified"
        elif code == 0 and text.startswith("odin-host-test "):
            detail = sanitized_diagnostic(
                f"platform mismatch: observed {observed}; selected {candidate.os}"
            )
        else:
            detail = text or f"ssh exit {code}"
        result = {
            "ok": ok,
            "checked_at": time.time(),
            "platform": observed,
            "detail": detail,
        }
    # The SSH await must not mutate a staged inventory while its desired
    # state is being persisted. Recheck identity inside the publication lock.
    async with self._publication_lock:
        active = self.registry.get(candidate.alias)
        mismatch = not result["ok"] and _is_host_key_mismatch(
            str(result.get("detail", ""))
        )
        testing_active_identity = bool(
            active is not None
            and candidate.address == active.address
            and candidate.ssh_user == active.ssh_user
            and candidate.os == active.os
            and candidate.port == active.port
            and candidate.trust_mode == active.trust_mode
            and candidate.host_keys == active.host_keys
        )
        if testing_active_identity and (mismatch or result["ok"]):
            self.registry.mark_test_result(
                candidate.alias, result, host_key_mismatch=mismatch
            )
    candidate = replace(candidate, tested=bool(result["ok"]), test_result=result)
    self._candidates[token] = candidate
    return candidate


# Lifted from the Linux original.
async def handle_run_script(self, inp: dict) -> str | tuple[str, int]:
    """Write a script to a temp file, execute it, and clean up."""
    from src.tools.handlers.system import ToolFailure, _truncate_lines, base64, is_test_command, is_test_failure, os, shlex  # noqa: E501, I001
    host = inp.get("host")
    script = inp.get("script")
    if not host:
        host = self._resolve_default_host(self._current_user_id)
        if not host:
            return "Error: 'host' is required for run_script."
    if not script:
        return "Error: 'script' is required for run_script."
    interpreter = inp.get("interpreter", default_interpreter(self, host))

    allowed, denial, governor_note = self._govern_command(script, host)
    if not allowed:
        return denial

    # Map interpreter to file extension
    ext_map = {
        "bash": ".sh",
        "sh": ".sh",
        "python3": ".py",
        "python": ".py",
        "node": ".js",
        "ruby": ".rb",
        "perl": ".pl",
        "powershell": ".ps1",
    }
    ext = ext_map.get(interpreter, ".sh")
    filename = inp.get("filename") or f"odin_script{ext}"

    # Sanitize interpreter to prevent injection
    allowed_interpreters = interpreters_for(self, host)
    if interpreter not in allowed_interpreters:
        return ToolFailure(
            f"{unsupported_interpreter(interpreter, allowed_interpreters)} "
            f"Use one of: {', '.join(sorted(allowed_interpreters))}"
        )

    resolved = self._resolve_host(host)
    if not resolved:
        return f"Unknown or disallowed host: {host}"
    address, ssh_user, _os = resolved

    # Base64-encode script to avoid all quoting/heredoc issues
    encoded = base64.b64encode(script.encode()).decode()

    safe_filename = shlex.quote(os.path.basename(filename))
    # Write to temp file, execute, capture output, clean up
    cmd = (
        f"TMPF=$(mktemp /tmp/{safe_filename}.XXXXXXXX) && "
        f"echo '{encoded}' | base64 -d > \"$TMPF\" && "
        f'chmod +x "$TMPF" && '
        f'{interpreter} "$TMPF" 2>&1; EXIT=$?; '
        f'rm -f "$TMPF"; exit $EXIT'
    )

    # Stream output if enabled for this tool
    on_output = None
    finish_cb = None
    if self.output_streamer and self.output_streamer.is_enabled("run_script"):
        _, on_output, finish_cb = self.output_streamer.create_callback(
            "run_script",
            channel_id=host,
        )

    if is_local_address(address):  # Windows: this computer runs the script from a private file
        code, output = await run_local_script(
            self, address, ssh_user, interpreter, script, filename, on_output)
    else:
        code, output = await self._exec_command(
            address,
            cmd,
            ssh_user,
            on_output=on_output,
            # run_script executes arbitrary user script text, same hazard.
            use_workspace=True,
        )
    if finish_cb:
        try:
            await finish_cb()
        except Exception:
            pass
    if code != 0:
        result = f"Script failed (exit {code}):\n{_truncate_lines(output)}"
        if (
            self._branch_freshness_enabled
            and is_test_command(script)
            and is_test_failure(result)
        ):
            result = await self._annotate_with_freshness(
                result, host, "run_script", script[:120]
            )
        text = f"{governor_note}{result}" if governor_note else result
        return text, code
    output = _truncate_lines(output)
    text = f"{governor_note}{output}" if governor_note else output
    return text, 0


# Lifted from the Linux original.
async def start_local_reserved(
    self, host: str, command: str, timeout: int = 300, *, owner_id: str | None = None,
    host_alias: str = "", host_identity: str = "", origin_channel: str = "",
    scope_id: str = "", host_binding: dict | None = None, host_lease: HostLease | None = None,
) -> str:
    """Start a background process locally. Returns confirmation with PID.

    ``host_lease`` is the generation-bound admission evidence the handler
    already acquired for this start (H2). It is held for the job's WHOLE
    lifetime — admission evidence while it runs, plus the live lease
    reference that lets ``force_revoke_host``/``shutdown`` see and fence
    this exact generation — and released only when the job settles or is
    torn down. Never persisted.
    """
    from src.tools.process_manager import JOB_TOKEN_ENV, MAX_LIFETIME_SECONDS, Path, ProcessInfo, WorkspaceError, asyncio, command_display, log, os, safe_text, secrets, time, workspace_env  # noqa: E501, I001
    from src.tools.ssh import is_local_address

    if not is_local_address(host):
        return "Error: remote process start requires a generation-bound host lease."

    alias = host_alias or host
    if alias in self._revoking_aliases or (host_lease is not None and host_lease.revoked):
        return self._refuse_start(host_lease, "Error: host force-revoked; process not started.")
    revoke_epoch = self._local_revoke_epochs.get(alias, 0)

    try:
        # start_new_session puts the shell at the head of its own process
        # group, so kill()/shutdown() can take out descendants
        # (`sh -c 'x & ...'`) instead of just the shell leader.
        workspace = self._resolve_workspace()
        job_token = secrets.token_hex(8)
        env = dict(workspace_env(Path(workspace))) if workspace else dict(os.environ)
        env[JOB_TOKEN_ENV] = job_token
    except WorkspaceError as e:
        # The workspace is unusable. This is a REFUSAL, not a spawn error:
        # it must read as a failure to the tool loop, not as a started
        # process (PR #239 round-4 — the plain string was classified ok).
        return self._refuse_start(
            host_lease, f"Error: cannot start background process — {e}"
        )
    try:
        from src.tools.command_shell import ShellUnavailableError, resolve_local_shell

        mode = self._command_shell() if callable(self._command_shell) else self._command_shell
        shell_choice = resolve_local_shell(mode)
        proc = await create_job_shell(  # Windows: PowerShell in a job of its own
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.PIPE,
            start_new_session=True,
            cwd=workspace,
            env=env,
            shell_choice=shell_choice,
        )
    except ShellUnavailableError as exc:
        return self._refuse_start(host_lease, f"Error: {exc}")
    except asyncio.CancelledError:
        # Cancellation is not a refusal, but it is still an exit path: the
        # generation reference must be processed before it propagates, or
        # a cancelled start leaks a lease for a job that never existed.
        self._release_start_lease(host_lease)
        raise
    except Exception as e:
        return self._refuse_start(host_lease, f"Failed to start process: {e}")

    pid = proc.pid
    info = ProcessInfo(
        pid=pid,
        command=command,
        host=host,
        start_time=time.time(),
        process=proc,
        effective_shell=shell_choice.name,
        shell_executable=shell_choice.executable,
        job_token=job_token,
        owner_id=owner_id,
        host_alias=host_alias,
        host_identity=host_identity,
        origin_channel=origin_channel,
        scope_id=scope_id,
        host_binding=host_binding,
        host_lease=host_lease,
    )
    self._processes[pid] = info
    self._retained_generations[info.generation] = info
    self._own_children.add(pid)

    # Drainage and terminal-state publication are SEPARATE tasks:
    # the reader drains stdout; the watcher publishes status at
    # leader exit and reaps the group (which closes the pipe).
    try:
        info._reader_task = asyncio.create_task(self._read_output(info))
        info._exit_task = asyncio.create_task(self._watch_exit(info))
        from src.async_utils import fire_and_forget

        info._lifetime_task = fire_and_forget(
            self._enforce_lifetime(info, MAX_LIFETIME_SECONDS), name=f"process_lifetime:{pid}"
        )
        self._persist_output(info)
    except BaseException:
        # The job is already spawned and recorded, so it now OWNS the
        # lease. Tear the process down instead of leaving an untracked
        # generation reference behind (H2); an unstartable lifecycle
        # deliberately fails loud here.
        await self._terminate_bound_host_job(info)
        raise

    if (revoke_epoch != self._local_revoke_epochs.get(alias, 0)
            or alias in self._revoking_aliases
            or (host_lease is not None and host_lease.revoked)):
        # Spawn crossed the revoke snapshot. Install the complete lifecycle
        # before teardown: even an unprovable kill must not strand a
        # permanently-running record or its concurrency slot.
        gone = await self._terminate_bound_host_job(info)
        if not gone:
            info.status = "unknown"
            info.finished_at = info.finished_at or time.time()
            info.capture_error = info.capture_error or "process cleanup could not be confirmed"
            self._persist_output(info)
        return ("Error: host force-revoked; process terminated."
                if gone else
                "Error: host force-revoked; process outcome unknown outcome_unknown=true.")

    log.info("Started process PID %d: %s", pid, command_display(command))
    return f"Process started (PID {pid}): {safe_text(command)}"


# Lifted from the Linux original.
def ensure_process_registry(self):
    """Lazy-init the ProcessRegistry ON THE EXECUTOR (RFC-004 P4).

    The attribute stays here — not on the system domain — because the
    web API (agents_loops, config_admin) and graceful shutdown read
    ``tool_executor._process_registry`` directly.
    """
    if not hasattr(self, "_process_registry"):
        # Pass the RESOLVER, not a resolved string: each background spawn
        # must re-verify the workspace's mutable filesystem invariants.
        self._process_registry = WindowsProcessRegistry(  # Windows: jobs, not sessions
            workspace=self._ensure_local_workspace,
            remote_exec=self._exec_remote_target,
            retention_dir=self._retention_root() / "process-output",
            acquire_output_lease=self._acquire_process_cleanup_lease,
            command_shell=lambda: self._command_shell_mode(),
        )
    return self._process_registry


# Lifted from the Linux original.
async def handle_apply_patch(self, inp: dict) -> str | tuple[str, int]:
    from src.tools.handlers.files_docs import Path, _APPLY_PATCH_COMMAND_MAX_BYTES, __file__, base64, json, shlex, zlib  # noqa: E501, I001
    host = inp.get("host")
    root = inp.get("root")
    patch_text = inp.get("patch_text")
    if not host:
        return "Error: 'host' is required for apply_patch.", 1
    if not isinstance(root, str) or not is_absolute(root):
        return "Error: 'root' must be an absolute path for apply_patch.", 1
    if not isinstance(patch_text, str):
        return "Error: 'patch_text' is required for apply_patch.", 1

    from src.tools.apply_patch import PatchError, parse_patch

    try:
        plan = parse_patch(patch_text)
    except PatchError as exc:
        return f"Error: invalid apply_patch envelope: {exc}", 1

    resolved = self._resolve_host(host)
    if not resolved:
        return f"Unknown or disallowed host: {host}", 1

    # The governor sees a representative write command before any staged
    # payload reaches the host. The patch itself is transported as base64,
    # never interpolated as shell syntax.
    allowed, denial, _ = self._govern_command(f"apply_patch --root {shlex.quote(root)}", host)
    if not allowed:
        return denial, 1

    runner = Path(__file__).resolve().parents[1] / "apply_patch.py"
    plan_json = json.dumps(plan, ensure_ascii=True, separators=(",", ":"))
    wrapper = (
        runner.read_text(encoding="utf-8")
        + "\nimport json\nimport sys as _sys\n"
        + "try:\n"
        + "    _plan = json.loads(_sys.stdin.read())\n"
        + "    _changed = apply_plan(_sys.argv[1], _plan)\n"
        + "    _result = {'ok': True, 'changed': _changed}\n"
        + "except PatchRollbackError as _exc:\n"
        + "    _result = {'ok': False, 'error': str(_exc), 'rollback_failed': True, "
        + "'rollback_failures': _exc.failures, "
        + "'recovery_artifacts': _exc.recovery_artifacts}\n"
        + "except BaseException as _exc:\n"
        + "    _result = {'ok': False, 'error': f'{type(_exc).__name__}: {_exc}', "
        + "'rollback_failed': False}\n"
        + "print(json.dumps(_result, ensure_ascii=True, separators=(',', ':')))\n"
    )
    runner_b64 = base64.b64encode(wrapper.encode("utf-8")).decode("ascii")
    plan_b64 = base64.b64encode(plan_json.encode("utf-8")).decode("ascii")
    safe_root = shlex.quote(root)
    command = (
        "runner=$(mktemp) || exit 1; "
        'plan=$(mktemp) || { rm -f -- "$runner"; exit 1; }; '
        'trap \'rm -f -- "$runner" "$plan"\' EXIT; '
        'chmod 600 -- "$runner" "$plan" || exit 1; '
        f'printf %s {shlex.quote(runner_b64)} | base64 -d > "$runner" || exit 1; '
        f'printf %s {shlex.quote(plan_b64)} | base64 -d > "$plan" || exit 1; '
        f'python3 "$runner" {safe_root} < "$plan"'
    )
    if len(command.encode("utf-8")) > _APPLY_PATCH_COMMAND_MAX_BYTES:
        runner_z = base64.b64encode(zlib.compress(wrapper.encode("utf-8"))).decode("ascii")
        plan_z = base64.b64encode(zlib.compress(plan_json.encode("utf-8"))).decode("ascii")
        decoder = shlex.quote(
            "import base64,sys,zlib; "
            "sys.stdout.buffer.write(zlib.decompress(base64.b64decode(sys.stdin.buffer.read())))"
        )
        command = (
            "runner=$(mktemp) || exit 1; "
            'plan=$(mktemp) || { rm -f -- "$runner"; exit 1; }; '
            'trap \'rm -f -- "$runner" "$plan"\' EXIT; '
            'chmod 600 -- "$runner" "$plan" || exit 1; '
            f'printf %s {shlex.quote(runner_z)} | python3 -c {decoder} > "$runner" || exit 1; '
            f'printf %s {shlex.quote(plan_z)} | python3 -c {decoder} > "$plan" || exit 1; '
            f'python3 "$runner" {safe_root} < "$plan"'
        )
        size = len(command.encode("utf-8"))
        if size > _APPLY_PATCH_COMMAND_MAX_BYTES:
            return (
                f"Error: compressed apply_patch command is {size} bytes; "
                f"limit is {_APPLY_PATCH_COMMAND_MAX_BYTES} bytes. "
                "Nothing was dispatched or written. "
                "Split the patch into smaller apply_patch calls.",
                1,
            )
    # Windows: this computer applies the plan in a child process of its own.
    raw = await apply_on_host(self, host, command, root=root, plan_json=plan_json)
    if isinstance(raw, tuple):
        text, code = str(raw[0]), int(raw[1])
    else:
        text, code = str(raw), 1
    if code != 0:
        return text, code
    try:
        result = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return "Error: apply_patch host returned an invalid result envelope.", 1
    if not isinstance(result, dict) or result.get("ok") is not True:
        error = (
            result.get("error", "unknown host-side failure")
            if isinstance(result, dict)
            else "invalid result"
        )
        if isinstance(result, dict) and result.get("rollback_failed") is True:
            artifacts = result.get("recovery_artifacts")
            retained = (
                " Retained private recovery artifacts: " + ", ".join(artifacts)
                if isinstance(artifacts, list)
                and artifacts
                and all(isinstance(path, str) for path in artifacts)
                else ""
            )
            return (
                "Error: apply_patch rollback failed; manual recovery required: "
                f"{error}.{retained}",
                1,
            )
        return f"Error: apply_patch failed without changing the final file set: {error}", 1
    changed = result.get("changed")
    if not isinstance(changed, list) or not all(isinstance(item, str) for item in changed):
        return "Error: apply_patch host returned an invalid result envelope.", 1
    return "Applied patch successfully:\n" + "\n".join(f"- {item}" for item in changed), 0


# Lifted from the Linux original.
async def exec_command(
    self,
    address: str,
    command: str,
    ssh_user: str = "root",
    timeout: int | None = None,
    on_output=None,
    use_workspace: bool = False,
    target=None,
    use_command_shell: bool = False,
) -> tuple[int, str]:
    """Execute a command locally or via SSH depending on host address.

    Local hosts (127.0.0.1, localhost, ::1) use direct subprocess —
    no SSH key needed, no network overhead.

    Both paths are wrapped in bulkhead semaphores so that a flood of
    SSH commands cannot exhaust subprocess/FD resources needed by
    local commands (and vice versa).

    When *on_output* is provided, stdout lines are streamed to the
    callback as they arrive (in addition to being collected).

    Internal/code-built commands always use /bin/sh. Only raw public
    command routes explicitly opt into tools.command_shell; workspace
    selection is independent (run_script uses a workspace but not this).
    """
    from src.tools.executor import BulkheadFullError, _current_tool_timeout_ctx, _host_lease_ctx, is_local_address  # noqa: E501, I001
    if timeout is None:
        timeout = _current_tool_timeout_ctx.get() or self.config.command_timeout_seconds
    active_lease = _host_lease_ctx.get()
    if target is None and active_lease is not None:
        candidate = active_lease.target
        if candidate.address == address and candidate.ssh_user == ssh_user:
            target = candidate
    if is_local_address(address):
        # The workspace applies ONLY to raw user commands, and only because
        # the caller asked for it. This primitive also backs apply_patch,
        # PDF host reads, and validation probes, whose fixed-path behavior
        # must remain independent of the raw-command workspace. Default
        # False preserves that separation.
        cwd = self._ensure_local_workspace() if use_workspace else None
        bh = self.bulkheads.get("subprocess")
        if bh:
            try:
                async with bh.acquire():
                    return await run_local_command(
                        command,
                        timeout=timeout,
                        on_output=on_output,
                        cwd=cwd,
                        command_shell=self._command_shell_mode() if use_command_shell else "sh",
                    )
            except BulkheadFullError:
                return 1, "Error: subprocess bulkhead full — too many concurrent local commands"
        return await run_local_command(
            command, timeout=timeout, on_output=on_output, cwd=cwd,
            command_shell=self._command_shell_mode() if use_command_shell else "sh",
        )
    ssh_retry = self.config.ssh_retry
    if target is not None:
        address = target.address
        ssh_user = target.ssh_user
    ssh_kwargs: dict[str, Any] = dict(
        host=address,
        command=command,
        ssh_key_path=target.key_path if target is not None else self.config.ssh_key_path,
        known_hosts_path=(
            target.known_hosts_path
            if target is not None
            else self.config.ssh_known_hosts_path
        ),
        timeout=timeout,
        ssh_user=ssh_user,
        port=target.port if target is not None else 22,
        host_key_alias=target.host_key_alias if target is not None else "",
        target_id=target.runtime_key if target is not None else "",
        max_retries=ssh_retry.max_retries,
        retry_base_delay=ssh_retry.base_delay,
        retry_max_delay=ssh_retry.max_delay,
        pool=None,  # Windows' OpenSSH has no ControlMaster
        on_output=on_output,
    )
    bh = self.bulkheads.get("ssh")
    if bh:
        try:
            async with bh.acquire():
                return await remote_ssh(**ssh_kwargs)
        except BulkheadFullError:
            return 1, "Error: SSH bulkhead full — too many concurrent SSH commands"
    return await remote_ssh(**ssh_kwargs)


# Lifted from the Linux original.
def pdf_lock_path() -> Path:
    from src.runtime.pdf_resources import Path, __file__, sys  # noqa: I001
    prefix = Path(sys.prefix).resolve()
    if prefix.name == "python" and prefix.parent.name == "runtime":
        return prefix.parent / "pdf.lock.json"
    # The packaged Windows runtime ships its own lock under the plain name.
    return Path(__file__).resolve().parents[2] / "app/packaging/python/pdf.lock.win_amd64.json"


# Lifted from the Linux original.
def read_pdf_lock() -> dict:
    from src.runtime.pdf_resources import PdfUnavailable, _lock_path, json  # noqa: I001
    try:
        lock = json.loads(_lock_path().read_text(encoding="utf-8"))
        digest = lock["sha256"]
        if (lock["schema"] != 1 or lock["package"] != "PyMuPDF"
                or lock["platform"] != "windows-amd64"
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or not lock["url"].startswith("https://")
                or not lock["wheel"].endswith(".whl")):
            raise ValueError("invalid pinned wheel")
        import platform

        if platform.machine() != "AMD64":
            raise PdfUnavailable("PDF support download is only available for x64 Windows.")
        return lock
    except PdfUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PdfUnavailable(
            "PDF support download cannot start: the pinned wheel lock is missing or invalid."
        ) from exc


# Lifted from the Linux original.
async def handle_http_probe(self, inp: dict) -> str | tuple[str, int]:
    from src.tools.handlers.browser_web import _truncate_lines  # noqa: I001
    from src.tools.http_probe_ops import build_http_probe_command, normalize_probe_headers

    try:
        # Decode strict wire headers before host authorization and retain
        # the canonical dict for the existing execution interface.
        if "headers" in inp:
            inp = {**inp, "headers": normalize_probe_headers(inp["headers"])}
    except ValueError as e:
        return f"http_probe error: {e}", 1

    # Validate before acquiring a generation lease: refused construction
    # has no transport and must not pin the host generation.
    try:
        cmd = build_http_probe_command(inp)
    except ValueError as e:
        return f"http_probe error: {e}", 1

    host = inp.get("host", "")
    if host:
        lease = self._acquire_host(host)
        if not lease:
            return f"Unknown or disallowed host: {host}"
        target = lease.target
        address, ssh_user = target.address, target.ssh_user
    else:
        lease = None
        target = None
        address = "127.0.0.1"
        ssh_user = "root"

    if lease is not None:
        with lease:
            code, output = await lease.run(
                lambda: probe(self, address, cmd, ssh_user, target=target)
            )
    else:
        code, output = await probe(self, address, cmd, ssh_user)
    # curl's exit code is the ground truth and was being discarded: a
    # connection failure (exit 7, status_code 000) returned prose that
    # matched no error prefix, so the executor classified the probe as a
    # SUCCESS and the audit log recorded it approved with no error
    # (adversarial review, reproduced). Structured returns make the status
    # a fact rather than an inference.
    if code != 0 and not output.strip():
        return f"http_probe failed (exit {code}): curl returned no output", code
    if not output.strip():
        return "http_probe: no response received", 1
    return _truncate_lines(output), code


# Lifted from the Linux original.
async def handle_validate_action(self, inp: dict) -> str:
    from src.tools.handlers.validation import log  # noqa: I001
    from src.tools.post_validation import (
        format_report_summary,
        report_as_json,
        run_bundle,
    )

    raw_checks = inp.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        return (
            "Error: 'checks' must be a non-empty list. See tool description for check schema."
        )

    bundle_name = str(inp.get("bundle_name") or "unnamed").strip()[:120]
    default_host = inp.get("default_host")
    default_host = str(default_host).strip() if default_host else None
    if not default_host:
        default_host = self._resolve_default_host(self._current_user_id) or None
    grace_seconds = int(inp.get("grace_seconds") or 0)
    grace_seconds = max(0, min(grace_seconds, 60))
    max_parallel = int(inp.get("max_parallel") or 12)
    fmt = str(inp.get("format") or "summary").strip().lower()

    governor = getattr(self, "command_governor", None)

    async def _exec(
        _address: str,
        command: str,
        _ssh_user: str,
        *,
        timeout: int,
        use_workspace: bool = False,
        use_command_shell: bool = False,
    ) -> tuple[int, str]:
        # Never mutate shared state here — concurrent checks would race.
        # _exec_command accepts a per-call timeout, which is honored
        # directly by the SSH/local primitives without touching self.
        if governor is not None:
            try:
                # Use the shared run_command admission path: it carries
                # the task-local requester tier and exact effective alias.
                allowed, denial, _note = self._govern_command(command, _address)
            except Exception as ge:
                # Fail-closed on governor exceptions: we advertise
                # command-type checks as going through the governor;
                # silently bypassing it if the governor blows up would
                # be exactly the "safe unless error path" foot-gun
                # Odin flagged. Emit the error into the result so the
                # operator sees it, and treat the check as errored.
                log.exception("governor check raised for validation command")
                raise RuntimeError(
                    f"validate_action: governor check raised {type(ge).__name__}: {ge}"
                ) from ge
            if not allowed:
                raise PermissionError(f"governor-blocked: {denial}")
        # Forwarded per check from run_bundle: True only for type=command
        # (user-supplied text, a raw command route like run_command —
        # round 10); fixed-shape probes must keep pre-PR cwd semantics so
        # an unusable workspace cannot disable service/process/http/port
        # validation (round 11).
        # resolve_host returns the alias in its address slot deliberately,
        # so the generation-bound target is acquired here after the
        # per-check governor decision.
        alias = _address
        lease = self._acquire_host(alias)
        if lease is None:
            raise PermissionError(f"unknown host alias: {alias}")
        with lease:
            target = lease.target
            return await lease.run(
                lambda: self._exec_command(
                    target.address,
                    command,
                    target.ssh_user,
                    timeout=timeout,
                    use_workspace=use_workspace,
                    target=target,
                    use_command_shell=(use_command_shell
                                       or is_local_address(target.address)),
                )
            )

    # Windows: checks aimed at this computer get Windows probes (windows_validate).
    hosts = VALIDATION_HOSTS.set((local_alias(self), default_host))
    try:
        report = await run_bundle(
            raw_checks,
            bundle_name=bundle_name,
            default_host=default_host,
            resolve_host=lambda alias: (
                (alias, "", "") if self._resolve_host(alias) is not None else None
            ),
            exec_command=_exec,
            grace_seconds=grace_seconds,
            max_parallel=max_parallel,
        )
    finally:
        VALIDATION_HOSTS.reset(hosts)

    if fmt == "json":
        return report_as_json(report)
    return format_report_summary(report)
