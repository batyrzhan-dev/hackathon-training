"""Deterministic demo rules, independent of mock/real AI and of HTTP/UI."""
from .models import AIAnalysis, PriorityResult, Reason

RULES = (
    ("safety_risk", 40, "Риск безопасности"),
    ("critical_outage", 30, "Нарушение критической инфраструктуры / услуги"),
    ("persists_multiple_days", 10, "Проблема длится несколько дней"),
)


def priority_for_score(score: int) -> str:
    if type(score) is not int or not 0 <= score <= 100:
        raise ValueError("Score must be an integer from 0 to 100")
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def calculate_priority(analysis: AIAnalysis, probable_duplicate_count: int | None) -> PriorityResult:
    """Caller supplies count of other unique, non-rejected candidates.

    Phase 1 explicitly supplies 0 because detection is disabled. None means
    unknown/failed detection in future phases, and never silently means zero.
    """
    if probable_duplicate_count is not None and (
        type(probable_duplicate_count) is not int or probable_duplicate_count < 0
    ):
        raise ValueError("Duplicate count must be a non-negative integer or None")
    reasons = []
    unresolved = []
    for field, points, label in RULES:
        feature = getattr(analysis, field)
        if feature.value == "yes":
            reasons.append(Reason(rule_id=field, label=label, points=points,
                                  evidence_or_ids=feature.evidence))
        elif feature.value == "unknown":
            unresolved.append(field)
    if probable_duplicate_count is None:
        unresolved.append("probable_duplicate_count")
    elif probable_duplicate_count >= 3:
        reasons.append(Reason(rule_id="probable_duplicates", label="Три и более вероятных дубля",
                              points=20, evidence_or_ids=[f"Число кандидатов: {probable_duplicate_count}"]))
    subtotal = sum(reason.points for reason in reasons)
    return PriorityResult(
        score=None if unresolved else subtotal,
        priority=None if unresolved else priority_for_score(subtotal),
        subtotal=subtotal, reasons=reasons, unresolved=unresolved,
    )
