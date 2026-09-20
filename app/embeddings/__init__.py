"""Embedding selection is independent of the existing analysis provider."""
import os

from .base import EmbeddingError, EmbeddingProvider
from .mock import MockEmbeddingProvider
from .openrouter import OpenRouterEmbeddingProvider

DEFAULT_EMBEDDING_MODEL = "nvidia/nemotron-3-embed-1b:free"


def get_embedding_provider() -> EmbeddingProvider | None:
    name = os.environ.get("EMBEDDING_PROVIDER", "disabled").strip().lower()
    if name == "disabled":
        return None
    if name == "mock":
        return MockEmbeddingProvider()
    if name == "openrouter":
        return OpenRouterEmbeddingProvider(
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            model=os.environ.get("OPENROUTER_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL))
    raise EmbeddingError("configuration")
