"""macOS: ``validate_action``'s fixed probes, choosing their tools where they run.

Odin builds each probe as a POSIX command and reads what it prints. Three of them name tools a
Mac lacks (GNU timeout, systemctl, journalctl). On macOS the engine builds those probes so that
they pick their tools on the target host: a Linux host runs Odin's own probe, unchanged, and a
Mac prints exactly what Odin's evaluation expects.

* ``port``: GNU timeout when the host has it, otherwise the same bash /dev/tcp probe under a
  perl alarm (perl ships with macOS); ``OPEN`` or ``CLOSED``.
* ``service``: the launchd job named (the user's domain, then the system's); a running job is
  ``active`` and anything else, a missing job included, ``inactive``, in systemctl's words.
* ``log_absent``/``log_present``: the unified log (``log show``) over the window, ``unit=``
  naming a process or subsystem; matched lines, then ``LOG_READ_OK``, or ``LOG_CHECK_ERROR``.

Every other check is Odin's own probe.
"""
from __future__ import annotations

import shlex

_PORT = 'cat < /dev/null > "/dev/tcp/$1/$2"'
_SERVICE = (
    'case "$(launchctl print "gui/$(id -u)/$1" 2>/dev/null || '
    'launchctl print "system/$1" 2>/dev/null)" in '
    '*"state = running"*) echo active;; *) echo inactive;; esac'
)
_LOG = (
    'p="$3"; '
    'printf "" | grep -E -e "$p" >/dev/null 2>&1; '
    'if [ "$?" -gt 1 ]; then echo "LOG_CHECK_ERROR invalid pattern"; '
    'printf "" | grep -E -e "$p" 2>&1 | head -n 2; exit 0; fi; '
    'if [ -n "$1" ]; then '
    'set -- --last "${2}s" --style compact '
    '--predicate "process == \\"$1\\" OR subsystem == \\"$1\\""; '
    'else set -- --last "${2}s" --style compact; fi; '
    'e=$(log show "$@" 2>&1 >/dev/null); r=$?; '
    'if [ "$r" -ne 0 ]; then echo "LOG_CHECK_ERROR log exit $r"; '
    'printf "%s\\n" "$e" | tail -n 1; exit 0; fi; '
    'log show "$@" 2>/dev/null | grep -E -e "$p" | head -n 20; echo LOG_READ_OK'
)


def build_command(check) -> str | None:
    """``_build_command`` on macOS: the probes above, Odin's own for every other check."""
    from ...tools.post_validation import _LOG_PROBE_SCRIPT, _build_command

    original = _build_command.linux_original(check)
    if original is None:
        return None
    t, target, timeout = check.type, check.target, int(check.timeout_seconds)
    if t == "port":
        host, port = target.rsplit(":", 1) if ":" in target else ("127.0.0.1", target)
        probe = f"bash -c {shlex.quote(_PORT)} _ {shlex.quote(host)} {shlex.quote(port)}"
        return (
            f"{{ if command -v timeout >/dev/null 2>&1; then timeout {timeout} {probe}; "
            f"else perl -e 'alarm shift @ARGV; exec @ARGV' {timeout} {probe}; fi; }} "
            "&& echo OPEN || echo CLOSED"
        )
    if t == "service":
        return (
            f'if [ "$(uname -s)" = Darwin ]; then '
            f"sh -c {shlex.quote(_SERVICE)} odin-service-check {shlex.quote(target)}; "
            f"else {original}; fi"
        )
    if t in ("log_absent", "log_present"):
        darwin = original.replace(shlex.quote(_LOG_PROBE_SCRIPT), shlex.quote(_LOG), 1)
        if darwin == original:
            return original
        return f'if [ "$(uname -s)" = Darwin ]; then {darwin}; else {original}; fi'
    return original
