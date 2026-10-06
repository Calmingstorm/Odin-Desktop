"""Build-time-only, digest-pinned D14 FastEmbed model staging.

No Hugging Face cache format or client is needed. Only enumerated immutable
revision URLs are fetched, at build time, and every byte is checked before
entering the bundle. Runtime model selection is in src.search.bundled_models.
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
import tomllib
import urllib.request
from pathlib import Path

MODEL = "BAAI/bge-small-en-v1.5"
FASTEMBED_VERSION = "0.8.1"
UV_LOCK = Path(__file__).resolve().parents[3] / "uv.lock"
REPOSITORY = "Qdrant/bge-small-en-v1.5-onnx-Q"
REVISION = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
MODEL_ROOT = "models/bge-small-en-v1.5"
SOURCE = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}"
UPSTREAM_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
LICENSE_SOURCE = (
    "https://raw.githubusercontent.com/FlagOpen/FlagEmbedding/"
    "c086741f5e117b7b8ce1745ea00b6c262f281a01/LICENSE"
)
UPSTREAM_CARD_SOURCE = (
    "https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/"
    f"{UPSTREAM_REVISION}/README.md"
)
# name: (SHA-256, exact size, provenance URL). The ONNX digest is also the
# repository's Git LFS object identity. Small-file digests pin resolved bytes.
ASSETS = {
    "README.md": ("01e220eed6921254f7e086bb3506d1c03f019f5f747bb9ac2f6ec5ce541edc12", 900, f"{SOURCE}/README.md"),
    "config.json": ("13582bcf2effc85b7bf3d3f5532e686bc1c9ce86bb009d10f0ec33cbe92299dd", 706, f"{SOURCE}/config.json"),
    "model_optimized.onnx": ("51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431", 66465124, f"{SOURCE}/model_optimized.onnx"),
    "ort_config.json": ("99881c45e073696289224931dd48694398bc6bcd1fe7cb7018bca1e0cc00e1fc", 1272, f"{SOURCE}/ort_config.json"),
    "special_tokens_map.json": ("5d5b662e421ea9fac075174bb0688ee0d9431699900b90662acd44b2a350503a", 695, f"{SOURCE}/special_tokens_map.json"),
    "tokenizer.json": ("d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66", 711396, f"{SOURCE}/tokenizer.json"),
    "tokenizer_config.json": ("0b29c7bfc889e53b36d9dd3e686dd4300f6525110eaa98c76a5dafceb2029f53", 1242, f"{SOURCE}/tokenizer_config.json"),
    "vocab.txt": ("07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3", 231508, f"{SOURCE}/vocab.txt"),
    "LICENSE": ("587a673933425dbc36ec61268d3b954051b2d3ef3c9b322ede357976055ffdd5", 1065, LICENSE_SOURCE),
    "UPSTREAM-MODEL-CARD.md": ("ddb964361a55c6e5dfca6361615854b260c9c960205d04c7520151aaa1d75837", 94783, UPSTREAM_CARD_SOURCE),
}


def _verify(path: Path, digest: str, size: int) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"model asset must be a regular file: {path}")
    if path.stat().st_size != size:
        raise ValueError(f"model asset size mismatch: {path}")
    with path.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual != digest:
        raise ValueError(f"model asset SHA-256 mismatch: {path}")


def _fetch(path: Path, digest: str, size: int, url: str) -> None:
    if path.exists() or path.is_symlink():
        _verify(path, digest, size)
        return
    # A failed/truncated download never becomes a reusable cache entry.
    with tempfile.TemporaryDirectory(prefix="model-fetch-", dir=path.parent) as temp:
        pending = Path(temp) / "asset"
        request = urllib.request.Request(url, headers={"User-Agent": "Odin-Desktop-P4.1"})
        with urllib.request.urlopen(request, timeout=120) as response, pending.open("wb") as output:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > size:
                    raise ValueError(f"model asset download exceeds pinned size: {url}")
                output.write(chunk)
        _verify(pending, digest, size)
        pending.replace(path)


def stage_models(bundle_root: Path, cache_dir: Path) -> dict:
    """Stage the exact FastEmbed 0.8.1 model and return relative-path inventory.

    bundle_root is resources/runtime, matching the other packaging lanes.
    Valid cached inputs make repeat builds offline. Corrupt inputs are rejected,
    never silently repaired or included. Existing destinations must be identical
    and closed over this inventory; this does not delete caller-owned resources.
    """
    packages = tomllib.loads(UV_LOCK.read_text())["package"]
    fastembed = next(item for item in packages if item["name"] == "fastembed")
    if fastembed["version"] != FASTEMBED_VERSION:
        raise ValueError("model pins require the audited FastEmbed version in uv.lock")
    bundle_root = Path(bundle_root).resolve()
    cache = Path(cache_dir).resolve() / "models" / "bge-small-en-v1.5"
    cache.mkdir(parents=True, exist_ok=True)
    destination = bundle_root / MODEL_ROOT
    destination.parent.mkdir(parents=True, exist_ok=True)
    for name, (digest, size, url) in ASSETS.items():
        _fetch(cache / name, digest, size, url)
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError("model destination must be a regular directory")
        if {p.name for p in destination.iterdir()} != set(ASSETS):
            raise ValueError("existing model destination inventory mismatch")
        for name, (digest, size, _) in ASSETS.items():
            _verify(destination / name, digest, size)
    else:
        with tempfile.TemporaryDirectory(prefix="models-stage-", dir=destination.parent) as temp:
            pending = Path(temp) / destination.name
            pending.mkdir()
            for name, (digest, size, _) in ASSETS.items():
                shutil.copyfile(cache / name, pending / name)
                (pending / name).chmod(0o644)
                _verify(pending / name, digest, size)
            pending.rename(destination)
    files = [
        {"path": f"{MODEL_ROOT}/{name}", "sha256": digest, "size": size, "source": url}
        for name, (digest, size, url) in ASSETS.items()
    ]
    return {
        "id": "semantic-search-model", "model": MODEL,
        "repository": REPOSITORY, "revision": REVISION, "source": SOURCE,
        "upstream_revision": UPSTREAM_REVISION,
        "license": "MIT", "model_root": MODEL_ROOT, "files": files,
        "licenses": [{"path": f"{MODEL_ROOT}/LICENSE", "spdx": "MIT",
                      "source": LICENSE_SOURCE, "sha256": ASSETS["LICENSE"][0]}],
        "dimensions": 384, "format": "quantized ONNX", "fastembed_version": FASTEMBED_VERSION,
        "offline_first_use": True,
        "phase2_limitation": "LocalEmbedder is bundled and offline-capable; the step-one desktop core graph does not expose semantic knowledge/search services yet.",
    }
