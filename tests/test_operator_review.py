import re

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import mock_ai
from app.main import app
from app.models import Feature, OperatorCard, OperatorChange
from app.operator_review import ReviewStore, apply_override
from app.scoring import calculate_priority

SOURCE = "Фонарь искрит второй день. Возможно нет воды."


def make_card():
    analysis = mock_ai.analyze(SOURCE)
    analysis.critical_outage = Feature(value="unknown", evidence=["Возможно нет воды."])
    return OperatorCard(text=SOURCE, analysis=analysis, scoring=calculate_priority(analysis, 0),
                        analysis_status="needs_review")


@pytest.mark.parametrize("field", ["safety_risk", "critical_outage", "persists_multiple_days"])
def test_any_unknown_blocks_final_priority(field):
    card = apply_override(make_card(), OperatorChange(field="critical_outage", value="no"))
    changed = apply_override(card, OperatorChange(field=field, value="unknown"))
    assert changed.scoring.score is None and changed.scoring.priority is None
    assert changed.scoring.unresolved == [field]
    assert changed.effective_values[field] == "unknown"


def test_unknown_to_no_produces_50_medium():
    result = apply_override(make_card(), OperatorChange(field="critical_outage", value="no"))
    assert result.scoring.score == result.scoring.subtotal == 50
    assert result.scoring.priority == "MEDIUM"
    assert {r.rule_id:r.points for r in result.scoring.reasons} == {"safety_risk":40,"persists_multiple_days":10}
    assert not result.scoring.unresolved


@pytest.mark.parametrize("field,points", [("safety_risk",40),("critical_outage",30),("persists_multiple_days",10)])
def test_unknown_to_yes_adds_exact_rule_points(field, points):
    card = make_card()
    for other in card.effective_values:
        card = apply_override(card, OperatorChange(field=other, value="no"))
    card = apply_override(card, OperatorChange(field=field, value="unknown"))
    assert card.scoring.priority is None
    result = apply_override(card, OperatorChange(field=field, value="yes"))
    assert result.scoring.score == points
    assert result.scoring.reasons[0].points == points
    assert "operator override" in result.scoring.reasons[0].evidence_or_ids[0]


def test_original_ai_and_evidence_unchanged_after_override():
    card = make_card()
    original = card.analysis.model_dump()
    result = apply_override(card, OperatorChange(field="critical_outage", value="yes"))
    assert result.analysis.model_dump() == original == card.analysis.model_dump()
    assert result.analysis.critical_outage.value == "unknown"
    assert result.analysis.critical_outage.evidence == ["Возможно нет воды."]
    assert result.operator_overrides == {"critical_outage":"yes"}
    assert result.effective_values["critical_outage"] == "yes"
    assert card.operator_overrides == {}


def test_multiple_edits_recalculate_without_accumulation():
    card = make_card()
    original = card.analysis.model_dump()
    edits = [("critical_outage","no",50,"MEDIUM"),
             ("critical_outage","yes",80,"HIGH"),
             ("safety_risk","no",40,"MEDIUM"),
             ("persists_multiple_days","no",30,"MEDIUM"),
             ("critical_outage","unknown",None,None),
             ("safety_risk","yes",None,None),
             ("critical_outage","no",40,"MEDIUM"),
             ("persists_multiple_days","yes",50,"MEDIUM")]
    for field, value, score, priority in edits:
        card = apply_override(card, OperatorChange(field=field,value=value))
        assert (card.scoring.score,card.scoring.priority) == (score,priority)
        assert card.analysis.model_dump() == original
    assert card.operator_overrides["persists_multiple_days"] == "yes"
    assert card.analysis.persists_multiple_days.value == "yes"


def test_operator_yes_without_ai_evidence_is_not_a_fake_quote():
    card = make_card()
    card.analysis.critical_outage = Feature(value="unknown", evidence=[])
    result = apply_override(card, OperatorChange(field="critical_outage",value="yes"))
    assert result.analysis.critical_outage.evidence == []
    assert result.scoring.score == 80
    reason = next(r for r in result.scoring.reasons if r.rule_id == "critical_outage")
    assert reason.evidence_or_ids == ["Решение оператора (operator override): yes"]


