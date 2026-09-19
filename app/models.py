"""Provider-independent contracts. AI features never contain score or priority."""
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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


class Feature(Contract):
    value: Literal["yes", "no", "unknown"]
    evidence: list[Text] = Field(default_factory=list)

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


class OperatorCard(Contract):
    text: str
    analysis: AIAnalysis
    scoring: PriorityResult
    analysis_status: Literal["mock_complete", "needs_review"]
    duplicate_detection_status: Literal["disabled_phase1"] = "disabled_phase1"
    probable_duplicate_count: int | None = None
    duplicate_count_for_scoring: Literal[0] = 0
    analysis_provider: Literal["mock"] = "mock"
