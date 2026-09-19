from itertools import product

import pytest
from pydantic import ValidationError

from app.models import AIAnalysis, Feature
from app.scoring import calculate_priority, priority_for_score


def features(safety=False, outage=False, days=False):
    def feature(value):
        return Feature(value="yes" if value else "no", evidence=["test evidence"] if value else [])
    return AIAnalysis(category="Другое", summary="Test", safety_risk=feature(safety),
                      critical_outage=feature(outage), persists_multiple_days=feature(days))


@pytest.mark.parametrize("safety,outage,duplicates,days", list(product([False, True], repeat=4)))
def test_all_rule_combinations(safety, outage, duplicates, days):
    result = calculate_priority(features(safety, outage, days), 3 if duplicates else 0)
    expected = 40 * safety + 30 * outage + 20 * duplicates + 10 * days
    assert result.score == expected == result.subtotal
    assert result.priority == ("HIGH" if expected >= 60 else "MEDIUM" if expected >= 30 else "LOW")
    expected_rules = {name for enabled, name in [(safety, "safety_risk"), (outage, "critical_outage"),
                                               (duplicates, "probable_duplicates"), (days, "persists_multiple_days")] if enabled}
    assert {reason.rule_id for reason in result.reasons} == expected_rules
    assert sum(reason.points for reason in result.reasons) == expected
    assert all(reason.evidence_or_ids for reason in result.reasons)
    assert not result.unresolved


@pytest.mark.parametrize("score,priority", [(0,"LOW"),(29,"LOW"),(30,"MEDIUM"),(59,"MEDIUM"),(60,"HIGH"),(100,"HIGH")])
def test_priority_boundaries(score, priority):
    assert priority_for_score(score) == priority


@pytest.mark.parametrize("score", [-1, 101, True, 30.5, "30"])
def test_invalid_scores(score):
    with pytest.raises(ValueError):
        priority_for_score(score)


@pytest.mark.parametrize("count,points", [(0,0),(1,0),(2,0),(3,20),(4,20),(100,20)])
def test_duplicate_threshold_once(count, points):
    assert calculate_priority(features(), count).score == points


@pytest.mark.parametrize("count", [-1, True, 3.1, "3"])
def test_invalid_duplicate_count(count):
    with pytest.raises(ValueError):
        calculate_priority(features(), count)


def test_unknown_duplicate_count_is_not_zero():
    result = calculate_priority(features(safety=True), None)
    assert result.score is None and result.priority is None
    assert result.subtotal == 40
    assert result.unresolved == ["probable_duplicate_count"]


@pytest.mark.parametrize("field", ["safety_risk", "critical_outage", "persists_multiple_days"])
def test_unknown_feature_does_not_produce_final_priority(field):
    analysis = features()
    setattr(analysis, field, Feature(value="unknown"))
    result = calculate_priority(analysis, 0)
    assert result.score is None and result.priority is None
    assert result.unresolved == [field]


def test_repeated_evidence_never_multiplies_points():
    analysis = features(safety=True)
    analysis.safety_risk.evidence *= 3
    assert calculate_priority(analysis, 0).score == 40


def test_recalculation_does_not_mutate_features_or_accumulate():
    analysis = features(safety=True, days=True)
    before = analysis.model_dump()
    assert calculate_priority(analysis, 3).score == 70
    assert calculate_priority(analysis, 2).score == 50
    assert calculate_priority(analysis, 3).score == 70
    assert analysis.model_dump() == before


def test_positive_requires_evidence():
    with pytest.raises(ValidationError):
        Feature(value="yes")
