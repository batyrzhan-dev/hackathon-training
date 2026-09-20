import logging
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from .examples import EXAMPLES
from .models import AnalyzeRequest, OperatorCard, OperatorChange, ScoringField, FeatureValue
from .operator_review import review_store
from .providers import AnalysisError, get_provider, selected_provider_name
from .scoring import calculate_priority

logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent
app = FastAPI(title="Городской помощник · Phase 2")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.policies["json.dumps_kwargs"] = {"sort_keys": True, "ensure_ascii": False}


def build_card(payload: AnalyzeRequest) -> OperatorCard:
    provider = get_provider()
    try:
        analysis = provider.analyze(payload.text)
        analysis.validate_evidence(payload.text)
    except ValueError:
        raise AnalysisError("invalid_response") from None
    # Detection is still disabled: preserve the explicit Phase 1 assumption.
    scoring = calculate_priority(analysis, probable_duplicate_count=0)
    status = "mock_complete" if provider.name == "mock" else "real_complete"
    return review_store.add(OperatorCard(
        text=payload.text, analysis=analysis, scoring=scoring,
        analysis_status="needs_review" if scoring.unresolved else status,
        analysis_provider=provider.name, analysis_model=provider.model,
    ))


def render(request: Request, *, text="", card=None, error=None, status_code=200):
    return templates.TemplateResponse(
        request=request, name="index.html", status_code=status_code,
        context={"text": text, "card": card, "error": error, "examples": EXAMPLES,
                 "provider_name": card.analysis_provider if card else selected_provider_name()},
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request, example: str | None = None):
    text = next((item["text"] for item in EXAMPLES if item["id"] == example), "")
    return render(request, text=text)


@app.post("/analyze", response_class=HTMLResponse)
def analyze_form(request: Request, text: Annotated[str, Form()] = ""):
    try:
        payload = AnalyzeRequest(text=text)
    except ValidationError:
        return render(request, text=text, error="Введите обращение: от 1 до 5 000 символов после удаления пробелов по краям.", status_code=422)
    try:
        card = build_card(payload)
    except AnalysisError as exc:
        logger.warning("AI analysis rejected: code=%s reason=%s", exc.code, exc.reason)
        return render(request, text=text, error=exc.message, status_code=exc.status_code)
    return render(request, text=payload.text, card=card)


@app.post("/api/analyze", response_model=OperatorCard)
def analyze_api(payload: AnalyzeRequest):
    try:
        return build_card(payload)
    except AnalysisError as exc:
        logger.warning("AI analysis rejected: code=%s reason=%s", exc.code, exc.reason)
        raise HTTPException(status_code=exc.status_code,
                            detail={"code": exc.code, "message": exc.message, "reason": exc.reason}) from None


@app.post("/cards/{card_id}/features", response_class=HTMLResponse)
def change_feature_form(
    request: Request, card_id: str,
    field: Annotated[ScoringField, Form()], value: Annotated[FeatureValue, Form()],
    text: Annotated[str, Form()] = "",
):
    try:
        card = review_store.update(card_id, OperatorChange(field=field, value=value))
    except KeyError:
        return render(request, text=text,
                      error="Карточка устарела или сервер перезапущен. Выполните анализ заново.", status_code=404)
    return render(request, text=card.text, card=card)


@app.patch("/api/cards/{card_id}/features", response_model=OperatorCard)
def change_feature_api(card_id: str, change: OperatorChange):
    try:
        return review_store.update(card_id, change)
    except KeyError:
        raise HTTPException(status_code=404, detail="Карточка устарела. Выполните анализ заново.") from None
