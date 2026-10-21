"""Windows: SSH from this computer to Linux hosts (phase 3 plan C6).

* Bundled OpenSSH clients when packaged, Windows' own clients from source, by
  absolute path: a bare ``ssh`` would let
  ``CreateProcess`` search the engine's folder and current directory before System32.
* No ControlMaster: Windows' OpenSSH has no connection sharing, so every command is
  a connection of its own.
* No console window for any of them, stdin from the null device, and a timed-out or
  cancelled client is ended by its handle (Linux ends its process group; ssh starts
  nothing else here).
* A private key's ACL names this user, SYSTEM and Administrators only: OpenSSH refuses a
  key that any other principal can open (OWNER RIGHTS too), and then waits instead of
  failing.
* A known_hosts path is quoted: OpenSSH splits the option on whitespace, and user folders
  can hold spaces.
* Host keys are scanned by ssh itself. Windows' ssh-keyscan (OpenSSH 9.5) proposes a key
  exchange it can't complete, so it fails against servers that prefer it.
"""
from __future__ import annotations

import asyncio
import contextlib
import errno
import os
import subprocess
import tempfile

from . import win32
from .windows_files import user_sid
from .windows_payloads import packaged_file

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW
# One connection per family: ssh records the key it was offered.
_SCAN_FAMILIES = ("ssh-ed25519", "ecdsa-sha2-nistp256,ecdsa-sha2-nistp384,ecdsa-sha2-nistp521",
                  "rsa-sha2-512,rsa-sha2-256")
_TOOLS = {"ssh", "ssh-keyscan", "ssh-keygen"}
_MISSING = ("Windows' OpenSSH client isn't installed "
            "(Settings > System > Optional features > OpenSSH Client)")


def openssh(name: str) -> str:
    """Bundled clients when packaged, the OS clients when running from source."""
    if name not in _TOOLS:
        raise ValueError(f"not an OpenSSH client program: {name}")
    bundled = packaged_file(f"tools/openssh/{name}.exe")
    if bundled is not None:
        return str(bundled)
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    path = os.path.join(root, "System32", "OpenSSH", f"{name}.exe")
    if not os.path.isfile(path):
        raise FileNotFoundError(errno.ENOENT, _MISSING, path)
    return path


def openssh_argv(argv: list[str]) -> list[str]:
    """``argv`` with an OpenSSH program named by its absolute path."""
    if argv and argv[0] in _TOOLS:
        return [openssh(argv[0]), *argv[1:]]
    return list(argv)


async def end_client(proc, owned_pgid: int | None = None) -> None:
    """End an ssh client and reap it (Linux: ``terminate_process_tree``)."""
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()
    with contextlib.suppress(TimeoutError, ProcessLookupError, OSError):
        await asyncio.wait_for(proc.wait(), 5)


# How long an ended ssh client gets to be reaped before its exit counts as unconfirmed.
END_CLIENT_SECONDS = 5

UNCONFIRMED_EXIT_NOTE = (
    "\n(Windows did not confirm that the local ssh client exited after it was ended, so the "
    "remote command may still be running.)"
)


async def end_client_settled(proc) -> bool:
    """End and reap an ssh client, carried to the reap through cancellation
    (Linux: ``ssh._cleanup_settled``). True once the client is reaped.

    Windows ends the client at once (TerminateProcess, no TERM grace), so only
    its reap can be interrupted: a cancellation there (a cascade kill, the
    shutdown drain) waits again within the same bound, and is raised once the
    wait is over. A client not reaped within ``END_CLIENT_SECONDS`` (a failed
    kill, a reap error, a client that never reports its exit) has an
    unconfirmed exit: the dispatch is marked uncertain, a warning names it,
    and False is returned (or the cancellation raised).
    """
    from ...odin_log import get_logger
    from ...tools.execution_outcome import mark_dispatch_uncertain

    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + END_CLIENT_SECONDS
    interrupted = False
    while proc.returncode is None and loop.time() < deadline:
        try:
            await asyncio.wait_for(proc.wait(), deadline - loop.time())
        except asyncio.CancelledError:
            interrupted = True
        except (TimeoutError, ProcessLookupError, OSError):
            break
    confirmed = proc.returncode is not None
    if not confirmed:
        mark_dispatch_uncertain()
        get_logger("ssh").warning(
            "ssh client PID %s was not reaped within %ss of being ended; its remote command may "
            "still be running", getattr(proc, "pid", "?"), END_CLIENT_SECONDS)
    if interrupted:
        raise asyncio.CancelledError
    return confirmed


# CreateProcess takes one command line of at most 32,767 UTF-16 units, its terminating NUL
# included (the executable's path and every quoted argument count).
COMMAND_LINE_LIMIT = 32767


def command_line_units(argv) -> int:
    """The UTF-16 units of the command line CreateProcess receives for *argv*."""
    return len(subprocess.list2cmdline(list(argv)).encode("utf-16-le")) // 2 + 1

def known_hosts_option(path) -> str:
    """``UserKnownHostsFile`` naming exactly one file, whatever spaces its path holds."""
    return 'UserKnownHostsFile="' + str(path).replace("\\", "/") + '"'


def restrict_key(path) -> None:
    """Leave the key to this user, SYSTEM and Administrators, as OpenSSH requires."""
    handle = win32.create_file(path, win32.READ_CONTROL | win32.WRITE_DAC,
                               win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE
                               | win32.FILE_SHARE_DELETE, win32.OPEN_EXISTING,
                               win32.FILE_FLAG_OPEN_REPARSE_POINT)
    try:
        win32.set_dacl(handle, f"D:P(A;;FA;;;{user_sid()})(A;;FA;;;SY)(A;;FA;;;BA)")
    finally:
        win32.close(handle)


async def scan_host_keys(address: str, port: int, timeout: float) -> tuple[int, bytes]:
    """What ``ssh-keyscan`` prints for ``address``, fetched by ssh, one key family at a time.

    ssh accepts and records the host key, then offers no authentication, so it logs in
    to nothing. Returns ``(0, lines)`` when any key arrived, else ssh's last output. A family
    that times out doesn't lose the keys the others recorded, as ssh-keyscan keeps what it
    got; cancellation still ends the scan.
    """
    from .windows_remote import run_argv

    lines: list[bytes] = []
    last = b""
    with tempfile.TemporaryDirectory(prefix="odin-scan-") as folder:
        known = os.path.join(folder, "known_hosts")
        empty = os.path.join(folder, "global")
        with open(empty, "wb"):
            pass
        for family in _SCAN_FAMILIES:
            try:
                code, last = await run_argv([
                    "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                    "-o", known_hosts_option(known),
                    "-o", "Global" + known_hosts_option(empty)[len("User"):],
                    "-o", f"HostKeyAlgorithms={family}", "-o", "PreferredAuthentications=none",
                    "-o", "ConnectTimeout=8", "-p", str(port), "-l", "odin-scan", "--", address,
                    "exit"], timeout)
            except TimeoutError:
                last = f"ssh timed out after {timeout:g}s scanning {family}".encode()
            if os.path.exists(known):
                with open(known, "rb") as handle:
                    lines.extend(line for line in handle.read().splitlines() if line.strip())
                os.remove(known)
    if lines:
        return 0, b"\n".join(lines) + b"\n"
    return 1, last


def keyscan_hint(output: bytes) -> str:
    """Why a certificate scan failed, when it is Windows' ssh-keyscan's own fault."""
    if b"unsupported KEX method" in output:
        return ("; Windows' ssh-keyscan can't complete this server's key exchange, "
                "so use pinned trust for this host")
    return ""
