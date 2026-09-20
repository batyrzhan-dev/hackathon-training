"""Provider-independent contracts. AI features never contain score or priority."""
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Category(StrEnum):
    ROADS = "Дороги"
    LIGHTING = "Освещение"
    WASTE = "Мусор"
    WATER = "Водоснабжение"
    YARDS = "Дворы"
    OTHER = "Другое"


class AnalyzeRequest(Contract):
    text: Text


Quote = Annotated[str, StringConstraints(min_length=1, max_length=5000)]


class Feature(Contract):
    value: Literal["yes", "no", "unknown"]
    evidence: list[Quote] = Field(default_factory=list)

    @model_validator(mode="after")
    def positive_needs_evidence(self):
        if self.value == "yes" and not self.evidence:
            raise ValueError("A positive feature requires source evidence")
        return self


class AIAnalysis(Contract):
    category: Category
    summary: Text
    location: Text | None = None
    event_time_text: Text | None = None
    ongoing: Literal["ongoing", "unknown"] = "unknown"
    safety_risk: Feature
    critical_outage: Feature
    persists_multiple_days: Feature
    review_reasons: list[str] = Field(default_factory=list)

    def validate_evidence(self, source: str) -> None:
        for feature in (self.safety_risk, self.critical_outage, self.persists_multiple_days):
            if any(quote not in source for quote in feature.evidence):
                raise ValueError("Evidence must be an exact quote from the input")


class Reason(Contract):
    rule_id: str
    label: str
    points: int
    evidence_or_ids: list[str]


class PriorityResult(Contract):
    score: int | None
    priority: Literal["LOW", "MEDIUM", "HIGH"] | None
    subtotal: int
    reasons: list[Reason]
    unresolved: list[str]


ScoringField = Literal["safety_risk", "critical_outage", "persists_multiple_days"]
FeatureValue = Literal["yes", "no", "unknown"]


class OperatorChange(Contract):
    field: ScoringField
    value: FeatureValue


class OperatorScoringInput(Contract):
    """Effective features for the engine, not an AI response or source quotes."""
    safety_risk: Feature
    critical_outage: Feature
    persists_multiple_days: Feature


class HistoricalReport(Contract):
    id: Text
    text: Text
    category: Category
    location: Text | None


class DuplicateCandidate(HistoricalReport):
    similarity: float = Field(ge=0, le=100)
    text_similarity: float = Field(ge=0, le=100)
    semantic_similarity: float | None = Field(default=None, ge=0, le=100)
    matching_method: Literal["lexical", "hybrid"] = "lexical"
    reasons: list[str]
    status: Literal["pending", "confirmed", "rejected"] = "pending"


class DuplicateChange(Contract):
    status: Literal["confirmed", "rejected"]


class OperatorCard(Contract):
    text: str
    analysis: AIAnalysis
    scoring: PriorityResult
    analysis_status: Literal["mock_complete", "real_complete", "needs_review"]
    duplicate_detection_status: Literal["complete"] = "complete"
    probable_duplicate_count: int = Field(default=0, ge=0)
    duplicate_count_for_scoring: int = Field(default=0, ge=0)
    candidates: list[DuplicateCandidate] = Field(default_factory=list)
    analysis_provider: Literal["mock", "openrouter"] = "mock"
    analysis_model: str | None = None
    semantic_matching_status: Literal["disabled", "complete", "mock", "fallback", "not_needed"] = "disabled"
    semantic_error: str | None = None
    embedding_model: str | None = None

    card_id: str | None = None
    operator_overrides: dict[ScoringField, FeatureValue] = Field(default_factory=dict)

    @computed_field
    @property
    def effective_values(self) -> dict[str, str]:
        return {field: self.operator_overrides.get(field, getattr(self.analysis, field).value)
                for field in ("safety_risk", "critical_outage", "persists_multiple_days")}
