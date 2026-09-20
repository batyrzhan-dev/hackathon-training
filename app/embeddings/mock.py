"""Synthetic vectors for tests/local wiring; not evidence of semantic quality."""
import hashlib
import re

from .base import validate_vectors


class MockEmbeddingProvider:
    name = "mock"
    model = "mock-hash-v1"

    def __init__(self, vectors=None):
        self.vectors = vectors
        self.calls = []

    def embed(self, texts):
        self.calls.append(tuple(texts))
        if self.vectors is not None:
            return validate_vectors([self.vectors[t] for t in texts], len(texts))
        result = []
        for text in texts:
            vector = [0.0] * 64
            for token in re.findall(r"\w+", text.lower()):
                index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:2], "big") % len(vector)
                vector[index] += 1
            if not any(vector):
                vector[0] = 1
            result.append(vector)
        return validate_vectors(result, len(texts))