def test_api_preserves_ai_and_does_not_call_provider_on_recalculation(monkeypatch):
    card = make_card()
    monkeypatch.setattr(mock_ai,"analyze",lambda _:card.analysis)
    with TestClient(app) as client:
        original = client.post("/api/analyze",json={"text":SOURCE}).json()
        assert original["effective_values"] == {"safety_risk":"yes","critical_outage":"unknown","persists_multiple_days":"yes"}
        assert original["operator_overrides"] == {}
        def forbidden(*args,**kwargs):
            raise AssertionError("Overrides must never call AI")
        monkeypatch.setattr("app.main.get_provider",forbidden)
        url = f"/api/cards/{original['card_id']}/features"
        for value,score in [("no",50),("yes",80),("unknown",None),("no",50)]:
            response = client.patch(url,json={"field":"critical_outage","value":value})
            assert response.status_code == 200
            result = response.json()
            assert result["scoring"]["score"] == score
            assert result["analysis"] == original["analysis"]
            assert result["operator_overrides"] == {"critical_outage":value}


def test_html_defaults_duration_mapping_and_override_marker():
    with TestClient(app) as client:
        result = client.post("/analyze",data={"text":SOURCE})
        assert result.status_code == 200
        for field,value in [("safety_risk","yes"),("critical_outage","unknown"),("persists_multiple_days","yes")]:
            select = re.search(f'<select id="override-{field}".*?</select>',result.text,re.S).group()
            assert f'value="{value}" selected' in select
        for label in ["Нет данных","Менее двух дней","Два дня и более"]:
            assert label in result.text
        url = re.search(r'action="(/cards/[^/]+/features)"',result.text).group(1)
        changed = client.post(url,data={"field":"critical_outage","value":"no","text":SOURCE})
        assert changed.status_code == 200
        assert "operator override · no" in changed.text
        assert "Исходное AI-значение: unknown" in changed.text
        assert "MEDIUM</span>" in changed.text
        assert "нет воды" in changed.text
        assert client.get('/static/operator-review.js').status_code == 200


@pytest.mark.parametrize("payload", [{"field":"priority","value":"HIGH"},
    {"field":"critical_outage","value":False}, {"field":"critical_outage","value":"maybe"},
    {"field":"critical_outage","value":"no","score":100},
    {"field":"critical_outage","value":"no","analysis":{}}])
def test_api_rejects_invalid_or_tampered_changes(payload):
    with TestClient(app) as client:
        assert client.patch('/api/cards/any/features',json=payload).status_code == 422


def test_missing_card_keeps_submitted_text_in_form():
    with TestClient(app) as client:
        response = client.post('/cards/missing/features',data={"field":"critical_outage","value":"no","text":SOURCE})
        assert response.status_code == 404
        assert SOURCE in response.text and "устарела" in response.text
        assert client.patch('/api/cards/missing/features',json={"field":"critical_outage","value":"no"}).status_code == 404


def test_store_snapshots_do_not_mutate_saved_original():
    store = ReviewStore()
    card = store.add(make_card())
    card.analysis.safety_risk.evidence.clear()
    card.operator_overrides["safety_risk"] = "no"
    saved = store.update(card.card_id,OperatorChange(field="critical_outage",value="no"))
    assert saved.analysis.safety_risk.evidence == ["искрит"]
    assert saved.effective_values["safety_risk"] == "yes"


def test_store_is_bounded_and_expires():
    store = ReviewStore(capacity=1)
    first = store.add(make_card())
    store.add(make_card())
    with pytest.raises(KeyError):
        store.update(first.card_id,OperatorChange(field="critical_outage",value="no"))
    expired = ReviewStore(ttl_seconds=0)
    card = expired.add(make_card())
    with pytest.raises(KeyError):
        expired.update(card.card_id,OperatorChange(field="critical_outage",value="no"))
