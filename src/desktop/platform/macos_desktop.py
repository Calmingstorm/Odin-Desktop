"""macOS variants of Desktop helpers outside the IPC and process boundary.

A new profile's defaults name this Mac as its local host, a macOS host, and put the workspace
beside the profiles, as Linux and Windows do; the Hosts panel's check of this computer says macos.

SSH control sockets: macOS's sun_path holds 104 bytes with its NUL, so the bound is 103 (Linux's is
107), keeping the same 17 bytes for OpenSSH's temporary suffix. The per-user temporary folder is too
long for the 37-byte registry socket name, so the fallback root is root's sticky /private/tmp, the
canonical form of macOS's /tmp link. Linux's rules hold: the managed components are this user's,
mode 0700, and are walked and created without following links.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

SOCKET_PATH_LIMIT = 103
STICKY_TMP = Path("/private/tmp")


def _fallback_root() -> Path:
    return STICKY_TMP / f"odin-desktop-{os.geteuid()}"


def check_socket_path(path: str) -> None:
    """ssh_sockets.check_socket_path with macOS's bound."""
    from ..ssh_sockets import OPENSSH_TEMP_SUFFIX_BYTES

    required = max(len(os.fsencode(path)), len(os.fsencode(os.path.abspath(path))))
    required += OPENSSH_TEMP_SUFFIX_BYTES
    if "\0" in path or required > SOCKET_PATH_LIMIT:
        raise ValueError(
            "Desktop SSH control socket path is too long or invalid: "
            f"{required} bytes including OpenSSH's {OPENSSH_TEMP_SUFFIX_BYTES}-byte "
            f"temporary suffix; maximum {SOCKET_PATH_LIMIT}. "
            "Choose a shorter tools.ssh_pool.socket_dir."
        )


def socket_directory(paths) -> str:
    """ssh_sockets.socket_directory: a valid XDG runtime root first, then /private/tmp."""
    from ..ssh_sockets import _fits, _runtime_root

    profile = paths.profile_id
    compact = "p-" + hashlib.sha256(profile.encode()).hexdigest()[:12]
    runtime = _runtime_root(sticky_tmp=STICKY_TMP)
    roots = [runtime / "odin-desktop"] if runtime is not None else []
    roots.append(_fallback_root())
    for root in roots:
        for namespace in dict.fromkeys((profile, compact)):
            candidate = str(root / namespace / "ssh")
            if _fits(candidate):
                return candidate
    raise ValueError("No bounded Desktop SSH runtime directory is available")


def prepare_socket_directory(value: str) -> None:
    """ssh_sockets.prepare_socket_directory with the /private/tmp fallback root."""
    from ..ssh_sockets import _open_directory

    path = Path(value)
    fallback = _fallback_root()
    if path.parent.parent == fallback:
        root = fallback
    else:
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        root = Path(runtime) / "odin-desktop" if runtime else None
        if root is None or path.parent.parent != root:
            return
        fd = _open_directory(root.parent, sticky_tmp=STICKY_TMP)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise PermissionError("Unsafe Desktop SSH XDG runtime root")
        finally:
            os.close(fd)
    fd = _open_directory(path, create_from=root, sticky_tmp=STICKY_TMP)
    os.close(fd)


def fresh_config_document(paths) -> dict:
    """Linux's provisioned defaults, with the local host and its workspace as the Mac has them.

    The local host is this Mac, a macOS host. The workspace is a sibling of the profile folders
    inside the app's private namespace
    (``~/Library/odin-desktop/.odin-desktop-workspaces/<profile>``), as on Linux and Windows:
    Linux's formula steps up from the data folder once, and the Mac's data folder sits one level
    deeper (``<profile>/data``), so it would put the workspace inside the profile. A profile keeps
    the values it was created with.
    """
    from ..provisioning import fresh_config_document as routed

    document = routed.linux_original(paths)
    tools = document["tools"]
    tools["hosts"]["localhost"]["os"] = "macos"
    tools["local_working_dir"] = str(
        paths.data_dir.parents[1] / ".odin-desktop-workspaces" / paths.profile_id)
    return document


# Lifted from Odin's HostEnrollmentManager._test (src/tools/hosts/control.py), with this Mac
# as the local host: a local candidate's check reports macos (Odin's names its own system,
# Linux).
async def host_test(self, candidate):
    from src.tools.hosts.control import _TEST_TIMEOUT, _is_host_key_mismatch, _run_argv, is_local_address, known_hosts_option, replace, sanitized_diagnostic, time  # noqa: E501, I001
    token = candidate.token
    if is_local_address(candidate.address):
        argv = ["sh", "-c", "printf 'odin-host-test macos\\n'"]
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
        if not legacy:
            if known_hosts in self._registry_trust_paths():
                # It was already committed, even if that generation gets
                # replaced during the SSH await below.
                self._candidate_trust.pop(known_hosts, None)
            else:
                self._candidate_trust[known_hosts] = self._trust_identity(candidate)
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
        code, output = await _run_argv(argv, _TEST_TIMEOUT)
    except TimeoutError:
        result = {
            "ok": False, "checked_at": time.time(), "platform": "",
            "detail": "connection test timed out",
        }
    else:
        text = sanitized_diagnostic(output)
        probe_ran = output.startswith(b"odin-host-test ")
        observed = text.rsplit(" ", 1)[-1].strip() if probe_ran else ""
        ok = code == 0 and probe_ran and observed == candidate.os
        if ok:
            detail = "authentication and platform verified"
        elif code == 0 and probe_ran:
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
    # Discard/expiry may occur while SSH is running; do not resurrect it.
    if token in self._candidates:
        self._candidates[token] = candidate
    return candidate
