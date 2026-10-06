#!/usr/bin/env python3
"""Isolated app E2E launch adapter, never a production core entry point.

Launch with engine Python, this file, and the normal app-appended core argv.
ODIN_SMOKE_CONTROL is a private JSON file below the isolation runner's HOME:
keyring=healthy|locked|missing, auth=pending|success|expired, probe_failure,
saved_only, guard_degraded, authorized, and optional provider_mode (or provider)
codex|ollama|compat. Boolean controls default false; auth defaults pending.

Only external boundaries are deterministic. Core ownership, journals, settings,
credential sanitization, provider transactions, construction and adoption are
real. saved_only/provider_mode describe the scenario; they do not mutate config
or impersonate effective readiness. A second launch preserves real saved settings
but has the real lazy graph until an explicit settings/model apply.

No token is written by this adapter. The sole persistence surrogate is the
authorized boolean, written after a successful in-memory codex_accounts write;
on the next process launch it recreates the known synthetic account in memory.
This proves app persistence/re-entry behavior, not OS keyring durability or OAuth.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time


REPOSITORY = Path(__file__).resolve().parents[3]


def refuse(message: str) -> None:
    raise RuntimeError(f"Auth E2E adapter refused: {message}")


def private_directory(path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
            or path.resolve() != path):
        refuse("HOME/XDG must be owned, private real directories")


def assert_isolation() -> Path:
    """Check evidence before importing or constructing any engine component."""
    if sys.platform != "linux" or os.geteuid() == 0:
        refuse("Linux and an unprivileged user are required")
    outer = os.environ.get("ODIN_REAL_CORE_OUTER_PID_NS")
    if not outer or os.readlink("/proc/self/ns/pid") == outer:
        refuse("a separate PID namespace is required")
    init = Path("/proc/1/cmdline").read_bytes().split(b"\0")
    runner = str(REPOSITORY / "app/scripts/real-core-isolation.mjs").encode()
    if runner not in init or b"--inside-run" not in init:
        refuse("namespace PID 1 is not the repository isolation runner")
    root = Path(os.environ.get("ODIN_REAL_CORE_ROOT", ""))
    if (not root.is_absolute() or root.parent != Path(tempfile.gettempdir())
            or not root.name.startswith("odrc-")
            or os.environ.get("HOME") != str(root)):
        refuse("the runner's disposable HOME is required")
    private_directory(root)
    for key, leaf in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                      ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "run")):
        path = root / leaf
        if os.environ.get(key) != str(path):
            refuse("unsafe XDG root")
        private_directory(path)
    if any(key.startswith("DBUS_") for key in os.environ):
        refuse("D-Bus environment must be absent")
    return root


class Control:
    _KEYS = frozenset({"keyring", "auth", "probe_failure", "saved_only", "unlock_calls",
                       "guard_degraded", "authorized", "provider_mode", "provider"})

    def __init__(self, root: Path):
        self.root = root
        self.path = Path(os.environ.get("ODIN_SMOKE_CONTROL", ""))
        if (not self.path.is_absolute() or self.path.resolve() != self.path
                or not self.path.is_relative_to(root) or self.path == root):
            refuse("ODIN_SMOKE_CONTROL must be a real file inside disposable HOME")
        self.read()

    def read(self) -> dict:
        # Atomic replacement by the Node orchestrator is supported. No symlink
        # is followed even when it changes modes while the core is running.
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 8192
                    or self.path.resolve() != self.path):
                refuse("control must be a bounded private owned JSON file")
            with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as stream:
                value = json.load(stream)
        finally:
            os.close(fd)
        if not isinstance(value, dict) or set(value) - self._KEYS:
            refuse("unknown control fields")
        if value.get("keyring", "healthy") not in {"healthy", "locked", "missing"}:
            refuse("invalid keyring control")
        if value.get("auth", "pending") not in {"pending", "success", "expired"}:
            refuse("invalid auth control")
        if type(value.get("unlock_calls", 0)) is not int or not 0 <= value.get("unlock_calls", 0) <= 100:
            refuse("invalid unlock count")
        for key in ("probe_failure", "saved_only", "guard_degraded", "authorized"):
            if key in value and type(value[key]) is not bool:
                refuse("control flags must be booleans")
        for key in ("provider_mode", "provider"):
            if key in value and value[key] not in {"codex", "ollama", "compat"}:
                refuse("invalid provider control")
        return value

    def mark_authorized(self, authorized: bool) -> None:
        value = self.read()
        value["authorized"] = authorized
        # Modes/booleans only, never a credential fallback or shadow vault.
        fd, temporary = tempfile.mkstemp(prefix=".auth-control-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def credentials() -> dict:
    return {"access_token": "E2E-OAUTH-ACCESS-NEVER-RENDER",
            "refresh_token": "E2E-OAUTH-REFRESH-NEVER-RENDER",
            "account_id": "e2e-test-account", "email": "e2e@example.invalid",
            "expires_at": 4102444800, "plan_type": "test"}


class MemoryKeyring:
    """Exercise the production secret wrapper with actual keyring exceptions."""

    def __init__(self, control: Control):
        self.control = control
        self.values: dict[tuple[str, str], str] = {}
        self._seed_codex = control.read().get("authorized", False)

    def _check(self) -> None:
        from keyring.errors import KeyringLocked, NoKeyringError

        mode = self.control.read().get("keyring", "healthy")
        if mode == "locked":
            raise KeyringLocked("Synthetic test keyring is locked")
        if mode == "missing":
            raise NoKeyringError("Synthetic test keyring is unavailable")

    def unlock(self) -> bool:
        value = self.control.read()
        if value.get("keyring") == "locked":
            value["unlock_calls"] = value.get("unlock_calls", 0) + 1
            value["keyring"] = "healthy"
            fd, temporary = tempfile.mkstemp(prefix=".unlock-control-", dir=self.control.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(value, stream, sort_keys=True)
                os.replace(temporary, self.control.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        self._check()
        return True

    def get_password(self, service: str, name: str) -> str | None:
        self._check()
        key = (service, name)
        if name == "codex_accounts" and self._seed_codex and key not in self.values:
            self.values[key] = json.dumps([credentials()])
        return self.values.get(key)

    def set_password(self, service: str, name: str, value: str) -> None:
        self._check()
        self.values[service, name] = value
        if name == "codex_accounts":
            raw = json.loads(value)
            rows = raw if isinstance(raw, list) else [raw]
            authorized = any(isinstance(row, dict) and bool(row.get("access_token"))
                             for row in rows)
            self.control.mark_authorized(authorized)
            self._seed_codex = authorized

    def delete_password(self, service: str, name: str) -> None:
        self._check()
        self.values.pop((service, name), None)
        if name == "codex_accounts":
            self.control.mark_authorized(False)
            self._seed_codex = False


class DeterministicGuard:
    def __init__(self, control: Control):
        self.control = control

    def is_usable(self, name: str) -> bool:
        return not self.control.read().get("guard_degraded", False)

    def is_available(self, name: str) -> bool:
        return not self.control.read().get("guard_degraded", False)


async def run(root: Path, control: Control) -> int:
    # Do this before engine imports, so every module sees the blocked boundary.
    import aiohttp

    def no_network(*args, **kwargs):
        raise RuntimeError("Outbound aiohttp is disabled in the auth E2E adapter")

    aiohttp.ClientSession = no_network
    sys.path.insert(0, str(REPOSITORY))
    from src.cli import parse_core_args
    from src.desktop import codex_accounts, providers
    from src.desktop.core import CoreService

    options = parse_core_args(sys.argv[1:])
    for path in (options.socket, options.token_file, options.paths.config_dir,
                 options.paths.data_dir, options.paths.cache_dir, options.paths.secrets_dir):
        if not path.resolve().is_relative_to(root):
            refuse("all core paths must remain inside disposable HOME")

    class DeviceClient(codex_accounts.CodexDeviceClient):
        async def request_device_code(self):
            return {"device_auth_id": "E2E-DEVICE-SECRET-NEVER-RENDER",
                    "user_code": "TEST-CODE", "interval": 1,
                    "verify_url": "https://auth.openai.com/codex/device",
                    "expires_in": (0.1 if control.read().get("auth") == "expired" else 900)}

        async def poll_device_auth_once(self, device_auth_id, user_code):
            mode = control.read().get("auth", "pending")
            if mode == "expired":
                # Also expire an already-open pending login on a control change.
                # Production checks its real deadline again after this boundary.
                for login in service.management.codex._logins.values():
                    login.deadline = time.monotonic() - 1
                return None
            return credentials() if mode == "success" else None

    class Owner(providers.ProviderOwner):
        @property
        def subsystem_guard(self):
            return DeterministicGuard(control) if control.read().get("guard_degraded") else None

        @subsystem_guard.setter
        def subsystem_guard(self, value):
            # LLMGateway assigns its constructor default; preserve absence.
            pass

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # No positive-health admission gate: the real matching adopted graph
            # is effective. This guard supplies only explicit observed failure;
            # it never substitutes for construction/adoption or a generation.

        async def _probe_openai_compatible(self, candidate):
            return "Synthetic provider qualification failed" if control.read().get("probe_failure") else None

        async def _probe_aux(self, candidate):
            return "Synthetic auxiliary qualification failed" if control.read().get("probe_failure") else None

    codex_accounts.CodexDeviceClient = DeviceClient
    providers.ProviderOwner = Owner
    service = CoreService(options.paths, options.socket, options.token_file,
                          secret_backend=MemoryKeyring(control))
    return await service.run()


def main() -> int:
    try:
        root = assert_isolation()
        return asyncio.run(run(root, Control(root)))
    except Exception as exc:
        # Never print arbitrary exception bodies (which may include input or
        # credential bytes). The integration runner measures app/core outcomes.
        diagnostic = str(exc) if str(exc).startswith("Auth E2E adapter refused:") else type(exc).__name__
        print(f"Auth E2E adapter failed or refused unsafe launch: {diagnostic}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
