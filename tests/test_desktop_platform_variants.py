"""``@windows_variant``: Linux keeps the original object; Windows routes to the variant."""
from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path

import pytest

from src.desktop.platform.variants import windows_variant

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


def _decorated():
    """Every ``@windows_variant("module:function")`` in the engine, with its parameters."""
    found = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and getattr(decorator.func, "id", "")
                        == "windows_variant" and decorator.args
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


def _original_sources():
    """SHA-256 of each routed Linux function's own source, from its def line to its end."""
    import hashlib

    sources = {}
    for source, node, target in _decorated():
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
# on, and the primitives windows_patch.py gives apply_patch.py (the whole file, whose os
# calls windows_dirfd.WindowsOs must cover).
OVERRIDE_SOURCES = {
    "src/tools/apply_patch.py":
        "0c98e655530fa8d5814b83058baf1bf44461d2deb0048d70566967ef53ca8636",
    "src/tools/process_manager.py:ProcessRegistry._start_local_reserved":
        "3d6acead94fd543dbc33dcafb0b8d96a06897857325103011e32b5d3e303ea55",
    "src/tools/local_supervisor.py:SupervisedShell":
        "8fc07a2abfe4f015b1cee1118338d2b544ff6476ed059ae0351ebad3ffecb2e9",
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

