import pytest
from fastapi.testclient import TestClient

from app import mock_ai
from app.examples import EXAMPLES
from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("example,score,priority", [("lighting",70,"HIGH"),("water",40,"MEDIUM"),
                                                 ("urgent",80,"HIGH"),("waste",0,"LOW"),("negation",20,"LOW")])
def test_end_to_end(example, score, priority):
    text = next(item["text"] for item in EXAMPLES if item["id"] == example)
    response = client.post("/api/analyze", json={"text": text})
    assert response.status_code == 200
    result = response.json()
    assert result["scoring"]["score"] == score
    assert result["scoring"]["priority"] == priority
    assert result["duplicate_detection_status"] == "complete"
    assert result["probable_duplicate_count"] == len(result["candidates"])
    assert result["duplicate_count_for_scoring"] == result["probable_duplicate_count"]
    assert "score" not in result["analysis"] and "priority" not in result["analysis"]
    for field in ("safety_risk", "critical_outage", "persists_multiple_days"):
        assert all(quote in text for quote in result["analysis"][field]["evidence"])
    html = client.post("/analyze", data={"text": text})
    assert html.status_code == 200
    assert 'OPERATOR CARD' in html.text and priority in html.text
    assert 'Похожие обращения' in html.text


@pytest.mark.parametrize("text", ["", "   ", "\n\t", "a" * 5001])
def test_invalid_input_rejected_before_analysis(text, monkeypatch):
    def fail(_):
        raise AssertionError("Analyzer must not run")
    monkeypatch.setattr(mock_ai, "analyze", fail)
    assert client.post("/api/analyze", json={"text": text}).status_code == 422
    response = client.post("/analyze", data={"text": text})
    assert response.status_code == 422
    assert "Введите обращение" in response.text


def test_missing_form_field():
    assert client.post("/analyze", data={}).status_code == 422


def test_trim_and_max_length():
    result = client.post("/api/analyze", json={"text": "  " + "а" * 5000 + "  "})
    assert result.status_code == 200
    assert len(result.json()["text"]) == 5000


@pytest.mark.parametrize("text", ["Возможно провод искрит.", "Возможно, провод искрит."])
def test_unknown_input_not_forced_low(text):
    response = client.post("/api/analyze", json={"text": text})
    result = response.json()
    assert result["analysis_status"] == "needs_review"
    assert result["scoring"]["priority"] is None


def test_score_cannot_be_supplied_by_client():
    assert client.post("/api/analyze", json={"text": "Мусор", "score": 100}).status_code == 422


def test_html_escapes_input():
    response = client.post("/analyze", data={"text": "<script>alert(1)</script> Мусор"})
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_invalid_analysis_is_visible_error(monkeypatch):
    analysis = mock_ai.analyze("Провод искрит.")
    monkeypatch.setattr(mock_ai, "analyze", lambda _: analysis)
    response = client.post("/analyze", data={"text": "Мусор"})
    assert response.status_code == 502
    assert "Не удалось проверить" in response.text
    assert "Мусор" in response.text
    assert client.post("/api/analyze", json={"text": "Мусор"}).status_code == 502


def test_home_demo_and_static():
    assert client.get("/").status_code == 200
    assert "второй день" in client.get("/?example=lighting").text
    assert client.get("/static/style.css").status_code == 200
