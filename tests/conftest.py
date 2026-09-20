import httpx
import pytest


@pytest.fixture(autouse=True)
def isolated_ai_environment(monkeypatch):
    """Old mock tests remain deterministic even on a real-key developer machine."""
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)

    def block_network(*args, **kwargs):
        raise AssertionError("Real HTTP is forbidden in pytest; use httpx.MockTransport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", block_network)
