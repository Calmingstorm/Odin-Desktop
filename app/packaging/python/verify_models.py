"""Native, offline first-use proof run by the bundled interpreter with -I.

Invoke inside an isolated PID + network namespace, from outside the checkout,
with an empty HOME and HF_HOME. This script imports the installed engine only;
it is validation tooling, never a bundled engine asset.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import socket
import sys
from pathlib import Path


def main() -> None:
    prefix = Path(sys.prefix).resolve()
    assert prefix.name == "python" and prefix.parent.name == "runtime", prefix
    import src.search.embedder as engine
    from src.search.bundled_models import bundled_model_roots

    assert Path(engine.__file__).resolve().is_relative_to(prefix), engine.__file__
    roots = bundled_model_roots()
    assert len(roots) == 1 and roots[0].is_dir(), roots
    root = roots[0]

    def forbidden(*args, **kwargs):
        raise AssertionError("offline embedding attempted network/download")

    socket.socket.connect = forbidden
    socket.socket.connect_ex = forbidden
    socket.create_connection = forbidden
    import fastembed.common.model_management as management
    import onnxruntime
    import numpy
    import requests

    for module in (management, onnxruntime, numpy):
        assert Path(module.__file__).resolve().is_relative_to(prefix), module.__file__

    management.snapshot_download = forbidden
    management.model_info = forbidden
    management.list_repo_tree = forbidden
    requests.sessions.Session.request = forbidden

    def snapshot():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}

    before = snapshot()

    async def verify():
        embedder = engine.LocalEmbedder()
        first = await embedder.embed("The database transaction committed successfully.")
        second = await embedder.embed("The database transaction committed successfully.")
        other = await embedder.embed("A bright blue painting hangs above the kitchen table.")
        assert first is not None, embedder.unavailable_reason
        assert second is not None and other is not None
        assert len(first) == len(second) == len(other) == 384
        assert all(math.isfinite(value) for vector in (first, second, other) for value in vector)
        norm = math.sqrt(sum(value * value for value in first))
        assert abs(norm - 1.0) < 0.001, norm
        assert first == second, "inference was not repeatable"
        cosine = sum(a * b for a, b in zip(first, other))
        assert cosine < 0.95, cosine
        native = embedder._model.model
        assert native.model.get_providers() == ["CPUExecutionProvider"]
        return {"dimensions": len(first), "norm": norm, "unrelated_cosine": cosine,
                "providers": native.model.get_providers()}

    result = asyncio.run(verify())
    assert snapshot() == before, "inference wrote to immutable model resources"
    print(json.dumps({"status": "pass", "model": engine.LocalEmbedder.MODEL,
                      "model_root": str(root), "python": sys.executable,
                      "engine": engine.__file__, "network_download_attempts": 0,
                      "resource_files_unchanged": True, **result}, sort_keys=True))


if __name__ == "__main__":
    main()
