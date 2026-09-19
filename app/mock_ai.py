"""Limited regex mock for Phase 1; no provider, score, priority or duplicate search."""
import re

from .models import AIAnalysis, Category, Feature

SAFETY = r"\b(?:искрит|искрение|огол[её]нн\w*\s+провод\w*|открыт\w*\s+люк\w*)\b"
OUTAGE = r"\b(?:нет\s+воды|без\s+воды|отключен[ао]?\s+вод[ауы]|водоснабжение\s+отсутствует)\b"
DURATION = r"\b(?:второй\s+день|третий\s+день|несколько\s+дней|[2-9]\d*\s+(?:дня|дней)|1\d+\s+(?:дня|дней))\b"
NEGATION = r"\b(?:не|нет|без)\s+(?:\w+\s+){0,2}$"
UNCERTAINTY = r"\b(?:возможно|кажется|вероятно|не\s+знаю)\b"


def extract_feature(text: str, pattern: str, negation_pattern: str = NEGATION) -> Feature:
    positives, negatives, uncertain = [], [], []
    for match in re.finditer(pattern, text, re.IGNORECASE):
        # Local clause is sufficient for this deliberately limited mock.
        prefix = re.split(r"[.!?;]", text[:match.start()])[-1][-80:]
        tail = text[match.end():match.end() + 12]
        if re.search(negation_pattern, prefix, re.IGNORECASE) or re.match(r"\s+нет\b", tail, re.IGNORECASE):
            negatives.append(match.group())
        elif re.search(UNCERTAINTY, prefix, re.IGNORECASE):
            uncertain.append(match.group())
        else:
            positives.append(match.group())
    if uncertain or (positives and negatives):
        return Feature(value="unknown", evidence=positives + negatives + uncertain)
    if positives:
        return Feature(value="yes", evidence=list(dict.fromkeys(positives)))
    return Feature(value="no", evidence=negatives)


def analyze(text: str) -> AIAnalysis:
    categories = (
        (Category.LIGHTING, r"фонар|освещ|столб|ламп"),
        (Category.WATER, r"вод[ауы]|водоснабж|труб"),
        (Category.WASTE, r"мусор|отход|контейнер"),
        (Category.ROADS, r"дорог|асфальт|ям[ауы]"),
        (Category.YARDS, r"двор|люк|площадк"),
    )
    matched = [category for category, pattern in categories if re.search(pattern, text, re.IGNORECASE)]
    location = re.search(r"(?:на\s+улице|ул\.)\s+[А-Яа-яЁё-]+\s*,?\s*\d+[А-Яа-яA-Za-z]?(?:/\d+)?", text, re.IGNORECASE)
    features = {
        "safety_risk": extract_feature(text, SAFETY),
        "critical_outage": extract_feature(text, OUTAGE),
        "persists_multiple_days": extract_feature(text, DURATION, negation_pattern=r"\bне\s+$"),
    }
    warnings = ["Mock: ограниченные текстовые шаблоны, не настоящий AI. Отсутствие совпадения означает no только в этой демонстрации."]
    if len(matched) > 1:
        warnings.append("Несколько категорий по шаблонам: проверьте выбранную основную категорию.")
    if any(feature.value == "unknown" for feature in features.values()):
        warnings.append("Неоднозначные признаки: итоговый приоритет не рассчитан.")
    # Extractive preview: no generated facts and no hardcoded final score.
    summary = text[:280] + ("…" if len(text) > 280 else "")
    duration = features["persists_multiple_days"]
    result = AIAnalysis(
        category=matched[0] if matched else Category.OTHER,
        summary=summary,
        location=location.group() if location else None,
        event_time_text=duration.evidence[0] if duration.evidence else None,
        ongoing="unknown",
        review_reasons=warnings,
        **features,
    )
    result.validate_evidence(text)
    return result
