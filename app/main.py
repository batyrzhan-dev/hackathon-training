from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from . import mock_ai
from .examples import EXAMPLES
from .models import AnalyzeRequest, OperatorCard
from .scoring import calculate_priority

BASE = Path(__file__).resolve().parent
app = FastAPI(title="Городской помощник · Phase 1")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.policies["json.dumps_kwargs"] = {"sort_keys": True, "ensure_ascii": False}


def build_card(payload: AnalyzeRequest) -> OperatorCard:
    analysis = mock_ai.analyze(payload.text)
    analysis.validate_evidence(payload.text)
    # Explicit phase-limited assumption, not a claim that no duplicates exist.
    scoring = calculate_priority(analysis, probable_duplicate_count=0)
    return OperatorCard(text=payload.text, analysis=analysis, scoring=scoring,
                        analysis_status="needs_review" if scoring.unresolved else "mock_complete")


def render(request: Request, *, text="", card=None, error=None, status_code=200):
    return templates.TemplateResponse(request=request, name="index.html", status_code=status_code,
                                      context={"text": text, "card": card, "error": error, "examples": EXAMPLES})


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
    except ValueError:
        return render(request, text=text, error="Не удалось проверить результат анализа. Повторите попытку.", status_code=502)
    return render(request, text=payload.text, card=card)


@app.post("/api/analyze", response_model=OperatorCard)
def analyze_api(payload: AnalyzeRequest):
    try:
        return build_card(payload)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Invalid analysis result") from exc
