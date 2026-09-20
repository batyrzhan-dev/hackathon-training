import re

import pytest
from fastapi.testclient import TestClient

from app.duplicates import HISTORY, find_candidates, normalize_location, normalize_text, text_similarity
from app.examples import EXAMPLES
from app.main import app
from app.mock_ai import analyze
from app.models import Category, DuplicateChange
from app.operator_review import ReviewStore
from app.scoring import calculate_priority

SOURCE = EXAMPLES[0]["text"]


def test_demo_finds_four_unique_pending_candidates_with_reasons():
    candidates = find_candidates(SOURCE, analyze(SOURCE))
    assert {c.id for c in candidates} == {"R-001", "R-002", "R-003", "R-004"}
    assert len(candidates) == 4
    for c in candidates:
        assert c.status == "pending"
        assert c.text and c.location and c.category == Category.LIGHTING
        assert len(c.reasons) == 3
        assert 0 <= c.similarity <= 100 and 0 <= c.text_similarity <= 100
    assert candidates == sorted(candidates, key=lambda c: (-c.similarity, c.id))


@pytest.mark.parametrize("report_id", ["R-005", "R-006", "R-007", "R-008", "R-011", "R-012"])
def test_negative_history_does_not_match(report_id):
    history = tuple(row for row in HISTORY if row.id == report_id)
    assert not find_candidates(SOURCE, analyze(SOURCE), history)


@pytest.mark.parametrize("location", ["Учебная 12", "На улице Учебной, 12", "УЛ. УЧЕБНАЯ, Д. 12",
    "улица  Учебная, дом 12", "улица Учебная, 12, у подъезда", "Учебную 12"])
def test_location_normalization(location):
    assert normalize_location(location) == normalize_location("Учебная 12")


@pytest.mark.parametrize("location", ["Учебная 12а", "Учебная 12/1", "Учебная 12 корпус 2", "Учебная 12 стр. 1", "Учебная 120", "Примерная 12", None, "во дворе"])
def test_different_or_missing_address_not_equal(location):
    assert normalize_location(location) != normalize_location("Учебная 12")


def test_punctuation_case_and_whitespace():
    assert normalize_text("  ФОНАРЬ,   у подъезда! ") == "фонарь у подъезда"
    assert text_similarity("", "фонарь") == 0
    assert text_similarity("фонарь", "ФОНАРЬ!") == 100


@pytest.mark.parametrize("location", [None, "во дворе", "Учебная"])
def test_unknown_address_never_proposes_duplicates(location):
    analysis = analyze(SOURCE)
    analysis.location = location
    assert find_candidates(SOURCE, analysis) == []


def test_unknown_category_and_empty_history():
    analysis = analyze(SOURCE)
    assert find_candidates(SOURCE, analysis, ()) == []
    analysis.category = Category.OTHER
    assert find_candidates(SOURCE, analysis) == []


def test_repeated_historical_id_counted_once():
    assert len(find_candidates(SOURCE, analyze(SOURCE), (HISTORY[0], HISTORY[0]))) == 1


@pytest.mark.parametrize("count,score", [(2,50),(3,70),(4,70)])
def test_two_three_four_candidates_scoring(count, score):
    candidates = find_candidates(SOURCE, analyze(SOURCE), HISTORY[:count])
    result = calculate_priority(analyze(SOURCE), len(candidates))
    assert result.score == score
    assert sum(r.points for r in result.reasons if r.rule_id == "probable_duplicates") == (20 if count >= 3 else 0)


