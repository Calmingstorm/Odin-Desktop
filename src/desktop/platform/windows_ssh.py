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
