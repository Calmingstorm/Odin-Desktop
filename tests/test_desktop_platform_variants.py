"""``@windows_variant`` and ``@darwin_variant``: Linux keeps the original object; Windows and
macOS route to their variants."""
from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path

import pytest

from src.desktop.platform.variants import darwin_variant, windows_variant

ROOT = Path(__file__).resolve().parents[1]


def doubled(value, *, scale=2):
    return value * scale


async def doubled_async(value, *, scale=2):
    await asyncio.sleep(0)
    return value * scale


def counted(limit):
    yield from range(limit)


def test_other_systems_get_the_original_function_object():
    def original(value, *, scale=2):
        return -value

    assert windows_variant("tests.test_desktop_platform_variants:doubled",
                           system="linux")(original) is original


def test_windows_routes_calls_with_the_same_arguments():
    def original(value, *, scale=2):
        return -value

    routed = windows_variant("tests.test_desktop_platform_variants:doubled",
                             system="win32")(original)
    assert routed is not original and routed.linux_original is original
    assert routed(3, scale=5) == 15 and routed.__name__ == "original"
    assert routed.windows_target == "tests.test_desktop_platform_variants:doubled"


def test_windows_routes_coroutines_and_generators():
    async def original_async(value, *, scale=2):
        return -value

    def original_generator(limit):
        yield -1

    routed_async = windows_variant("tests.test_desktop_platform_variants:doubled_async",
                                   system="win32")(original_async)
    assert inspect.iscoroutinefunction(routed_async)
    assert asyncio.run(routed_async(4, scale=3)) == 12
    routed_generator = windows_variant("tests.test_desktop_platform_variants:counted",
                                       system="win32")(original_generator)
    assert list(routed_generator(3)) == [0, 1, 2]


@pytest.mark.parametrize("target", ["", "module", ":name", "module:", "a:b:c"])
def test_a_target_names_one_function_in_one_module(target):
    with pytest.raises(ValueError):
        windows_variant(target, system="linux")


def _decorated(kind="windows_variant"):
    """Every ``@windows_variant("module:function")`` (or ``kind``) in the engine."""
    found = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and getattr(decorator.func, "id", "")
                        == kind and decorator.args
                        and isinstance(decorator.args[0], ast.Constant)):
                    found.append((path.relative_to(ROOT).as_posix(), node, decorator.args[0].value))
    return found


def _parameters(node):
    arguments = node.args
    return ([a.arg for a in arguments.posonlyargs + arguments.args], arguments.vararg is not None,
            [a.arg for a in arguments.kwonlyargs], arguments.kwarg is not None)


