"""Optional local-only sentence embeddings for analytics search."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence


class EmbeddingError(RuntimeError):
    """A local embedding model is unavailable or returned invalid vectors."""


class SentenceTransformerEmbeddingProvider:
    """Load an explicitly configured local model on first use; never download it."""

    def __init__(self, model_path: str | Path, *, model_id: str, version: str,
                 model: Any | None = None):
        path = Path(model_path).expanduser()
        if not path.is_dir():
            raise EmbeddingError("The configured local embedding model directory is unavailable.")
        if not model_id.strip() or not version.strip():
            raise ValueError("model_id and version must not be blank")
        self.model_path = path
        self.model_id = model_id
        self.version = version
        self._model = model

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(str(self.model_path), local_files_only=True)
            except Exception:
                raise EmbeddingError("The configured local embedding model could not be loaded.") from None
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if isinstance(texts, (str, bytes)) or not texts:
            raise ValueError("texts must be a non-empty sequence of strings")
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("texts must contain non-blank strings")
        try:
            raw = self._load().encode(
                list(texts), convert_to_numpy=True, normalize_embeddings=True,
                show_progress_bar=False,
            )
            values = raw.tolist() if hasattr(raw, "tolist") else raw
            vectors = [[float(value) for value in row] for row in values]
        except EmbeddingError:
            raise
        except Exception:
            raise EmbeddingError("The local embedding model failed to encode text.") from None
        if len(vectors) != len(texts) or not vectors:
            raise EmbeddingError("The local embedding model returned the wrong number of vectors.")
        dimension = len(vectors[0])
        if dimension == 0 or any(
            len(vector) != dimension or not any(vector)
            or any(not math.isfinite(value) for value in vector)
            for vector in vectors
        ):
            raise EmbeddingError("The local embedding model returned invalid vectors.")
        return vectors
