"""Pinned fresh profile parity. Static check imports only the standard library."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ARCHIVE = "maintenance/odin-v4.13.0.tar.gz"
ARCHIVE_SHA256 = "845d783bd4ee46cd44e63d56532512fd9cef10d08b1432e45047d155c6b348d0"
PROOF = "maintenance/fresh-profile-parity.json"
GENERATOR = "scripts/maintenance/fresh_profile_parity.py"
TEST = "tests/test_desktop_fresh_profile_parity.py"
CITATIONS = ("docs/design/00-brief.md", "docs/design/prompt-changes.md")
BASELINE_OBSERVATION_SHA256 = "73649ce984d9d1564d54a38010af2d98124911779d708acfca0adced90df73e8"
DESKTOP_OBSERVATION_SHA256 = "fd705fd055b4af81c3bdee0a775dea89828de1fe3864ed9bd5de1fa4fae7936c"
DELTA_SHA256 = "76035be1e5267c2bc2ae6e51a02a478b98da2fb556ee46fe1a6f93068723b1b0"
ABSENT = {"absent": True}


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flatten(node, prefix="settings"):
    result = {}
    if isinstance(node, dict) and node:
        for key, value in sorted(node.items()):
            result.update(flatten(value, prefix + "." + key))
    else:
        result[prefix] = node
    return result


def source_paths(root):
    directories = ("src/config", "src/permissions", "src/tools/hosts", "src/tools/handlers")
    explicit = ("src/desktop/authority.py", "src/desktop/paths.py", "src/desktop/provisioning.py",
                "src/desktop/settings.py", "src/desktop/secrets.py", "src/runtime_paths.py",
                "src/reasoning.py", "src/tools/executor.py", "src/tools/builtin_policy.py",
                "src/tools/http_probe_ops.py", "src/tools/risk_classifier.py",
                "src/llm/model_ref.py",
                "src/json_store.py", "src/odin_log/__init__.py", "src/odin_log/logger.py")
    return sorted({GENERATOR, TEST, *CITATIONS, *explicit, *(
        str(path.relative_to(root)) for directory in directories
        for path in (root / directory).rglob("*.py")
    )})


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def approval_for(path):
    removed = {"discord.allowed_users", "discord.channels", "discord.ignore_bot_ids",
               "discord.require_mention", "discord.respond_to_bots", "discord.token",
               "web.api_token", "web.api_tokens", "web.enabled",
               "web.host", "web.port", "web.session_timeout_minutes", "web.trusted_proxies",
               "permissions.default_tier", "permissions.overrides_path", "permissions.tiers"}
    if path.removeprefix("settings.") in removed:
        return {"kind": "removed surface", "status": "approved",
                "reference": "docs/design/00-brief.md; decisions D1, D6, D17 rows"}
    relocated = {
        "context.directory", "sessions.persist_directory", "tools.local_working_dir",
        "tools.ssh_key_path", "tools.ssh_known_hosts_path", "tools.ssh_pool.socket_dir",
        "tools.audit_log_path", "tools.trajectory_path", "logging.directory", "usage.directory",
        "openai_codex.credentials_path", "search.search_db_path", "turn_state.db_path",
        "attachments.temp_directory", "computer.storage_dir",
    }
    if path.removeprefix("settings.") in relocated:
        return {"kind": "D-decision", "status": "approved",
                "reference": "docs/design/00-brief.md; decision D5 row (independent fresh state)"}
    ingress = {"settings.webhook.bind_address", "settings.webhook.port",
               "settings.webhook.secret", "settings.webhook.triggers"}
    if path in ingress:
        return {"kind": "D-decision", "status": "approved",
                "reference": ("docs/design/00-brief.md; decision D10 row (opt-in LAN/tailnet "
                              "listener with per-trigger secrets)")}
    renames = {"settings.webhook.channel_id", "settings.webhook.gitea_channel_id",
               "settings.webhook.github_channel_id", "settings.webhook.gitlab_channel_id",
               "settings.webhook.conversation_id", "settings.webhook.gitea_conversation_id",
               "settings.webhook.github_conversation_id", "settings.webhook.gitlab_conversation_id",
               "settings.monitoring.alert_channel_id", "settings.monitoring.alert_conversation_id"}
    if path in renames:
        return {"kind": "prompt-changes", "status": "approved",
                "reference": ("docs/design/prompt-changes.md; part C interface changes, "
                              "channel-ID removal")}
    if path in {"access.unauthenticated_hosts", "settings.tools.governor.admin_can_override",
                "settings.tools.governor.owner_can_override"}:
        return {"kind": "D-decision", "status": "approved",
                "reference": ("docs/design/00-brief.md; decision D17 row "
                              "(owner follows admin override)")}
    return {"kind": "unknown", "reference": "", "status": "unknown"}


def differences(baseline, desktop):
    return [{"path": key, "baseline": baseline.get(key, ABSENT),
             "desktop": desktop.get(key, ABSENT), "approval": approval_for(key)}
            for key in sorted(baseline.keys() | desktop.keys())
            if baseline.get(key, ABSENT) != desktop.get(key, ABSENT)]


def check(root):
    """Static closure gate. Dynamic tests separately compare collect() in full."""
    root = Path(root)
    errors, count = [], 0
    try:
        proof = json.loads((root / PROOF).read_text(), object_pairs_hook=_unique)
        if set(proof) != {"schema_version", "baseline_sha256", "hashes", "observations", "deltas"}:
            raise ValueError("unexpected or missing proof fields")
        if type(proof["schema_version"]) is not int or proof["schema_version"] != 1:
            raise ValueError("unsupported schema_version")
        if (proof["baseline_sha256"] != ARCHIVE_SHA256
                or file_hash(root / ARCHIVE) != ARCHIVE_SHA256):
            errors.append("pinned archive hash mismatch")
        paths = source_paths(root)
        if not isinstance(proof["hashes"], dict):
            raise ValueError("hashes must be a map")
        if set(proof["hashes"]) != set(paths):
            errors.append("missing/extra source or approval hashes")
        for path in paths:
            if proof["hashes"].get(path) != file_hash(root / path):
                errors.append(f"stale hash: {path}")
        if proof["observations"] != {
            "baseline_sha256": BASELINE_OBSERVATION_SHA256,
            "desktop_sha256": DESKTOP_OBSERVATION_SHA256,
        }:
            errors.append("observation digest missing, changed or incomplete")
        deltas = expand_deltas(proof["deltas"])
        if digest(deltas) != DELTA_SHA256:
            errors.append("delta list omits, duplicates, adds or changes values")
        count = len(deltas)
        for row in deltas:
            if set(row) != {"path", "baseline", "desktop", "approval"}:
                errors.append("invalid delta shape")
            if row["approval"] != approval_for(row["path"]):
                errors.append(f"unrecognized approval: {row['path']}")
            if row["approval"]["status"] != "approved":
                errors.append(f"unknown approval: {row['path']}")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(f"invalid parity proof: {exc}")
    return {"valid": not errors, "status": "blocked" if errors else "pass",
            "errors": errors, "delta_count": count}


report = check


def expand_deltas(rows):
    """Compact row = [path, old, new, approval citation]. Never wildcard approval."""
    result = []
    for row in rows:
        if isinstance(row, dict):
            result.append(row)
            continue
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError("delta row needs exact path, values and citation")
        path, old, new, citation = row
        approval = approval_for(path)
        expected = ("D10" if "decision D10" in approval["reference"] else
                    "D5" if "decision D5" in approval["reference"] else
                    "D17" if "decision D17" in approval["reference"] else
                    "removed surface" if approval["kind"] == "removed surface" else
                    "prompt-changes C" if approval["kind"] == "prompt-changes" else "unknown")
        if citation != expected:
            raise ValueError(f"unrecognized citation for {path}")
        result.append({"path": path, "baseline": old, "desktop": new, "approval": approval})
    return result


def _baseline_worker(root):
    from src.config.schema import load_config
    from src.permissions.host_access import HostAccessManager
    from src.permissions.manager import PermissionManager

    config = load_config(root / "config.yml")
    access = HostAccessManager(str(root / "fresh-host-access.json"),
                               available_hosts=list(config.tools.hosts))
    permissions = PermissionManager(config.permissions.tiers, config.permissions.default_tier,
                                    str(root / "fresh-permissions.json"))
    values = flatten(config.model_dump(mode="json"))
    values.update({"access.owner_hosts": access.get_allowed_hosts("fresh-owner"),
                   "access.unauthenticated_hosts": access.get_allowed_hosts("fresh-owner"),
                   "access.preference_default": access.get_default_host("fresh-owner"),
                   "access.owner_tool_names": permissions.allowed_tool_names("fresh-owner")})
    values.update(_runtime_selection(config, permissions, access, "fresh-owner"))
    print(json.dumps(values, sort_keys=True))


def _runtime_selection(config, permissions, access, owner, paths=None):
    import asyncio
    from types import SimpleNamespace

    from src.tools.builtin_policy import BuiltinToolPolicy
    from src.tools.executor import ToolExecutor

    executor = ToolExecutor(config.tools, permission_manager=permissions,
                            host_access_manager=access, app_config=config,
                            **({"profile_paths": paths} if paths else {}))
    if paths:
        executor._builtin_policy = BuiltinToolPolicy(
            lambda: SimpleNamespace(tools=config.tools),
            lambda: {"run_command": True, "http_probe": True})
    else:
        executor._builtin_policy = BuiltinToolPolicy(lambda: SimpleNamespace(tools=config.tools))
    calls = []

    async def harmless(address, command, ssh_user, **kwargs):
        calls.append({"address": address, "ssh_user": ssh_user,
                      "target": kwargs.get("target").alias if kwargs.get("target") else None})
        return 0, "fresh parity stub"

    executor._exec_command = harmless

    async def run():
        result = {}
        for name, tool, payload in (
            ("omitted_host", "run_command", {"command": "printf fresh"}),
            ("explicit_host", "run_command", {"host": "localhost", "command": "printf fresh"}),
            ("http_probe_local_fallback", "http_probe", {"url": "https://example.invalid"}),
        ):
            response = await executor.execute(tool, payload, user_id=owner)
            if not response.ok or not calls:
                raise RuntimeError(f"runtime {name} failed: {response}")
            result["runtime." + name] = calls.pop()
        return result

    return asyncio.run(run())


def collect(root):
    """Run only under the non-root isolated test launcher, never in a live profile."""
    import os
    import re
    import subprocess
    import sys
    import tarfile
    import tempfile
    from unittest.mock import patch

    if os.geteuid() == 0:
        raise RuntimeError("collect requires non-root isolated test runner")
    from src.desktop.authority import OwnerAuthority
    from src.desktop.paths import ProfilePaths
    from src.desktop.provisioning import ensure_profile
    from src.desktop.settings import SettingsService
    from src.permissions.host_access import HostAccessManager
    from src.permissions.manager import PermissionManager
    from src.tools.hosts import HostRegistry

    root = Path(root)
    if file_hash(root / ARCHIVE) != ARCHIVE_SHA256:
        raise ValueError("pinned archive hash mismatch")
    with tempfile.TemporaryDirectory(prefix="odin-fresh-parity-") as temporary:
        work = Path(temporary)
        baseline_root = work / "baseline"
        baseline_root.mkdir()
        with tarfile.open(root / ARCHIVE, "r:gz") as archive:
            for member in archive.getmembers():
                selected = member.name == "config.yml" or member.name.startswith("src/")
                if selected and member.isfile():
                    path = baseline_root / member.name
                    if path.is_relative_to(baseline_root) and ".." not in Path(member.name).parts:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(archive.extractfile(member).read())
        env = {"PATH": os.environ["PATH"], "HOME": str(work / "home"),
               "DISCORD_TOKEN": "fresh-fixture", "PYTHONPATH": str(baseline_root),
               "ODIN_ENV_FILE": str(work / "absent.env")}
        template = (baseline_root / "config.yml").read_text()
        for name in re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", template):
            env[name] = "fresh-fixture"
        worker = subprocess.run(
            [sys.executable, str(root / GENERATOR), "_baseline", str(baseline_root)],
            cwd=baseline_root, env=env, capture_output=True, text=True, timeout=60)
        if worker.returncode:
            raise RuntimeError(worker.stderr)
        baseline = json.loads(worker.stdout)
        paths = ProfilePaths.from_xdg(home=work / "desktop", environ={})
        authority = OwnerAuthority(paths)
        try:
            # Fresh timezone is machine-dependent; pin this parity fixture's
            # system zone, just as its HOME/credentials are pinned above. Actual
            # detection and existing-profile preservation have provisioning tests.
            with patch.dict(os.environ, {"TZ": "UTC"}):
                config = ensure_profile(paths, authority=authority)
            service = SettingsService(paths, None, config=config)
            desktop = flatten(service.config.model_dump(mode="json"))
            for key, value in desktop.items():
                if isinstance(value, str) and value.startswith(str(work / "desktop")):
                    desktop[key] = value.replace(str(work / "desktop"), "$PROFILE_HOME", 1)
            registry = HostRegistry(config.tools.hosts, profile_paths=paths)
            permissions = PermissionManager(authority)
            access = HostAccessManager(paths.config_dir / "host-preferences.json",
                                       available_hosts_provider=registry.active_aliases,
                                       permission_manager=permissions)
            desktop["access.unauthenticated_hosts"] = access.get_allowed_hosts(authority.owner_id)
            context = authority.authenticate_local(peer_uid=os.geteuid())
            token = permissions.set_request_owner(context)
            try:
                owner = authority.owner_id
                desktop.update({"access.owner_hosts": access.get_allowed_hosts(owner),
                                "access.preference_default": access.get_default_host(owner),
                                "access.owner_tool_names": permissions.allowed_tool_names(owner)})
                desktop.update(_runtime_selection(config, permissions, access, owner, paths))
            finally:
                permissions.reset_request_owner(token)
        finally:
            authority.release_runtime()
        for key, value in baseline.items():
            if isinstance(value, str) and value.startswith(str(baseline_root)):
                baseline[key] = value.replace(str(baseline_root), "$BASELINE_INSTALL", 1)
    return {"baseline": baseline, "desktop": desktop}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("report", "_baseline"))
    parser.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args()
    if args.command == "_baseline":
        _baseline_worker(Path(args.root))
    else:
        print(json.dumps(check(Path(args.root)), indent=2))
