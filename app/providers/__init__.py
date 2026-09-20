"""Selection is confined to this factory; main depends only on the interface."""
import os

from .base import AnalysisError, AnalysisProvider
from .mock import MockProvider
from .openrouter import OpenRouterProvider


def selected_provider_name() -> str:
    name = os.environ.get("AI_PROVIDER", "mock").strip().lower()
    return name if name in {"mock", "openrouter"} else "unconfigured"


def get_provider() -> AnalysisProvider:
    name = selected_provider_name()
    if name == "mock":
        return MockProvider()
    if name == "openrouter":
        return OpenRouterProvider(
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            model=os.environ.get("OPENROUTER_MODEL", ""),
        )
    raise AnalysisError("configuration")
