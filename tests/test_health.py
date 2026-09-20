from fastapi.testclient import TestClient

from app.main import app


def test_health_does_not_require_ai_or_credentials(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    def forbidden():
        raise AssertionError("Health check must not call an AI provider")

    monkeypatch.setattr("app.main.get_provider", forbidden)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
