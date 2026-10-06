"""Worker dependency routing without native imports, buses or graphics."""
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.computer.runtime import dependency_resolver as resolver
from src.computer.runtime.gi_support import load_gi


def test_main_process_refuses_even_installed_gi(monkeypatch):
    monkeypatch.setattr(sys.modules["__main__"], "__file__", __file__)
    importer = Mock()
    monkeypatch.setattr(resolver.importlib, "import_module", importer)
    path, environment = list(sys.path), dict(os.environ)
    with pytest.raises(ImportError, match="^gi_worker_only$"):
        load_gi()
    importer.assert_not_called()
    assert sys.path == path and dict(os.environ) == environment


@pytest.mark.parametrize("name", ["worker.py", "x11_attached_worker.py", "x11_guardian.py"])
def test_only_retained_worker_entrypoints_resolve(monkeypatch, name):
    monkeypatch.setattr(sys.modules["__main__"], "__file__",
                        str(Path(resolver.__file__).with_name(name)))
    assert resolver._worker_process()
    existing = object()
    importer = Mock(return_value=existing)
    monkeypatch.setattr(resolver.importlib, "import_module", importer)
    environment, path = dict(os.environ), list(sys.path)
    assert load_gi() is existing
    assert dict(os.environ) == environment and sys.path == path


def test_same_named_foreign_worker_and_environment_claim_rejected(tmp_path, monkeypatch):
    fake = tmp_path / "worker.py"
    fake.write_text("pass")
    monkeypatch.setattr(sys.modules["__main__"], "__file__", str(fake))
    monkeypatch.setenv("ODIN_NATIVE_WORKER", "1")
    assert not resolver._worker_process()


def test_failed_loader_cleans_only_new_gi_modules(monkeypatch):
    import importlib.machinery
    from types import SimpleNamespace

    monkeypatch.setattr(resolver, "_worker_process", lambda: True)
    monkeypatch.setattr(resolver.importlib, "import_module",
                        Mock(side_effect=ModuleNotFoundError(name="gi")))
    safe = SimpleNamespace(st_mode=0o40755, st_uid=0)
    monkeypatch.setattr(resolver.Path, "lstat", lambda self: safe)
    monkeypatch.delitem(sys.modules, "gi", raising=False)
    retained = object()
    monkeypatch.setitem(sys.modules, "gi.retained", retained)
    monkeypatch.delitem(sys.modules, "gi.partial", raising=False)
    loader = Mock()
    loader.create_module.return_value = None
    def execute(module):
        sys.modules["gi.partial"] = object()
        raise RuntimeError("ABI mismatch")
    loader.exec_module.side_effect = execute
    monkeypatch.setattr(resolver.importlib.machinery.PathFinder, "find_spec",
                        Mock(return_value=importlib.machinery.ModuleSpec("gi", loader)))
    with pytest.raises(RuntimeError, match="ABI mismatch"):
        load_gi()
    assert "gi" not in sys.modules and "gi.partial" not in sys.modules
    assert sys.modules["gi.retained"] is retained
