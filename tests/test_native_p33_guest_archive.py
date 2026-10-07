"""Small-fixture tests for the reusable P3.3 guest source archive."""

import ast
import importlib.util
import re
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "native_p33_guest_archive", ROOT / "scripts/qualification/lab/guest_archive.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def fixture_root(tmp_path):
    for relative in builder.GUEST_SOURCES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# fixture: {relative}\n")
    return tmp_path


def test_archive_contains_all_guest_imported_and_launched_sources(tmp_path):
    root = fixture_root(tmp_path / "repo")
    destination = tmp_path / "guest.tar.gz"
    names = builder.archive_sources(root, destination)

    with tarfile.open(destination, "r:gz") as archive:
        assert set(archive.getnames()) == set(builder.GUEST_SOURCES)
        assert set(names) == set(builder.GUEST_SOURCES)
        for name in builder.GUEST_SOURCES:
            assert archive.extractfile(name).read() == (root / name).read_bytes()


def test_reviewed_archive_covers_actual_local_import_and_launch_dependencies():
    # Derive edges from the real helpers, not from fake files or the allowlist.
    # External Node/Python packages and built engine/app trees are separately
    # provisioned. Local imports and repository-relative launches belong here.
    required = set()
    for relative in builder.GUEST_SOURCES:
        source = ROOT / relative
        text = source.read_text()
        if source.suffix == ".mjs":
            for name in re.findall(r"from ['\"](\./[^'\"]+)['\"]", text):
                required.add(str((source.parent / name).resolve().relative_to(ROOT)))
            required.update(re.findall(r"join\(repository, ['\"]([^'\"]+\.py)['\"]\)", text))
        if source.suffix != ".py":
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = source.parent / (node.module.replace(".", "/") + ".py")
                if imported.is_file():
                    required.add(str(imported.relative_to(ROOT)))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "with_name" and node.args:
                    argument = node.args[0]
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        target = source.parent / argument.value
                        if target.is_file():
                            required.add(str(target.relative_to(ROOT)))
            # Resolve literal repository-path suffixes, including notification
            # fixture's Path(__file__).parents[2] / 'app/fixture-core/fixture_core.py'.
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                candidate = ROOT / node.value
                if "/" in node.value and candidate.is_file() and candidate.suffix == ".py":
                    required.add(node.value)
    assert "app/fixture-core/fixture_core.py" in required
    assert "tests/desktop_fixtures/private_notification_server.py" in required
    assert "app/scripts/native-p33-display.mjs" in required
    assert required <= set(builder.GUEST_SOURCES), sorted(required - set(builder.GUEST_SOURCES))


def test_fixture_core_is_required_and_missing_dependency_fails(tmp_path):
    root = fixture_root(tmp_path / "repo")
    (root / "app/fixture-core/fixture_core.py").unlink()
    with pytest.raises(ValueError, match="Unsafe or missing"):
        builder.archive_sources(root, tmp_path / "guest.tar.gz")
    assert not (tmp_path / "guest.tar.gz").exists()


@pytest.mark.parametrize("kind", ["leaf", "parent"])
def test_symlink_sources_are_refused(tmp_path, kind):
    root = fixture_root(tmp_path / "repo")
    source = root / builder.GUEST_SOURCES[0]
    if kind == "leaf":
        source.unlink()
        source.symlink_to(root / builder.GUEST_SOURCES[1])
    else:
        directory = source.parent
        moved = root / "moved"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsafe or missing"):
        builder.archive_sources(root, tmp_path / "guest.tar.gz")


def test_existing_archive_is_never_overwritten(tmp_path):
    root = fixture_root(tmp_path / "repo")
    destination = tmp_path / "guest.tar.gz"
    destination.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="replace"):
        builder.archive_sources(root, destination)
    assert destination.read_bytes() == b"preserve"
