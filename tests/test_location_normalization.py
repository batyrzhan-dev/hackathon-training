"""Regression for actual AI locations; no network or embedding threshold changes."""
import pytest
from fastapi.testclient import TestClient

from app import mock_ai
from app.duplicates import find_candidates, normalize_location
from app.main import app
from app.models import Category

LOCATIONS = [
    "Учебная 12",
    "ул. Учебной, 12",
    "улица Учебная, дом 12",
    "дом 12 по улице Учебной",
    "возле дома 12 на Учебной",
    "у дома 12 на Учебной",
    "Учебной, 12",
]
TEXT = "Возле дома 12 на Учебной ночью темно, уличный светильник не работает."


@pytest.mark.parametrize("location", LOCATIONS)
def test_requested_constructions_share_canonical_location(location):
    assert normalize_location(location) == "учебная|12||"


@pytest.mark.parametrize("left,right", [
    ("Учебная 12", "Учебная 15"),
    ("возле дома 12 на Учебной", "у дома 15 на Учебной"),
    ("дом 12 по улице Учебной", "дом 12 по улице Примерной"),
    ("у дома 12а на Учебной", "Учебная 12"),
    ("возле дома 12/1 на Учебной", "Учебная 12"),
    ("дом 12 корпус 2 по улице Учебной", "Учебная 12"),
    ("дом 12 стр. 1 на Учебной", "Учебная 12"),
])
def test_house_and_street_remain_exact_gates(left, right):
    assert normalize_location(left) is not None
    assert normalize_location(right) is not None
    assert normalize_location(left) != normalize_location(right)


@pytest.mark.parametrize("left,right", [
    ("У ДОМА №12 НА УЛ. УЧЕБНОЙ", "Учебная 12"),
    ("д. 12 по ул. Учебной", "Учебная 12"),
    ("дом 15 по улице Примерной", "Примерная 15"),
    ("возле дома 3 на Тестовой", "Тестовая 3"),
    ("у дома 12а на Учебной", "Учебная 12а"),
    ("дом 12/1 по улице Учебной", "Учебная 12/1"),
    ("дом 12 корпус 2 по улице Учебной", "Учебная 12 корпус 2"),
    ("дом 12 стр. 1 на Учебной", "Учебная 12 стр. 1"),
    ("у дома 12 на Учебной, у подъезда", "Учебная 12"),
])
def test_general_constructions_preserve_house_details(left,right):
    assert normalize_location(left) is not None
    assert normalize_location(left) == normalize_location(right)


@pytest.mark.parametrize("location", ["возле дома 12", "дом на Учебной", "дом 12 или 15 на Учебной"])
def test_incomplete_or_ambiguous_address_is_not_guessed(location):
    assert normalize_location(location) is None


def actual_ai_analysis():
    # Isolate the supplied real extraction from the deliberately limited regex mock.
    analysis = mock_ai.analyze(TEXT)
    analysis.category = Category.LIGHTING
    analysis.location = "Возле дома 12 на Учебной"
    return analysis


def test_exact_real_ai_location_matches_history():
    analysis = actual_ai_analysis()
    assert normalize_location(analysis.location) == "учебная|12||"
    assert {c.id for c in find_candidates(TEXT,analysis)} == {"R-001","R-002","R-003","R-004"}
    analysis.location = "Возле дома 15 на Учебной"
    assert find_candidates(TEXT,analysis) == []


def test_exact_real_extraction_in_api_with_semantic_disabled(monkeypatch):
    analysis = actual_ai_analysis()
    monkeypatch.setattr(mock_ai,"analyze",lambda _:analysis)
    monkeypatch.setenv("EMBEDDING_PROVIDER","disabled")
    with TestClient(app) as client:
        response = client.post('/api/analyze',json={"text":TEXT})
        assert response.status_code == 200
        result = response.json()
        assert result['analysis']['location'] == "Возле дома 12 на Учебной"
        assert result['semantic_matching_status'] == 'disabled'
        assert result['probable_duplicate_count'] == 4
        assert {c['id'] for c in result['candidates']} == {"R-001","R-002","R-003","R-004"}
