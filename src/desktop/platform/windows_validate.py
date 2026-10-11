"""Windows: ``validate_action``'s fixed probes on this computer (phase 3 plan C8).

Odin builds each probe as a POSIX command (curl, bash's /dev/tcp, systemctl, pgrep,
journalctl) and reads what it prints. For a check aimed at this Windows computer the
probe is Windows PowerShell instead, printing exactly what the Linux probe prints, so
the evaluation stays Odin's own:

* ``http``: Windows' curl.exe; the status code, or ``FAILED_<exit>``.
* ``port``: a TCP connect within the check's timeout; ``OPEN`` or ``CLOSED``.
* ``service``: the service named (or display-named) in systemctl's words (``active``,
  ``inactive``, ``activating``, ``deactivating``); a missing service is ``inactive``, and a
  service this user can't read says so instead of claiming a state.
* ``process``: command lines matched case-sensitively, as pgrep -f does; ``PRESENT``,
  ``ABSENT``, or ``PROCESS_CHECK_ERROR``. Windows shows a user only some command lines
  (measured: a standard user reads its own), so a process whose command line is hidden is
  matched by its image name; ``-EncodedCommand`` payloads aren't text and aren't matched.
* ``log_absent``/``log_present``: the Event Log stands in for the journal (Application
  and System, ``unit=`` naming the event provider), lines matched case-sensitively within
  the window, then ``LOG_READ_OK``; an invalid pattern is ``LOG_CHECK_ERROR``.

The handler marks which hosts are this computer for the run (``VALIDATION_HOSTS``);
checks for any other host keep Odin's POSIX probes.
"""
from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar

from .windows_exec import ps_quote

# (is this alias this computer?, the run's default host)
VALIDATION_HOSTS: ContextVar[tuple[Callable[[str], bool], str | None] | None] = ContextVar(
    "windows_validation_hosts", default=None)


def local_alias(executor) -> Callable[[str], bool]:
    """Whether an alias resolves to this computer, for the executor's requester."""
    from ...tools.ssh import is_local_address

    def local(alias: str) -> bool:
        resolved = executor._resolve_host(alias)
        return bool(resolved) and is_local_address(resolved[0])

    return local


def build_command(check) -> str | None:
    """``_build_command`` on Windows: this computer's probes, Odin's for other hosts."""
    from ...tools.post_validation import _build_command

    hosts = VALIDATION_HOSTS.get()
    if (hosts is not None and check.type != "command"
            and hosts[0](check.host or hosts[1] or "localhost")):
        return windows_probe(check)
    return _build_command.linux_original(check)


def windows_probe(check) -> str | None:
    t, target, timeout = check.type, check.target, int(check.timeout_seconds)
    if t == "http":
        return (
            "$curl = Join-Path $env:SystemRoot 'System32\\curl.exe'\n"
            f"$o = & $curl -sS -o NUL -w '%{{http_code}}' --max-time {timeout} -L "
            f"{ps_quote(target)} 2>&1 | ForEach-Object {{ \"$_\" }}\n"
            "$r = $LASTEXITCODE\n"
            "$o -join \"`n\"\n"
            "if ($r -ne 0) { \"FAILED_$r\" }")
    if t == "port":
        host, port = target.rsplit(":", 1) if ":" in target else ("127.0.0.1", target)
        if not host or not port.isdigit():
            return None
        return (
            "$c = New-Object System.Net.Sockets.TcpClient\n"
            f"try {{ if ($c.ConnectAsync({ps_quote(host)}, {int(port)}).Wait({timeout * 1000})) "
            "{ 'OPEN' } else { 'CLOSED' } } catch { 'CLOSED' } finally { $c.Dispose() }")
    if t == "service":
        # One service by name, not a listing: a standard user may not list services. The
        # getter is called as a method because PowerShell hides a property getter's error.
        # 1060 is ERROR_SERVICE_DOES_NOT_EXIST.
        return (
            f"$n = {ps_quote(target)}\n"
            "try {\n"
            "  Add-Type -AssemblyName System.ServiceProcess\n"
            "  $service = New-Object System.ServiceProcess.ServiceController $n\n"
            "  $state = [string]$service.get_Status()\n"
            "} catch {\n"
            "  $e = $_.Exception; while ($e.InnerException) { $e = $e.InnerException }\n"
            "  if ($e.NativeErrorCode -eq 1060) { 'inactive' } else {\n"
            "    \"service check failed: $($e.Message)\" }\n"
            "  exit 0\n"
            "}\n"
            "switch ($state) { 'Running' { 'active' } 'StartPending' { 'activating' } "
            "'ContinuePending' { 'activating' } 'StopPending' { 'deactivating' } "
            "'PausePending' { 'deactivating' } default { 'inactive' } }")
    if t == "process":
        return (
            f"$p = {ps_quote(target)}\n"
            "try {\n"
            "  [void][regex]::new($p)\n"
            "  $m = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {\n"
            "    if ($_.ProcessId -eq $PID) { return $false }\n"
            "    $line = $_.Name\n"
            "    if ($_.CommandLine) {\n"
            "      $line = $_.CommandLine -replace ' -EncodedCommand [A-Za-z0-9+/=]+', '' }\n"
            "    $line -cmatch $p })\n"
            "  if ($m.Count) { 'PRESENT' } else { 'ABSENT' }\n"
            "} catch { \"PROCESS_CHECK_ERROR $($_.Exception.Message)\" }")
    if t in ("log_absent", "log_present"):
        unit, pattern = "", target
        if target.startswith("unit="):
            rest = target[5:]
            if ":" not in rest:
                return None
            unit, pattern = rest.split(":", 1)
        return (
            f"$p = {ps_quote(pattern)}\n"
            f"$u = {ps_quote(unit)}\n"
            "try { [void][regex]::new($p) } catch {\n"
            "  'LOG_CHECK_ERROR invalid pattern'; $_.Exception.Message; exit 0 }\n"
            f"$f = @{{ LogName = 'Application', 'System'; "
            f"StartTime = (Get-Date).AddSeconds(-{int(check.window_seconds)}) }}\n"
            "if ($u) { $f.ProviderName = $u }\n"
            "$e = @()\n"
            "try { $e = @(Get-WinEvent -FilterHashtable $f -ErrorAction Stop) } catch {\n"
            "  $id = $_.FullyQualifiedErrorId\n"
            "  if ($id -notmatch 'NoMatchingEventsFound|NoMatchingProvider') {\n"
            "    \"LOG_CHECK_ERROR Get-WinEvent: $($_.Exception.Message)\"; exit 0 } }\n"
            "$e | ForEach-Object { \"$($_.Message)\" -split \"`r?`n\" } | "
            "Where-Object { $_ -cmatch $p } | Select-Object -First 20\n"
            "'LOG_READ_OK'")
    return None
