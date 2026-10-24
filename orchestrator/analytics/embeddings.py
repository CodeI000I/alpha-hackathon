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
        self.version = f"{version}:token-windows-v1"
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
            model = self._load()
            max_length = getattr(model, 'max_seq_length', None)
            tokenizer = getattr(model, 'tokenizer', None)
            if max_length is None:
                if tokenizer is not None:
                    raise EmbeddingError('The configured model does not expose a maximum input length.')
                windows = [[(text, 1)] for text in texts]
            else:
                if tokenizer is None:
                    raise EmbeddingError('The configured model cannot expose its tokenizer for safe windowing.')
                windows = [self._windows(text, tokenizer, max_length) for text in texts]
            flat_texts = [window for group in windows for window, _ in group]
            raw = model.encode(
                flat_texts, convert_to_numpy=True, normalize_embeddings=True,
                show_progress_bar=False,
            )
            values = raw.tolist() if hasattr(raw, "tolist") else raw
            encoded = [[float(value) for value in row] for row in values]
        except EmbeddingError:
            raise
        except Exception:
            raise EmbeddingError("The local embedding model failed to encode text.") from None
        if len(encoded) != len(flat_texts) or not encoded:
            raise EmbeddingError("The local embedding model returned the wrong number of vectors.")
        dimension = len(encoded[0])
        if dimension == 0 or any(
            len(vector) != dimension or not any(vector)
            or any(not math.isfinite(value) for value in vector)
            for vector in encoded
        ):
            raise EmbeddingError("The local embedding model returned invalid vectors.")
        vectors = []
        offset = 0
        for group in windows:
            if len(group) == 1:
                vectors.append(encoded[offset])
                offset += 1
                continue
            weighted = [0.0] * dimension
            total_weight = 0
            for _, weight in group:
                for index, value in enumerate(encoded[offset]):
                    weighted[index] += value * weight
                offset += 1
                total_weight += weight
            vector = [value / total_weight for value in weighted]
            magnitude = math.sqrt(sum(value * value for value in vector))
            if not math.isfinite(magnitude) or magnitude == 0:
                raise EmbeddingError("The local embedding model returned invalid aggregate vectors.")
            vectors.append([value / magnitude for value in vector])
        return vectors

    @staticmethod
    def _windows(text: str, tokenizer: Any, max_length: int) -> list[tuple[str, int]]:
        try:
            tokens = SentenceTransformerEmbeddingProvider._token_ids(tokenizer, text)
            special_tokens = tokenizer.num_special_tokens_to_add(pair=False)
            capacity = max_length - special_tokens
            if capacity <= 0:
                raise ValueError('model sequence length leaves no room for text tokens')
            if len(tokens) <= capacity:
                return [(text, max(len(tokens), 1))]
            windows = []
            start = 0
            while start < len(tokens):
                end = min(start + capacity, len(tokens))
                while True:
                    decoded = tokenizer.decode(tokens[start:end], skip_special_tokens=True).strip()
                    if not decoded:
                        raise ValueError('tokenizer produced an empty text window')
                    decoded_tokens = SentenceTransformerEmbeddingProvider._token_ids(tokenizer, decoded)
                    if len(decoded_tokens) <= capacity:
                        windows.append((decoded, max(len(decoded_tokens), 1)))
                        start = end
                        break
                    if end - start <= 1:
                        raise ValueError('decoded window exceeds the model sequence length')
                    end -= 1
            return windows
        except Exception as exc:
            if isinstance(exc, EmbeddingError):
                raise
            raise EmbeddingError('The local embedding tokenizer could not create safe windows.') from None

    @staticmethod
    def _token_ids(tokenizer: Any, text: str) -> list[int]:
        if hasattr(tokenizer, 'tokenize') and hasattr(tokenizer, 'convert_tokens_to_ids'):
            return list(tokenizer.convert_tokens_to_ids(tokenizer.tokenize(text)))
        return list(tokenizer.encode(text, add_special_tokens=False))