def test_review_recalculates_ids_and_preserves_ai_and_overrides(monkeypatch):
    with TestClient(app) as client:
        original = client.post("/api/analyze", json={"text":SOURCE}).json()
        assert (original["scoring"]["score"], original["scoring"]["priority"]) == (70,"HIGH")
        def forbidden(*args, **kwargs):
            raise AssertionError("Review must not call AI")
        monkeypatch.setattr("app.main.get_provider", forbidden)
        card_id = original["card_id"]
        def change(report_id, status):
            response = client.patch(f"/api/cards/{card_id}/duplicates/{report_id}", json={"status":status})
            assert response.status_code == 200
            result = response.json()
            assert result["analysis"] == original["analysis"]
            assert len(result["candidates"]) == 4
            return result
        result = change("R-001", "confirmed")
        assert result["probable_duplicate_count"] == 4
        assert result["scoring"]["score"] == 70
        result = change("R-001", "rejected")
        assert result["probable_duplicate_count"] == 3 and result["scoring"]["score"] == 70
        ids = next(r["evidence_or_ids"] for r in result["scoring"]["reasons"] if r["rule_id"] == "probable_duplicates")
        assert ids == ["R-002", "R-003", "R-004"]
        result = change("R-002", "rejected")
        assert result["probable_duplicate_count"] == 2
        assert (result["scoring"]["score"], result["scoring"]["priority"]) == (50,"MEDIUM")
        assert all(r["rule_id"] != "probable_duplicates" for r in result["scoring"]["reasons"])
        assert change("R-002", "rejected")["scoring"]["score"] == 50
        # Unknown stays unknown even with four candidates; override survives duplicate edits.
        features_url = f"/api/cards/{card_id}/features"
        unknown = client.patch(features_url,json={"field":"critical_outage","value":"unknown"}).json()
        assert unknown["scoring"]["priority"] is None
        change("R-001", "confirmed")
        result = change("R-002", "confirmed")
        assert result["scoring"]["priority"] is None and result["scoring"]["subtotal"] == 70
        assert result["operator_overrides"] == {"critical_outage":"unknown"}
        final = client.patch(features_url,json={"field":"critical_outage","value":"no"}).json()
        assert final["scoring"]["score"] == 70
        assert final["analysis"] == original["analysis"]


def test_html_review_flow_and_explanations():
    with TestClient(app) as client:
        page = client.post("/analyze", data={"text":SOURCE})
        assert page.status_code == 200
        assert "Найдено вероятных дублей: 4" in page.text
        assert "не вероятность" in page.text and "Подтвердить дубликат" in page.text
        card_id = re.search(r'/cards/([^/]+)/duplicates/',page.text).group(1)
        for report_id in ("R-001", "R-002"):
            page = client.post(f"/cards/{card_id}/duplicates/{report_id}",data={"status":"rejected"})
            assert page.status_code == 200
        assert "Найдено вероятных дублей: 2" in page.text
        assert "MEDIUM</span>" in page.text
        assert "+0 · Менее трёх вероятных дублей" in page.text
        assert "Исключён из подсчёта" in page.text
        assert SOURCE in page.text


@pytest.mark.parametrize("payload", [{"status":"pending"},{"status":"invalid"},{"status":"confirmed","score":100}])
def test_invalid_review_payload(payload):
    with TestClient(app) as client:
        assert client.patch('/api/cards/missing/duplicates/R-001',json=payload).status_code == 422


def test_missing_card_candidate_and_expiry():
    with TestClient(app) as client:
        result = client.post('/cards/missing/duplicates/R-001',data={"status":"rejected","text":SOURCE})
        assert result.status_code == 404 and SOURCE in result.text
        original = client.post('/api/analyze',json={"text":SOURCE}).json()
        assert client.patch(f"/api/cards/{original['card_id']}/duplicates/forged",json={"status":"confirmed"}).status_code == 404
    from app.models import OperatorCard
    store = ReviewStore(ttl_seconds=0)
    card = store.add(OperatorCard.model_validate({k:v for k,v in original.items() if k != "effective_values"}))
    with pytest.raises(KeyError):
        store.update_duplicate(card.card_id,"R-001",DuplicateChange(status="rejected"))


def test_card_decisions_are_isolated_and_history_immutable():
    before = [r.model_dump() for r in HISTORY]
    with TestClient(app) as client:
        first = client.post('/api/analyze',json={"text":SOURCE}).json()
        second = client.post('/api/analyze',json={"text":SOURCE}).json()
        client.patch(f"/api/cards/{first['card_id']}/duplicates/R-001",json={"status":"rejected"})
        result = client.patch(f"/api/cards/{second['card_id']}/duplicates/R-002",json={"status":"confirmed"}).json()
        assert result["probable_duplicate_count"] == 4
        assert next(c for c in result["candidates"] if c["id"] == "R-001")["status"] == "pending"
    assert [r.model_dump() for r in HISTORY] == before


@pytest.mark.parametrize("text", ["На улице Учебной, 12, фонарь неисправен.",
                                  "На улице Учебной, 12, неисправный фонарь у подъезда."])
def test_fault_word_is_not_mistaken_for_repaired(text):
    assert len(find_candidates(text, analyze(text))) >= 3


def test_house_number_symbol():
    assert normalize_location("ул. Учебная, д. №12") == normalize_location("Учебная 12")


@pytest.mark.parametrize("text", ["На улице Учебной, 12, фонарь не работал, теперь все работает.",
                                  "На улице Учебной, 12, фонарь исправен, раньше было темно."])
def test_resolved_complaint_does_not_receive_duplicate_bonus(text):
    assert find_candidates(text, analyze(text)) == []