def test_every_variant_exists_with_the_original_parameters():
    """Checked statically, so Linux needs no Windows import to prove the routes."""
    decorated = _decorated()
    assert decorated, "no Windows variants found"
    for source, node, target in decorated:
        module, _, name = target.partition(":")
        module_path = ROOT / (module.replace(".", "/") + ".py")
        assert module_path.is_file(), f"{source}:{node.name} -> missing module {module}"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        definitions = {item.name: item for item in tree.body
                       if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert name in definitions, f"{source}:{node.name} -> {target} is not defined"
        variant = definitions[name]
        assert _parameters(variant) == _parameters(node), f"{source}:{node.name} -> {target}"
        assert isinstance(variant, ast.AsyncFunctionDef) == isinstance(node, ast.AsyncFunctionDef)


PINS = ROOT / "maintenance/windows-variant-sources.json"


def _original_sources(kind="windows_variant"):
    """SHA-256 of each routed Linux function's own source, from its def line to its end."""
    import hashlib

    sources = {}
    for source, node, target in _decorated(kind):
        lines = (ROOT / source).read_text(encoding="utf-8").splitlines()
        text = "\n".join(lines[node.lineno - 1:node.end_lineno]) + "\n"
        sources[f"{source}:{node.name} -> {target}"] = hashlib.sha256(text.encode()).hexdigest()
    return sources


def test_each_windows_variant_was_reviewed_against_its_linux_original():
    """A routed Linux function that changes needs its Windows variant reviewed.

    Update maintenance/windows-variant-sources.json only after that review:
    the variant mirrors the Linux body with its POSIX steps replaced.
    """
    import json

    recorded = json.loads(PINS.read_text(encoding="utf-8"))
    current = _original_sources()
    assert set(current) == set(recorded), "routed functions and pins differ"
    changed = sorted(key for key in current if current[key] != recorded[key])
    assert not changed, f"review these Windows variants against their changed originals: {changed}"


# Windows stand-ins for Odin code: the subclasses in windows_jobs.py, by what each leans
# on; the primitives windows_patch.py gives apply_patch.py (the whole file, whose os
# calls windows_dirfd.WindowsOs must cover); windows_remote's copies of the pinned
# ssh.py's runner, line reader and binary reader; and windows_tools' copy of the http_probe
# handler (browser_web.py stays upstream's byte for byte; the executor routes to the copy).
OVERRIDE_SOURCES = {
    "src/tools/apply_patch.py":
        "4bc3a7fba574c4fbc6eb2adea41384f8bbdb2c87cbf4897de0e58a3369013160",
    "src/tools/process_manager.py:ProcessRegistry._start_local_reserved":
        "3d6acead94fd543dbc33dcafb0b8d96a06897857325103011e32b5d3e303ea55",
    "src/tools/ssh.py:_read_lines_with_callback":
        "9a33f75e18fb7d77f2c1ad10be1c88efbc0a51610fcdb4a42417a42de75472c9",
    "src/tools/ssh.py:run_ssh_command":
        "9e861c3d3b4b2353ecb6d9b89cf4d2f47c31e5ba844bb084b1055880793c0607",
    "src/tools/handlers/browser_web.py:BrowserWebTools._handle_http_probe":
        "b539e2e3a11d0e5a5c8ce29f9ae972b3dc465fe8f4d27f4e8658ca01e0970657",
    "src/tools/ssh.py:read_binary_file":
        "f5a4a4dd520f80bfa8159ad1a0b1491372ebcaa5e836ab55fe4f1bdd4de335cf",
    "src/tools/local_supervisor.py:SupervisedShell":
        "8fc07a2abfe4f015b1cee1118338d2b544ff6476ed059ae0351ebad3ffecb2e9",
    "src/tools/risk_classifier.py:CommandGovernor.check":
        "24740ff045379a0076cf71b7f2d7b39e130ca1b62958f2616d254f8aac5dc4d7",
}


def _member_source(path: str, qualname: str = "") -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    if not qualname:
        return text
    node = ast.parse(text)
    for part in qualname.split("."):
        node = next(child for child in ast.iter_child_nodes(node)
                    if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == part)
    lines = text.splitlines()
    return "\n".join(lines[node.lineno - 1:node.end_lineno]) + "\n"


def test_windows_subclasses_were_reviewed_against_what_they_override():
    """Each stand-in must be reviewed when what it stands in for changes.

    ``WindowsProcessRegistry`` lifts the local start and ``JobShell`` stands in for the
    supervised shell; ``WindowsOs`` and the registry stand-ins serve ``apply_patch.py``.
    Update a digest here only after that review.
    """
    import hashlib

    changed = [key for key, digest in OVERRIDE_SOURCES.items()
               if hashlib.sha256(_member_source(*key.split(":")).encode()).hexdigest() != digest]
    assert not changed, f"review the Windows overrides of: {changed}"


# --- macOS: the same contract through @darwin_variant -----------------------------------------


@pytest.mark.parametrize("system", ["linux", "win32"])
def test_darwin_variants_leave_other_systems_the_original_object(system):
    def original(value, *, scale=2):
        return -value

    assert darwin_variant("tests.test_desktop_platform_variants:doubled",
                          system=system)(original) is original
    # And a Windows variant leaves macOS the original too.
    assert windows_variant("tests.test_desktop_platform_variants:doubled",
                           system="darwin")(original) is original


def test_darwin_routes_calls_coroutines_and_generators():
    def original(value, *, scale=2):
        return -value

    async def original_async(value, *, scale=2):
        return -value

    def original_generator(limit):
        yield -1

    routed = darwin_variant("tests.test_desktop_platform_variants:doubled",
                            system="darwin")(original)
    assert routed is not original and routed.linux_original is original
    assert routed(3, scale=5) == 15 and routed.__name__ == "original"
    assert routed.darwin_target == "tests.test_desktop_platform_variants:doubled"
    assert not hasattr(routed, "windows_target")
    routed_async = darwin_variant("tests.test_desktop_platform_variants:doubled_async",
                                  system="darwin")(original_async)
    assert asyncio.run(routed_async(4, scale=3)) == 12
    routed_generator = darwin_variant("tests.test_desktop_platform_variants:counted",
                                      system="darwin")(original_generator)
    assert list(routed_generator(3)) == [0, 1, 2]


def test_every_darwin_variant_exists_with_the_original_parameters():
    """Checked statically, so Linux needs no macOS import to prove the routes."""
    decorated = _decorated("darwin_variant")
    assert decorated, "no macOS variants found"
    for source, node, target in decorated:
        module, _, name = target.partition(":")
        assert module.startswith("src.desktop.platform."), f"{source}:{node.name} -> {target}"
        module_path = ROOT / (module.replace(".", "/") + ".py")
        assert module_path.is_file(), f"{source}:{node.name} -> missing module {module}"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        definitions = {item.name: item for item in tree.body
                       if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert name in definitions, f"{source}:{node.name} -> {target} is not defined"
        variant = definitions[name]
        assert _parameters(variant) == _parameters(node), f"{source}:{node.name} -> {target}"
        assert isinstance(variant, ast.AsyncFunctionDef) == isinstance(node, ast.AsyncFunctionDef)


MACOS_PINS = ROOT / "maintenance/macos-variant-sources.json"


def test_each_darwin_variant_was_reviewed_against_its_linux_original():
    """A routed Linux function that changes needs its macOS variant reviewed.

    Update maintenance/macos-variant-sources.json only after that review.
    """
    import json

    recorded = json.loads(MACOS_PINS.read_text(encoding="utf-8"))
    current = _original_sources("darwin_variant")
    assert set(current) == set(recorded), "routed functions and pins differ"
    changed = sorted(key for key in current if current[key] != recorded[key])
    assert not changed, f"review these macOS variants against their changed originals: {changed}"


def test_linux_runs_the_originals_and_imports_no_macos_module():
    import subprocess
    import sys

    program = (
        "import sys\n"
        "import src.__main__ as entry\n"
        "from src.desktop import commands, ipc_auth, paths, provisioning, resource_cleanup\n"
        "from src.desktop import ssh_sockets\n"
        "from src.health import checker\n"
        "from src.tools.hosts.control import HostEnrollmentManager\n"
        "routed = [entry._enable_process_containment, entry._arm_finalize_watchdog,\n"
        "          entry._zombie_reaper, checker._process_descriptor_usage,\n"
        "          resource_cleanup.current_boot_id, commands._anchored_database_path,\n"
        "          ssh_sockets.check_socket_path, ssh_sockets.socket_directory,\n"
        "          ssh_sockets.prepare_socket_directory, paths.private_directory,\n"
        "          ipc_auth.private_parent, ipc_auth.load_token,\n"
        "          provisioning.fresh_config_document, HostEnrollmentManager._test]\n"
        "assert not any(hasattr(f, 'darwin_target') for f in routed), routed\n"
        "assert commands._anchored_database_path(7, 'x.sqlite') == '/proc/self/fd/7/x.sqlite'\n"
        "loaded = [m for m in sys.modules if m.startswith('src.desktop.platform.')\n"
        "          and m.rsplit('.', 1)[1].startswith(('darwin', 'macos'))]\n"
        "assert not loaded, loaded\n"
    )
    if sys.platform not in ("linux", "win32"):
        pytest.skip("Linux's and Windows' own objects")
    result = subprocess.run([sys.executable, "-c", program], cwd=ROOT, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-3000:]


# macOS stand-ins for Odin code, each reviewed against what it lifts or overrides: macos_jobs'
# copies of create_supervised_shell, run_local_command and the registry's local start, and its
# registry overrides; macos_process's reaper subclass; macos_safety's copy of the governor check;
# the opening of apply_patch's command, which macos_jobs recognizes to give a local patch the
# engine's python3; and the macOS worker, which speaks Linux's protocol.
MACOS_OVERRIDE_SOURCES = {
    "src/tools/local_supervisor.py:create_supervised_shell":
        "912122289118a78f03b84fdd1ae86bddbd490285cf27db609055feb99aa3e8de",
    "src/tools/local_supervisor.py:SupervisedShell":
        "8fc07a2abfe4f015b1cee1118338d2b544ff6476ed059ae0351ebad3ffecb2e9",
    "src/tools/ssh.py:run_local_command":
        "06d309b7b49a31a5050d7b2fd7ffd690fa18938dc655d21abf70042addfc8e40",
    "src/tools/process_manager.py:ProcessRegistry._start_local_reserved":
        "3d6acead94fd543dbc33dcafb0b8d96a06897857325103011e32b5d3e303ea55",
    "src/tools/process_manager.py:ProcessRegistry._output_page":
        "a90dce9c71ed6831ba529b6ad761c90ad2d352a670388676a1662c51abc9b583",
    "src/tools/process_manager.py:ProcessRegistry.kill":
        "4dbfa9d34953eeb5090420dd015563c4a84aa0ce6f0ac2ff2297f31541fc7146",
    "src/tools/process_manager.py:ProcessRegistry._remote_cleanup_caveat":
        "c2be9d2577b0e06dfb60f73a7b4fcbd8bf45f0cb7059616c18b09fad245c55f0",
    "src/tools/process_manager.py:AdoptedZombieReaper":
        "0505a0aff99cca0d7d5bb037bf85a42dc9f03920b51412c908290ca921cbcc6a",
    "src/tools/risk_classifier.py:CommandGovernor.check":
        "24740ff045379a0076cf71b7f2d7b39e130ca1b62958f2616d254f8aac5dc4d7",
    "src/tools/local_supervisor_worker.py":
        "89cc24e74d3ef527e88a4d18b7f8898b11b03c8097630545e41b9e834ecd8865",
    "src/tools/handlers/files_docs.py:FilesDocsTools._handle_apply_patch":
        "caaa9d85787b51b7ebaa98d5e4e1d614300d11c0f33ed211b0c613956dfe6f9a",
}


def test_macos_stand_ins_were_reviewed_against_what_they_lift_or_override():
    """Update a digest here only after reviewing the macOS stand-in against the change."""
    import hashlib

    changed = [key for key, digest in MACOS_OVERRIDE_SOURCES.items()
               if hashlib.sha256(_member_source(*key.split(":")).encode()).hexdigest() != digest]
    assert not changed, f"review the macOS stand-ins for: {changed}"
