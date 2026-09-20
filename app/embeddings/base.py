"""Embedding contracts, safe errors and provider-independent vector validation."""
import math
from typing import Protocol

MAX_DIMENSIONS = 16384


class EmbeddingError(Exception):
    """Expose only a fixed code, never a provider body, input or credential."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class EmbeddingProvider(Protocol):
    name: str
    model: str

    def embed(self, texts: list[str]) -> list[tuple[float, ...]]: ...


def validate_vectors(vectors, count: int) -> list[tuple[float, ...]]:
    if not isinstance(vectors, (list, tuple)) or len(vectors) != count or not count:
        raise EmbeddingError("invalid_response")
    result = []
    dimension = None
    for vector in vectors:
        if not isinstance(vector, (list, tuple)) or not 1 <= len(vector) <= MAX_DIMENSIONS:
            raise EmbeddingError("invalid_response")
        if dimension is not None and len(vector) != dimension:
            raise EmbeddingError("invalid_response")
        dimension = len(vector)
        if any(type(x) not in (int, float) for x in vector):
            raise EmbeddingError("invalid_response")
        try:
            values = tuple(float(x) for x in vector)
            norm = math.hypot(*values)
        except (OverflowError, ValueError):
            raise EmbeddingError("invalid_response") from None
        if not all(math.isfinite(x) for x in values) or not math.isfinite(norm) or norm == 0:
            raise EmbeddingError("invalid_response")
        result.append(values)
    return result


def cosine_similarity(left, right) -> float:
    a, b = validate_vectors([left, right], 2)
    an, bn = math.hypot(*a), math.hypot(*b)
    return max(-1.0, min(1.0, math.fsum((x / an) * (y / bn) for x, y in zip(a, b))))
