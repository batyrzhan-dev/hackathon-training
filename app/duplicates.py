"""Small deterministic demo matcher. No AI calls, writes, or external packages."""
import json
import re
from pathlib import Path

from .models import AIAnalysis, Category, DuplicateCandidate, HistoricalReport

TEXT_SIMILARITY_THRESHOLD = 50.0
DUPLICATE_SIMILARITY_THRESHOLD = 80.0
CATEGORY_WEIGHT = 20.0
LOCATION_WEIGHT = 40.0
TEXT_WEIGHT = 40.0


def normalize_text(text: str) -> str:
    return " ".join(re.findall(r"[а-яa-z0-9]+", text.lower().replace("ё", "е")))


def normalize_location(location: str | None) -> str | None:
    if not location:
        return None
    value = location.lower().replace("ё", "е")
    value = re.sub(r"[,.№]", " ", value)
    value = " ".join(value.split())
    # Recognise house-first syntax before removing address words. Reorder only
    # a full address; never guess the street or discard part of a house number.
    house_first = re.fullmatch(
        r"(?:(?:возле|у)\s+)?(?:дом|дома|д)\s+"
        r"(?P<number>\d+[а-яa-z]?(?:/\d+)?"
        r"(?:\s+(?:к|корпус|корп)\s*\d+[а-я]?)?"
        r"(?:\s+(?:стр|строение)\s*\d+[а-я]?)?)"
        r"\s+(?:по|на)\s+(?:(?:улица|улице|ул)\s+)?"
        r"(?P<street>[а-яa-z-]+(?:\s+[а-яa-z-]+)*?)"
        r"(?P<detail>\s+(?:у|возле|рядом)\b.*)?", value)
    if house_first:
        value = (f"{house_first['street']} {house_first['number']}"
                 f"{house_first['detail'] or ''}")
    elif re.match(r"(?:(?:возле|у)\s+)?(?:дом|дома|д)\b", value):
        # Incomplete house-first text must not turn a preposition into a street.
        return None
    value = re.sub(r"\b(?:на|улица|улице|ул|дом|дома|д)\b", " ", value)
    value = " ".join(value.split())
    # Require a street and house. Preserve letters, slash, корпус/строение.
    match = re.fullmatch(
        r"([а-яa-z -]+?)\s+(\d+[а-яa-z]?(?:/\d+)?)(?:\s+(?:к|корпус|корп)\.?\s*(\d+[а-я]?))?"
        r"(?:\s+(?:стр|строение)\.?\s*(\d+[а-я]?))?(?:\s+(?:у|возле|рядом)\b.*)?", value)
    if not match:
        return None
    street, house, building, structure = match.groups()
    street = re.sub(r"(?:ой|ую)\b", "ая", street.strip())
    return f"{street}|{house}|{building or ''}|{structure or ''}"


STOP_WORDS = set("на у в во из и а но возле рядом по о об со с к уже сегодня второй день дома дом улице улица ул подъезда подъезд жители сообщают нет не до сих пор том этом д".split())
FAILURE = re.compile(r"не\s+(?:горит|работает|светит)|нет\s+освещения|неисправ(?:ен|на|но|ны|н\w*)|сломан\w*|темно", re.I)
RESOLVED = re.compile(r"\b(?:починили|исправен|исправна|все\s+работает|теперь\s+.*работает|снова\s+.*(?:горит|работает))\b", re.I)
INDOOR = re.compile(r"квартир|внутри|настольн", re.I)


def text_tokens(text: str) -> set[str]:
    value = normalize_text(text)
    value = FAILURE.sub(" поломка ", value)
    value = re.sub(r"\b(?:фонар\w*|освещ\w*|ламп\w*|темно)\b", " светильник ", value)
    # Darkness/outage formulations can omit the noun entirely.
    if FAILURE.search(normalize_text(text)):
        value += " поломка"
    return {token for token in value.split() if token not in STOP_WORDS and not token.isdigit()}


def text_similarity(left: str, right: str) -> float:
    a, b = text_tokens(left), text_tokens(right)
    # Overlap coefficient tolerates a longer new report with extra safety details.
    return 100.0 * len(a & b) / min(len(a), len(b)) if a and b else 0.0


def load_history() -> tuple[HistoricalReport, ...]:
    data = json.loads((Path(__file__).parent / "data" / "reports.json").read_text(encoding="utf-8"))
    reports = tuple(HistoricalReport.model_validate(row) for row in data)
    if len({row.id for row in reports}) != len(reports):
        raise ValueError("Historical report IDs must be unique")
    return reports


HISTORY = load_history()


def eligible_reports(text: str, analysis: AIAnalysis,
                    history: tuple[HistoricalReport, ...] = HISTORY) -> list[HistoricalReport]:
    location = normalize_location(analysis.location)
    if location is None or analysis.category == Category.OTHER:
        return []
    candidates = []
    seen = set()
    for report in history:
        if report.id in seen:
            continue
        seen.add(report.id)
        if report.category != analysis.category or normalize_location(report.location) != location:
            continue
        # Conservative demo guards: restored lights and indoor lamps are different issues.
        if analysis.category == Category.LIGHTING:
            if any(not FAILURE.search(normalize_text(t)) or RESOLVED.search(normalize_text(t)) for t in (text, report.text)):
                continue
            if bool(INDOOR.search(text)) != bool(INDOOR.search(report.text)):
                continue
        candidates.append(report)
    return candidates


def find_candidates(text: str, analysis: AIAnalysis,
                    history: tuple[HistoricalReport, ...] = HISTORY) -> list[DuplicateCandidate]:
    candidates = []
    for report in eligible_reports(text, analysis, history):
        similarity = text_similarity(text, report.text)
        score = CATEGORY_WEIGHT + LOCATION_WEIGHT + TEXT_WEIGHT * similarity / 100
        if similarity >= TEXT_SIMILARITY_THRESHOLD and score >= DUPLICATE_SIMILARITY_THRESHOLD:
            candidates.append(DuplicateCandidate(**report.model_dump(), similarity=round(score, 1),
                text_similarity=round(similarity, 1), reasons=["Совпала категория", "Совпал нормализованный адрес", "Похожее описание"]))
    return sorted(candidates, key=lambda candidate: (-candidate.similarity, candidate.id))
