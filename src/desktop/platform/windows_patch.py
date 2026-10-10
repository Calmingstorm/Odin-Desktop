"""Windows: ``apply_patch`` on this computer (phase 3 plan C4).

The plan reaches a child process of its own, inside a job, on stdin: the same
input Linux's host runner reads. Odin's ``apply_patch.py`` stays byte for byte as
shipped (it is also the runner sent to Linux hosts, so it imports nothing of
ours). The child gives that module its Windows primitives instead:
:class:`~.windows_dirfd.WindowsOs` as its ``os``, a Windows root and labels for
its folder registry, and a rename that never replaces. It then runs
``apply_plan`` unchanged and prints the same JSON envelope, which the handler
parses exactly as on Linux. A remote host still gets the POSIX command.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys


def install(apply_patch):
    """``apply_patch``'s Windows primitives, only in this process (which exists for one patch)."""
    from . import windows_dirfd

    shim = windows_dirfd.WindowsOs()
    apply_patch.os = shim
    apply_patch._DirectoryRegistry.__init__ = windows_dirfd.directory_registry_init
    apply_patch._DirectoryRegistry.display = windows_dirfd.directory_registry_display
    return shim


def envelope(apply_patch, shim, root: str, plan_text: str) -> dict:
    """The Linux runner's envelope for one plan. A retained artifact that couldn't be made
    private is reported with the rollback's own failures, never in place of them."""
    from . import windows_dirfd

    try:
        plan = json.loads(plan_text)
        changed = apply_patch.apply_plan(root, plan,
                                         rename_noreplace=windows_dirfd.rename_noreplace)
        return {"ok": True, "changed": changed}
    except apply_patch.PatchRollbackError as exc:
        return {"ok": False, "error": str(exc), "rollback_failed": True,
                "rollback_failures": [*exc.failures, *shim.privacy_failures],
                "recovery_artifacts": exc.recovery_artifacts}
    except BaseException as exc:  # noqa: BLE001 - the Linux runner's envelope, every failure
        error = f"{type(exc).__name__}: {exc}"
        if shim.privacy_failures:
            error += "; " + "; ".join(shim.privacy_failures)
        return {"ok": False, "error": error, "rollback_failed": False}


def main() -> int:
    """The child: apply the plan on stdin under the root in argv, print the envelope."""
    from ...tools import apply_patch

    shim = install(apply_patch)
    result = envelope(apply_patch, shim, sys.argv[1], sys.stdin.read())
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0


def _unconfirmed(ended: bool) -> str:
    return "" if ended else "; its process could not be confirmed ended"


async def run_patch(root: str, plan_json: str, timeout: float) -> tuple[int, str]:
    """The plan applied by a child in a job of its own: its exit code and output."""
    from ...observability.diagnostics import safe_error
    from ...tools.execution_outcome import mark_dispatch_uncertain
    from .windows_exec import release, spawn, terminate

    argv = [sys.executable, "-I", "-B", "-m", "src.desktop.platform.windows_patch", root]
    running = await spawn(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(
            running.process.communicate(plan_json.encode("ascii")), timeout)
    except TimeoutError:
        mark_dispatch_uncertain()
        ended = await terminate(running)
        return 1, (f"apply_patch timed out after {timeout} seconds; its outcome is unknown"
                   + _unconfirmed(ended))
    except asyncio.CancelledError:
        await terminate(running)
        raise
    except Exception as exc:  # the child may still be committing: end it before letting go
        mark_dispatch_uncertain()
        ended = await terminate(running)
        return 1, (f"apply_patch failed while it ran ({safe_error(exc)}); its outcome is unknown"
                   + _unconfirmed(ended))
    finally:
        release(running)
    code = running.process.returncode or 0
    output = stdout.decode("utf-8", "replace")
    if code:
        output += stderr.decode("utf-8", "replace")
    return code, output


async def apply_on_host(self, alias: str, command: str, *, root: str, plan_json: str):
    """``_run_on_host`` for ``apply_patch``: the same lease and result; locally, the child."""
    from ...tools.command_shell import raw_command_result
    from ...tools.executor import _current_tool_timeout_ctx
    from ...tools.output_authorization import record_host
    from ...tools.ssh import is_local_address

    lease = self._acquire_host(alias)
    if not lease:
        return f"Unknown or disallowed host: {alias}"
    record_host(lease)
    with lease:
        target = lease.target
        if is_local_address(target.address):
            timeout = _current_tool_timeout_ctx.get() or self.config.command_timeout_seconds
            code, output = await lease.run(lambda: run_patch(root, plan_json, timeout))
        else:
            code, output = await lease.run(lambda: self._exec_command(
                target.address, command, target.ssh_user, target=target))
    return raw_command_result(code, output), code


if __name__ == "__main__":
    raise SystemExit(main())
