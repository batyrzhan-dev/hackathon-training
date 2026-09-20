"""Short-lived local review state. No database or AI calls."""
from collections import OrderedDict
from secrets import token_urlsafe
from threading import Lock
from time import monotonic

from .models import Feature, OperatorCard, OperatorChange, OperatorScoringInput, DuplicateChange
from .scoring import calculate_priority

FIELDS = ("safety_risk", "critical_outage", "persists_multiple_days")


def apply_override(card: OperatorCard, change: OperatorChange) -> OperatorCard:
    updated = card.model_copy(deep=True)
    updated.operator_overrides[change.field] = change.value
    return recalculate_card(updated)


def recalculate_card(updated: OperatorCard) -> OperatorCard:
    effective = {}
    for field in FIELDS:
        if field in updated.operator_overrides:
            value = updated.operator_overrides[field]
            # These are explicitly operator decisions, never fabricated AI quotes.
            effective[field] = Feature(value=value, evidence=[f"Решение оператора (operator override): {value}"])
        else:
            effective[field] = getattr(updated.analysis, field).model_copy(deep=True)
    active_ids = sorted({candidate.id for candidate in updated.candidates if candidate.status != "rejected"})
    updated.probable_duplicate_count = updated.duplicate_count_for_scoring = len(active_ids)
    updated.scoring = calculate_priority(OperatorScoringInput(**effective), probable_duplicate_count=len(active_ids))
    for reason in updated.scoring.reasons:
        if reason.rule_id == "probable_duplicates":
            reason.evidence_or_ids = active_ids
    updated.analysis_status = ("needs_review" if updated.scoring.unresolved else
                               "mock_complete" if updated.analysis_provider == "mock" else "real_complete")
    return updated


class ReviewStore:
    """Bounded in-memory cards with idle expiry; snapshots cannot mutate originals."""
    def __init__(self, capacity=256, ttl_seconds=3600):
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self._cards = OrderedDict()
        self._lock = Lock()

    def _expire(self):
        now = monotonic()
        for key, (expires, _) in list(self._cards.items()):
            if expires <= now:
                del self._cards[key]

    def add(self, card: OperatorCard) -> OperatorCard:
        with self._lock:
            self._expire()
            saved = card.model_copy(deep=True)
            saved.card_id = token_urlsafe(24)
            self._cards[saved.card_id] = (monotonic() + self.ttl_seconds, saved)
            while len(self._cards) > self.capacity:
                self._cards.popitem(last=False)
            return saved.model_copy(deep=True)

    def update(self, card_id: str, change: OperatorChange) -> OperatorCard:
        with self._lock:
            self._expire()
            if card_id not in self._cards:
                raise KeyError("Review card expired or missing")
            updated = apply_override(self._cards[card_id][1], change)
            self._cards[card_id] = (monotonic() + self.ttl_seconds, updated)
            self._cards.move_to_end(card_id)
            return updated.model_copy(deep=True)

    def update_duplicate(self, card_id: str, report_id: str, change: DuplicateChange) -> OperatorCard:
        with self._lock:
            self._expire()
            if card_id not in self._cards:
                raise KeyError("Review card expired or missing")
            updated = self._cards[card_id][1].model_copy(deep=True)
            candidate = next((item for item in updated.candidates if item.id == report_id), None)
            if candidate is None:
                raise KeyError("Candidate missing")
            candidate.status = change.status
            updated = recalculate_card(updated)
            self._cards[card_id] = (monotonic() + self.ttl_seconds, updated)
            self._cards.move_to_end(card_id)
            return updated.model_copy(deep=True)


review_store = ReviewStore()
