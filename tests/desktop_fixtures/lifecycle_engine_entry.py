"""Test-only source composition seam, NOT supported chat/tool dispatch.

Original src.__main__.main, CoreService and ManagementService.compose. Only
composition admits one original ProcessRegistry execution. No new methods,
capabilities or substitute owner results. Instrumentation records real calls.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from private_notification_server import assert_isolated

assert_isolated()
root = Path(os.environ["ODIN_APP_EXECUTION_ROOT"]).resolve()
if not root.is_relative_to(Path(os.environ["HOME"]).resolve()):
    raise RuntimeError("Execution evidence must stay in throwaway HOME")
root.mkdir(mode=0o700, parents=True, exist_ok=True)


def record(kind, **values):
    with (root / "lifecycle.jsonl").open("a") as stream:
        stream.write(json.dumps({"kind": kind, "corePid": os.getpid(),
                                "monotonicMs": time.monotonic_ns() / 1_000_000,
                                **values}) + "\n")


record("fixture_import_enter")
try:
    import asyncio
    import hashlib
    import shlex
    import subprocess

    import src.__main__ as entry
    record("entry_import_return")
    from src.desktop.management import ManagementService
    record("management_import_return")
    import src.desktop.core as core_module
    from src.desktop.core import CoreService
except BaseException as exc:
    record("fixture_import_failed", error=type(exc).__name__, detail=str(exc))
    raise
record("fixture_import_return")

original_build = core_module.build_engine_services


def build(*args, **kwargs):
    record("engine_build_enter")
    try:
        result = original_build(*args, **kwargs)
    except BaseException as exc:
        record("engine_build_failed", error=type(exc).__name__, detail=str(exc))
        raise
    record("engine_build_return")
    return result


core_module.build_engine_services = build
original_secret_call = core_module.secret_call


async def secret_call(function, *args, **kwargs):
    record("secret_hydration_enter")
    try:
        result = await original_secret_call(function, *args, **kwargs)
    except BaseException as exc:
        record("secret_hydration_failed", error=type(exc).__name__, detail=str(exc))
        raise
    record("secret_hydration_return")
    return result


core_module.secret_call = secret_call
original_start = CoreService.start


async def start(self, *args, **kwargs):
    record("core_start_enter")
    try:
        result = await original_start(self, *args, **kwargs)
    except BaseException as exc:
        record("core_start_failed", error=type(exc).__name__, detail=str(exc))
        raise
    record("core_start_return")
    return result


CoreService.start = start


if os.environ.get("ODIN_APP_EXECUTION_SOURCE_BASELINE") == "1":
    # Exact committed pre-change source, not a substitute implementation.
    source = subprocess.check_output(
        ["git", "show", "1d75c5e805c62e1e7c2883e5dfd0f56141cb07a5:src/desktop/management.py"],
        cwd=Path(__file__).resolve().parents[2],
    )
    namespace = {"__name__": "src.desktop.measured_baseline", "__package__": "src.desktop"}
    exec(compile(source, "1d75c5e8:src/desktop/management.py", "exec"), namespace)
    # The historical management API predates shared engine/settings ownership.
    # Measure its exact historical composition too, not an incompatible hybrid
    # with today's request-enabled core (which now supplies settings=).
    core_source = subprocess.check_output(
        ["git", "show", "1d75c5e805c62e1e7c2883e5dfd0f56141cb07a5:src/desktop/core.py"],
        cwd=Path(__file__).resolve().parents[2],
    )
    core_namespace = {"__name__": "src.desktop.measured_baseline_core",
                      "__package__": "src.desktop"}
    exec(compile(core_source, "1d75c5e8:src/desktop/core.py", "exec"), core_namespace)
    core_namespace["ManagementService"] = namespace["ManagementService"]
    import src.desktop.core as core_module

    core_module.CoreService = core_namespace["CoreService"]
    original_start = core_namespace["CoreService"].start
    core_namespace["CoreService"].start = start
    original_compose = namespace["ManagementService"].compose.__func__
    record("exact_committed_baseline", source_commit="1d75c5e805c62e1e7c2883e5dfd0f56141cb07a5",
           sha256=hashlib.sha256(source).hexdigest(),
           core_sha256=hashlib.sha256(core_source).hexdigest())
else:
    original_compose = ManagementService.compose.__func__


def compose(cls, core, **kwargs):
    record("compose_enter")
    owner_class = (namespace["ManagementService"]
                   if os.environ.get("ODIN_APP_EXECUTION_SOURCE_BASELINE") == "1" else cls)
    manager = original_compose(owner_class, core, **kwargs)
    record("compose_return")
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700, exist_ok=True)
    manager.executor.config.local_working_dir = str(workspace)
    registry = manager.executor._ensure_process_registry()
    original_shutdown = registry.shutdown

    def state():
        return [{"pid": p.pid, "generation": p.generation, "status": p.status,
                 "session_confirmed_empty": p.session_confirmed_empty,
                 "restored": p.restored,
                 "supervisorPid": getattr(getattr(p.process, "_worker", None), "pid", None)}
                for p in registry._processes.values()]

    async def shutdown():
        record("registry_shutdown_enter", records=state())
        try:
            result = await original_shutdown()
        except BaseException as exc:
            record("registry_shutdown_failed", error=type(exc).__name__, records=state())
            raise
        record("registry_shutdown_return", killed=result, records=state())
        return result

    registry.shutdown = shutdown
    original_close = manager.close

    async def close():
        record("management_close_enter", records=state())
        await original_close()
        record("management_close_return", records=state())

    manager.close = close

    async def admit():
        marker = root / "admitted.json"
        # Explicit fixture-owned restart fence, not production exactly-once.
        try:
            fd = os.open(root / "admission.fence", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            record("restart_no_readmission", records=state())
            return
        os.close(fd)
        command = " ".join(shlex.quote(arg) for arg in [sys.executable,
            str(Path(__file__).with_name("owned_execution.py")), str(root)])
        record("registry_start_enter")
        try:
            result = await registry.start("localhost", command, owner_id=core.authority.owner_id)
        except BaseException as exc:
            record("registry_start_failed", error=type(exc).__name__,
                   detail=str(exc), records=state())
            raise
        record("registry_start_return", result=result, records=state())
        if not state() or any(p["status"] != "running" for p in state()):
            raise RuntimeError(f"Original registry refused fixture admission: {result}")
        # The restart fence is not a readiness receipt. Descendants can write
        # effects before registry.start returns; publish only a complete receipt.
        pending = root / "admitted.pending"
        pending.write_text(json.dumps({"result": result, "records": state(),
                                      "corePid": os.getpid(), "test_only_composition_seam": True}))
        pending.chmod(0o600)
        os.replace(pending, marker)
        record("original_registry_admission", records=state())

    def completed(task):
        try:
            task.result()
        except BaseException as exc:
            record("admission_failed", error=type(exc).__name__, detail=str(exc), records=state())
            print(f"Fixture admission failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    task = asyncio.create_task(admit(), name="isolated-original-registry-admission")
    task.add_done_callback(completed)
    return manager


ManagementService.compose = classmethod(compose)
if os.environ.get("ODIN_APP_EXECUTION_SOURCE_BASELINE") == "1":
    namespace["ManagementService"].compose = classmethod(compose)
record("entry_main_enter")
try:
    entry.main()
except BaseException as exc:
    record("entry_main_failed", error=type(exc).__name__, detail=str(exc))
    raise
