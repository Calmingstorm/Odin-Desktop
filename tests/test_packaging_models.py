"""Pinned model staging and install-relative resolution, without native imports."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

from src.search import bundled_models
from src.search.embedder import LocalEmbedder

MODULE = Path(__file__).parents[1] / "app" / "packaging" / "python" / "models.py"
spec = importlib.util.spec_from_file_location("packaging_models", MODULE)
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)


@pytest.fixture
def assets(tmp_path, monkeypatch):
    body = b"pinned-model-test-bytes"
    pins = {
        name: (hashlib.sha256(body).hexdigest(), len(body), f"https://example.invalid/{name}")
        for name in ("model_optimized.onnx", "LICENSE")
    }
    monkeypatch.setattr(models, "ASSETS", pins)
    cache = tmp_path / "cache" / "models" / "bge-small-en-v1.5"
    cache.mkdir(parents=True)
    for name in pins:
        (cache / name).write_bytes(body)
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *a, **k: pytest.fail("unexpected network"))
    return body, cache


def test_cached_stage_is_offline_reproducible_and_closed(tmp_path, assets):
    body, _ = assets
    root = tmp_path / "bundle with spaces"
    metadata = models.stage_models(root, tmp_path / "cache")
    assert models.stage_models(root, tmp_path / "cache") == metadata
    assert metadata["license"] == "MIT"
    assert metadata["revision"] == models.REVISION
    for item in metadata["files"]:
        path = root / item["path"]
        assert path.read_bytes() == body
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    destination = root / models.MODEL_ROOT
    (destination / "unlisted").write_bytes(b"unlisted")
    with pytest.raises(ValueError, match="inventory mismatch"):
        models.stage_models(root, tmp_path / "cache")


def test_corrupt_cache_never_enters_bundle(tmp_path, assets):
    body, cache = assets
    (cache / "model_optimized.onnx").write_bytes(b"X" * len(body))
    root = tmp_path / "bundle"
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        models.stage_models(root, tmp_path / "cache")
    assert not (root / models.MODEL_ROOT).exists()


def test_changed_engine_dependency_requires_model_pin_audit(tmp_path, monkeypatch):
    lock = tmp_path / "uv.lock"
    lock.write_text('[[package]]\nname="fastembed"\nversion="99.0.0"\n')
    monkeypatch.setattr(models, "UV_LOCK", lock)
    with pytest.raises(ValueError, match="audited FastEmbed"):
        models.stage_models(tmp_path / "bundle", tmp_path / "cache")
    assert not (tmp_path / "bundle").exists()


def test_symlink_cache_is_not_a_model_input(tmp_path, assets):
    _, cache = assets
    model = cache / "model_optimized.onnx"
    model.unlink()
    model.symlink_to(cache / "LICENSE")
    with pytest.raises(ValueError, match="regular file"):
        models.stage_models(tmp_path / "bundle", tmp_path / "cache")


def test_download_is_size_bounded_and_never_caches_invalid_bytes(tmp_path, monkeypatch):
    import io

    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"too long"))
    target = tmp_path / "asset"
    with pytest.raises(ValueError, match="exceeds pinned size"):
        models._fetch(target, "0" * 64, 1, "https://example.invalid/model")
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_download_requires_exact_digest_then_can_reuse_offline(tmp_path, monkeypatch):
    import io

    body = b"good"
    digest = hashlib.sha256(body).hexdigest()
    target = tmp_path / "asset"
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"evil"))
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        models._fetch(target, digest, len(body), "https://example.invalid/model")
    assert not target.exists()
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(body))
    models._fetch(target, digest, len(body), "https://example.invalid/model")
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network"))
    models._fetch(target, digest, len(body), "https://example.invalid/model")
    assert target.read_bytes() == body


def test_default_resolution_requires_noneditable_packaged_install(tmp_path, monkeypatch):
    prefix = tmp_path / "relocated resources" / "runtime" / "python"
    installed = prefix / "lib" / f"python{bundled_models.sys.version_info.major}.{bundled_models.sys.version_info.minor}" / "site-packages"
    monkeypatch.setattr(bundled_models.sys, "prefix", str(prefix))
    assert bundled_models.bundled_model_roots() == ()  # actual checkout is not admitted
    monkeypatch.setattr(bundled_models, "__file__", str(installed / "src/search/bundled_models.py"))
    expected = prefix.parent / "models" / "bge-small-en-v1.5"
    assert bundled_models.bundled_model_roots() == (expected,)
    assert LocalEmbedder()._model_roots == (expected,)
    assert LocalEmbedder(model_roots=())._model_roots == ()
    monkeypatch.setenv("HF_HOME", str(tmp_path / "ambient-cache"))
    monkeypatch.setenv("ODIN_MODEL_ROOT", str(tmp_path / "untrusted"))
    assert bundled_models.bundled_model_roots() == (expected,)
    monkeypatch.setattr(bundled_models.sys, "prefix", "/usr")
    assert bundled_models.bundled_model_roots() == ()


@pytest.mark.asyncio
async def test_explicit_offline_local_load_failure_can_retry(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    attempts = []

    class Model:
        def __init__(self, name, **kwargs):
            assert kwargs["local_files_only"] is True
            assert kwargs["specific_model_path"] == str(tmp_path)
            attempts.append(name)
            if len(attempts) == 1:
                raise RuntimeError("local load failed")

        def embed(self, texts):
            return [SimpleNamespace(tolist=lambda: [1.0] * 384)]

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=Model))
    embedder = LocalEmbedder(model_roots=[tmp_path])
    assert await embedder.embed("first") is None
    assert await embedder.embed("retry") == [1.0] * 384
    assert attempts == [LocalEmbedder.MODEL, LocalEmbedder.MODEL]


def test_the_windows_runtime_keeps_its_packages_in_lib_site_packages(tmp_path, monkeypatch):
    prefix = tmp_path / "Programs" / "Odin" / "resources" / "runtime" / "python"
    installed = prefix / "Lib" / "site-packages"
    monkeypatch.setattr(bundled_models.sys, "platform", "win32")
    monkeypatch.setattr(bundled_models.sys, "prefix", str(prefix))
    monkeypatch.setattr(bundled_models, "__file__", str(installed / "src/search/bundled_models.py"))
    assert bundled_models.bundled_model_roots() == (prefix.parent / "models" / "bge-small-en-v1.5",)
    # The Linux layout inside a Windows runtime isn't the installed engine.
    major, minor = bundled_models.sys.version_info[:2]
    linux = prefix / "lib" / f"python{major}.{minor}" / "site-packages"
    monkeypatch.setattr(bundled_models, "__file__", str(linux / "src/search/bundled_models.py"))
    assert bundled_models.bundled_model_roots() == ()
