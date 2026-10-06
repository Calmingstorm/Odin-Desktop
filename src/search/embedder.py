from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from ..odin_log import get_logger
from .bundled_models import bundled_model_roots

if TYPE_CHECKING:
    from fastembed import TextEmbedding

log = get_logger("search.embedder")

# bge-small context is ~512 tokens; truncate input to ~32K chars to be safe
MAX_INPUT_CHARS = 32_000


class LocalEmbedder:
    """CPU embeddings from explicitly supplied bundled model directories only.

    Each root is a complete fastembed model directory, not an ambient cache.
    Missing or unusable bundles degrade embeddings to None; loading never
    downloads a model or falls back to a user/system cache.
    """

    MODEL = "BAAI/bge-small-en-v1.5"
    DIMENSIONS = 384

    def __init__(self, *, model_roots: Iterable[str | Path] | None = None) -> None:
        roots = tuple(Path(root) for root in (
            bundled_model_roots() if model_roots is None else model_roots
        ))
        if any(not root.is_absolute() for root in roots):
            raise ValueError("bundled model roots must be absolute paths")
        self._model_roots = roots
        self._model: TextEmbedding | None = None
        self._model_lock = threading.Lock()
        self._unavailable_reason: str | None = (
            None if roots else "no bundled embedding model roots configured"
        )

    @property
    def unavailable_reason(self) -> str | None:
        """Why embeddings are unavailable, or None before/since successful load."""
        return self._unavailable_reason

    def _ensure_model(self):
        # Loading (including import) runs in the inference worker.
        # A thread lock keeps first callers single-flight even if a waiting
        # coroutine is cancelled while the worker is still initializing.
        with self._model_lock:
            if self._model is None:
                failures = []
                for root in self._model_roots:
                    try:
                        model_root = root.resolve(strict=True)
                        if not model_root.is_dir():
                            raise ValueError("bundled model root is not a directory")
                        from fastembed import TextEmbedding

                        self._model = TextEmbedding(
                            self.MODEL,
                            specific_model_path=str(model_root),
                            cache_dir=str(model_root),
                            local_files_only=True,
                            cuda=False,
                        )
                    except Exception as exc:
                        failures.append(f"{root}: {exc}")
                        continue
                    self._unavailable_reason = None
                    return
                self._unavailable_reason = (
                    "bundled embedding model unavailable: " + "; ".join(failures)
                    if failures else "no bundled embedding model roots configured"
                )
                raise RuntimeError(self._unavailable_reason)

    async def embed(self, text: str) -> list[float] | None:
        """Embed text. Returns 384-dim float list or None on failure."""
        try:
            text = text[:MAX_INPUT_CHARS]
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, partial(self._embed_sync, text)
            )
            return result
        except Exception as e:
            log.warning("Embed failed: %s", e)
            return None

    def _embed_sync(self, text: str) -> list[float]:
        self._ensure_model()
        vectors = list(self._model.embed([text]))  # type: ignore[union-attr]
        return vectors[0].tolist()
