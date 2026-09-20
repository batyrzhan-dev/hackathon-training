"""Add semantic candidates without removing the Phase 3 lexical path."""
from dataclasses import dataclass
from typing import Literal

from .duplicates import (HISTORY, CATEGORY_WEIGHT, LOCATION_WEIGHT, TEXT_WEIGHT,
                         eligible_reports, find_candidates, text_similarity)
from .embeddings import get_embedding_provider
from .embeddings.base import EmbeddingError, cosine_similarity
from .embeddings.cache import history_cache
from .models import DuplicateCandidate

LEXICAL_WEIGHT = 0.25
SEMANTIC_WEIGHT = 0.75
SEMANTIC_THRESHOLD = 80.0
HYBRID_TEXT_THRESHOLD = 65.0
# Final displayed score keeps Phase 3's category/location components: 60 + .4 * text.
HYBRID_THRESHOLD = CATEGORY_WEIGHT + LOCATION_WEIGHT + TEXT_WEIGHT * HYBRID_TEXT_THRESHOLD / 100


@dataclass
class MatchingResult:
    candidates: list[DuplicateCandidate]
    status: Literal["disabled", "complete", "mock", "fallback", "not_needed"]
    error: str | None = None
    model: str | None = None


ERROR_MESSAGES = {
    "missing_key": "Не задан OPENROUTER_API_KEY",
    "free_model_required": "Нужна embedding-модель с суффиксом :free",
    "configuration": "Проверьте EMBEDDING_PROVIDER",
    "timeout": "Истекло время ожидания embeddings",
    "network": "Сетевая ошибка embeddings",
    "rate_limit": "Лимит запросов embeddings",
    "authentication": "OpenRouter отклонил ключ",
    "api_error": "Ошибка API embeddings",
    "empty_response": "Пустой ответ embeddings",
    "invalid_response": "Некорректные векторы embeddings",
    "invalid_input": "Некорректный вход embeddings",
}


def hybrid_score(lexical: float, semantic: float) -> float:
    combined = LEXICAL_WEIGHT * lexical + SEMANTIC_WEIGHT * semantic
    return max(0.0, min(100.0, CATEGORY_WEIGHT + LOCATION_WEIGHT + TEXT_WEIGHT * combined / 100))


def match_duplicates(text, analysis, history=HISTORY) -> MatchingResult:
    lexical = find_candidates(text, analysis, history)
    model = None
    try:
        provider = get_embedding_provider()
        if provider is None:
            return MatchingResult(lexical, "disabled")
        model = provider.model
        eligible = eligible_reports(text, analysis, history)
        if not eligible:
            return MatchingResult([], "not_needed", model=model)
        query, vectors = history_cache.vectors(provider, text, eligible)
        legacy_ids = {candidate.id for candidate in lexical}
        candidates = []
        for report, vector in zip(eligible, vectors):
            lex = text_similarity(text, report.text)
            semantic = 100 * max(0.0, cosine_similarity(query, vector))
            score = hybrid_score(lex, semantic)
            semantic_match = semantic >= SEMANTIC_THRESHOLD and score >= HYBRID_THRESHOLD
            if report.id not in legacy_ids and not semantic_match:
                continue
            reasons = ["Совпала категория", "Совпал нормализованный адрес"]
            if report.id in legacy_ids:
                reasons.append("Похожее описание (lexical)")
            if semantic_match:
                reasons.append("Семантически похожее описание")
            candidates.append(DuplicateCandidate(**report.model_dump(), similarity=round(score, 1),
                text_similarity=round(lex, 1), semantic_similarity=round(semantic, 1),
                matching_method="hybrid" if semantic_match else "lexical", reasons=reasons))
        candidates.sort(key=lambda c: (-c.similarity, c.id))
        return MatchingResult(candidates, "mock" if provider.name == "mock" else "complete", model=model)
    except EmbeddingError as exc:
        return MatchingResult(lexical, "fallback", ERROR_MESSAGES.get(exc.code, "Ошибка embeddings"), model)
