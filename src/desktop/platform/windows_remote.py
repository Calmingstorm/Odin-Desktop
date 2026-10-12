"""Windows variants of Odin's SSH paths (phase 3: from this computer to Linux hosts).

Each is the Linux body with only its POSIX steps replaced: Windows' OpenSSH by its
absolute path and without a console window, no ControlMaster, a client ended by its
handle, and host trust files written through the private store. The routed originals
and the copied ones (``run_ssh_command`` and its line reader, from the pinned
``ssh.py``) are pinned in ``tests/test_desktop_platform_variants.py``.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .windows_engine import _publish_path
from .windows_ssh import (
    CREATE_NO_WINDOW,
    end_client,
    keyscan_hint,
    known_hosts_option,
    openssh,
    openssh_argv,
    scan_host_keys,
)

if TYPE_CHECKING:
    from ...tools.local_supervisor import SupervisedShell
    from ...tools.ssh import OutputCallback
    from ...tools.ssh_pool import SSHConnectionPool


# Lifted from the Linux original.
async def read_lines_with_callback(
    proc: asyncio.subprocess.Process | SupervisedShell,
    timeout: int,
    on_output: OutputCallback,
    owned_pgid: int | None = None,
) -> tuple[int, str]:
    """Read bounded chunks, framing lines without StreamReader's 64 KiB limit.

    Very long lines are emitted as bounded fragments. Capture remains byte-
    ordered and the incremental decoder preserves split UTF-8 characters.
    """
    from src.tools.ssh import _stream_timeout_result, _truncate_output, codecs, mark_dispatch_uncertain  # noqa: E501, I001
    lines: list[str] = []
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    pending = ""

    async def emit(text: str) -> None:
        lines.append(text)
        # A failing consumer must not abandon a running child outside the
        # command deadline. The common exception arm owns cleanup.
        await on_output(text)

    try:
        async with asyncio.timeout(timeout):
            assert proc.stdout is not None
            while True:
                raw = await proc.stdout.read(16384)
                if not raw:
                    break
                pending += decoder.decode(raw)
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    await emit(line + "\n")
                if len(pending) >= 16384:
                    await emit(pending)
                    pending = ""
            pending += decoder.decode(b"", final=True)
            if pending:
                await emit(pending)
        # Wait for process exit with a bounded timeout to avoid indefinite hang
        try:
            await asyncio.wait_for(proc.wait(), timeout=min(timeout, 10))
        except TimeoutError:
            mark_dispatch_uncertain()
            await end_client(proc, owned_pgid=owned_pgid)
            return _stream_timeout_result(proc, "".join(lines), timeout)
    except TimeoutError:
        mark_dispatch_uncertain()
        await end_client(proc, owned_pgid=owned_pgid)
        return _stream_timeout_result(proc, "".join(lines) + pending, timeout)
    except asyncio.CancelledError:
        # Task cancellation (loop drain at shutdown/restart) must not leak
        # the child or its descendants past this process's lifetime.
        await end_client(proc, owned_pgid=owned_pgid)
        raise
    except Exception:
        mark_dispatch_uncertain()
        await end_client(proc, owned_pgid=owned_pgid)
        raise
    output = "".join(lines)
    return proc.returncode or 0, _truncate_output(output)


# Lifted from the Linux original.
async def run_ssh_command(
    host: str,
    command: str,
    ssh_key_path: str,
    known_hosts_path: str,
    timeout: int = 30,
    ssh_user: str = "root",
    max_retries: int = 1,
    retry_base_delay: float = 0.5,
    retry_max_delay: float = 10.0,
    pool: SSHConnectionPool | None = None,
    on_output: OutputCallback | None = None,
    port: int = 22,
    host_key_alias: str = "",
    target_id: str = "",
) -> tuple[int, str]:
    """Run a command on a remote host via SSH. Returns (exit_code, output).

    When *pool* is provided, uses OpenSSH ControlMaster multiplexing to
    reuse persistent connections. Otherwise falls back to one-shot SSH.

    Retries on transient SSH connection failures (exit code 255 with known
    error patterns). Command-level failures (nonzero exit from the remote
    command itself) are NOT retried — they represent valid remote results.
    """
    from src.tools.ssh import _is_ssh_transient_failure, _truncate_output, compute_backoff, log, mark_dispatch_uncertain  # noqa: E501, I001
    if pool is not None:
        ssh_args: list[str] = []
    else:
        ssh_args = [
            openssh("ssh"),
            "-i",
            ssh_key_path,
            "-o",
            known_hosts_option(known_hosts_path),
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "BatchMode=yes",
            "-p",
            str(port),
            *(["-o", f"HostKeyAlias={host_key_alias}"] if host_key_alias else []),
            f"{ssh_user}@{host}",
            command,
        ]

    from src.observability.diagnostics import command_display, safe_error

    log.info("SSH to %s@%s: %s", ssh_user, host, command_display(command))
    last_exit_code = 1
    last_output = ""

    # Positive values historically count attempts: keep approved retry policy.
    # Zero disables retries, not the initial attempt.
    for attempt in range(max(1, max_retries)):
        proc: asyncio.subprocess.Process | None = None
        pool_acquired = False
        try:
            if pool is not None:
                # Establish a foreground, asyncio-owned master before the
                # command. The lease survives every return/exception arm via
                # finally; release starts the configured idle-expiry timer.
                was_connected = pool.is_connected(host, ssh_user, target_id)
                pool_acquired = await pool.acquire(
                    host,
                    ssh_key_path,
                    known_hosts_path,
                    ssh_user,
                    port=port,
                    host_key_alias=host_key_alias,
                    target_id=target_id,
                )
                ssh_args = pool.get_ssh_args(
                    host,
                    command,
                    ssh_key_path,
                    known_hosts_path,
                    ssh_user,
                    was_connected=was_connected,
                    port=port,
                    host_key_alias=host_key_alias,
                    target_id=target_id,
                )
            # The ssh client is a direct child (no new session: killing the
            # client is sufficient — the remote side is ssh's own domain, and
            # ControlMaster mux masters must stay untouched).
            proc = await asyncio.create_subprocess_exec(
                *ssh_args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
            )
            if on_output is not None:
                exit_code, output = await read_lines_with_callback(
                    proc,
                    timeout,
                    on_output,
                )
            else:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                output = stdout.decode("utf-8", errors="replace")
                exit_code = proc.returncode or 0

            if pool is not None:
                # Compatibility with a live socket inherited from the old
                # daemonizing pool during an in-place update. New explicit
                # masters are direct asyncio children and return immediately.
                if not target_id:
                    await pool.ensure_master_registered(host, ssh_user)

            if exit_code == 0 or not _is_ssh_transient_failure(exit_code, output):
                return exit_code, _truncate_output(output)

            last_exit_code = exit_code
            last_output = output

            if attempt < max_retries - 1:
                wait = compute_backoff(attempt, retry_base_delay, retry_max_delay)
                log.warning(
                    "SSH transient failure to %s (attempt %d/%d): %s. Retrying in %.1fs...",
                    host,
                    attempt + 1,
                    max_retries,
                    output.strip()[:200],
                    wait,
                )
                await asyncio.sleep(wait)
            else:
                log.warning(
                    "SSH transient failure to %s (attempt %d/%d, exhausted): %s",
                    host,
                    attempt + 1,
                    max_retries,
                    output.strip()[:200],
                )

        except TimeoutError:
            last_exit_code = 1
            last_output = f"Command timed out after {timeout} seconds"
            # Reap the timed-out client on EVERY arm — the retry path used
            # to leave the previous ssh process running while spawning the
            # next attempt.
            if proc is not None:
                mark_dispatch_uncertain()
                await end_client(proc)
            if pool is not None:
                # A legacy socket may still name a detached master; preserve
                # its positive registration evidence until it is replaced.
                if not target_id:
                    await pool.ensure_master_registered(host, ssh_user)
            if attempt < max_retries - 1:
                wait = compute_backoff(attempt, retry_base_delay, retry_max_delay)
                log.warning(
                    "SSH timeout to %s (attempt %d/%d). Retrying in %.1fs...",
                    host,
                    attempt + 1,
                    max_retries,
                    wait,
                )
                await asyncio.sleep(wait)
            else:
                return 1, last_output

        except asyncio.CancelledError:
            # Loop drain at shutdown/restart: the ssh client must not
            # outlive this process.
            if proc is not None:
                await end_client(proc)
            raise

        except Exception as e:
            if proc is not None:
                mark_dispatch_uncertain()
                await end_client(proc)
            log.error("SSH command failed: %s", safe_error(e))
            return 1, f"SSH error: {safe_error(e)}"
        finally:
            if pool is not None and pool_acquired:
                pool.release(host, ssh_user, target_id)

    return last_exit_code, _truncate_output(last_output)


# Lifted from the Linux original.
async def read_binary_file(
    address: str,
    path: str,
    *,
    max_bytes: int,
    ssh_key_path: str = "",
    known_hosts_path: str = "",
    ssh_user: str = "root",
    port: int = 22,
    host_key_alias: str = "",
    timeout: int = 60,
) -> tuple[bytes | None, str]:
    """Read a file as BYTES from a local or remote host.

    Returns ``(data, "")`` on success or ``(None, error_message)``. Oversize is
    an explicit error rather than a silent truncation, because a partial binary
    is indistinguishable from a corrupt one.
    """
    from src.tools.ssh import asyncio, is_local_address, log, os, shlex  # noqa: I001
    if max_bytes < 0:
        return None, "max_bytes must be >= 0"

    if is_local_address(address):
        def _read() -> tuple[bytes | None, str]:
            try:
                size = os.path.getsize(path)
            except OSError as exc:
                return None, f"cannot stat {path}: {exc}"
            if size > max_bytes:
                return None, f"file is {size} bytes, over the {max_bytes}-byte limit"
            try:
                with open(path, "rb") as handle:
                    return handle.read(max_bytes + 1), ""
            except OSError as exc:
                return None, f"cannot read {path}: {exc}"

        data, err = await asyncio.to_thread(_read)
        if err:
            return None, err
        if data is not None and len(data) > max_bytes:
            return None, f"file exceeds the {max_bytes}-byte limit"
        return data, ""

    # Remote: cap stdout at the SOURCE. `communicate()` buffers all output, so
    # `cat` followed by a post-read length check still let an arbitrarily large
    # remote file exhaust Odin's memory before being rejected. Reading exactly
    # max+1 bytes bounds the transport and preserves an unambiguous oversize
    # signal. `--` stops option parsing for option-like paths.
    quoted = shlex.quote(path)
    remote_command = f"head -c {max_bytes + 1} -- {quoted}"
    ssh_args = [
        openssh("ssh"),
        "-i",
        ssh_key_path,
        "-o",
        known_hosts_option(known_hosts_path),
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "BatchMode=yes",
        "-p",
        str(port),
        *(["-o", f"HostKeyAlias={host_key_alias}"] if host_key_alias else []),
        f"{ssh_user}@{address}",
        remote_command,
    ]
    log.info("SSH binary read from %s@%s: %s", ssh_user, address, path)
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *ssh_args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        if proc is not None:
            await end_client(proc)
        return None, f"timed out reading {path} after {timeout}s"
    except asyncio.CancelledError:
        if proc is not None:
            await end_client(proc)
        raise
    except OSError as exc:
        return None, f"ssh failed: {exc}"
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()[:200]
        return None, detail or f"remote read failed (exit {proc.returncode})"
    if len(stdout) > max_bytes:
        return None, f"file is over the {max_bytes}-byte limit"
    return stdout, ""


# Lifted from the Linux original.
async def run_argv(
    argv: list[str], timeout: float, *, input_bytes: bytes | None = None
) -> tuple[int, bytes]:
    from src.tools.hosts.control import asyncio  # noqa: I001
    proc = await asyncio.create_subprocess_exec(
        *openssh_argv(argv),
        stdin=asyncio.subprocess.PIPE if input_bytes is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )
    try:
        output, _ = await asyncio.wait_for(proc.communicate(input_bytes), timeout=timeout)
    except (TimeoutError, asyncio.CancelledError):
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    return proc.returncode or 0, output


# Lifted from the Linux original.
def materialize_trust(
    self,
    host_id: str,
    key_alias: str,
    trust_mode: str,
    keys: tuple[str, ...] | list[str],
) -> str:
    from src.tools.hosts.registry import hashlib, normalize_public_key, private_directory  # noqa: E501, I001
    private_directory(self._trust_dir)
    normalized_keys = tuple(normalize_public_key(key) for key in keys)
    identity = "\0".join((host_id, key_alias, trust_mode, *normalized_keys))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    destination = self._trust_dir / f"{digest}.known_hosts"
    marker = "@cert-authority " if trust_mode == "ca" else ""
    payload = "".join(
        f"{marker}{key_alias} {key}\n" for key in normalized_keys
    )
    # Windows: the private store's own atomic replace (phase 2, A5).
    _publish_path(destination, payload.encode("utf-8"), create=True)
    return str(destination)


# Lifted from the Linux original.
async def scan(self, address: str, port: int) -> tuple[str, ...]:
    # Windows: its ssh-keyscan offers a key exchange it can't complete; ssh fetches the keys.
    from src.tools.hosts.control import HostTrustError, _SCAN_TIMEOUT, normalize_public_key, sanitized_diagnostic  # noqa: E501, I001
    code, output = await scan_host_keys(address, port, _SCAN_TIMEOUT)
    if code != 0:
        raise HostTrustError(f"host-key scan failed: {sanitized_diagnostic(output)}")
    keys: list[str] = []
    for raw in output.decode("utf-8", "replace").splitlines():
        if not raw or raw.startswith("#"):
            continue
        try:
            normalized = normalize_public_key(raw)
        except HostTrustError:
            continue
        if normalized not in keys:
            keys.append(normalized)
    if not keys:
        raise HostTrustError("host-key scan returned no supported public keys")
    return tuple(keys)


# Lifted from the Linux original.
async def scan_ca(self, address: str, port: int) -> tuple[str, ...]:
    from src.tools.hosts.control import HostTrustError, _SCAN_TIMEOUT, certificate_authority_key, sanitized_diagnostic  # noqa: E501, I001
    code, output = await run_argv(
        ["ssh-keyscan", "-c", "-T", "8", "-p", str(port), address], _SCAN_TIMEOUT,
    )
    if code != 0:
        raise HostTrustError(f"host certificate scan failed: {sanitized_diagnostic(output)}"
                             f"{keyscan_hint(output)}")
    keys = []
    for raw in output.decode("utf-8", "replace").splitlines():
        if not raw or raw.startswith("#"):
            continue
        try:
            key = certificate_authority_key(raw)
        except HostTrustError:
            continue
        if key not in keys:
            keys.append(key)
    if not keys:
        raise HostTrustError("host certificate scan returned no supported host certificates")
    return tuple(keys)
