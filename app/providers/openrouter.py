"""OpenRouter Chat Completions adapter. One request; no fallback or retries."""
import json

import httpx
from pydantic import SecretStr, ValidationError

from ..models import AIAnalysis
from .base import AnalysisError
from .prompts import SYSTEM_PROMPT

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = httpx.Timeout(45.0, connect=10.0)


def response_schema() -> dict:
    schema = AIAnalysis.model_json_schema()

    def require_all(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
                node["additionalProperties"] = False
            for value in node.values():
                require_all(value)
        elif isinstance(node, list):
            for value in node:
                require_all(value)

    require_all(schema)
    return schema


def parse_analysis(content: str, source: str) -> AIAnalysis:
    try:
        raw = json.loads(content)
    except (ValueError, TypeError):
        raise AnalysisError("invalid_response", reason="json") from None
    if not isinstance(raw, dict) or set(raw) != set(AIAnalysis.model_fields):
        raise AnalysisError("invalid_response", reason="fields")
    for field in ("safety_risk", "critical_outage", "persists_multiple_days"):
        feature = raw[field]
        if not isinstance(feature, dict) or set(feature) != {"value", "evidence"}:
            raise AnalysisError("invalid_response", reason="feature_shape")
    try:
        result = AIAnalysis.model_validate_json(content, strict=True)
    except (ValueError, ValidationError, TypeError):
        raise AnalysisError("invalid_response", reason="schema") from None
    for feature in (result.safety_risk, result.critical_outage, result.persists_multiple_days):
        if feature.value == "no" and not feature.evidence:
            raise AnalysisError("invalid_response", reason="negative_without_evidence")
    try:
        result.validate_evidence(source)
    except ValueError:
        raise AnalysisError("invalid_evidence") from None
    return result


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, api_key: str, model: str, *, transport: httpx.BaseTransport | None = None):
        if not api_key.strip():
            raise AnalysisError("missing_key")
        if not model.strip():
            raise AnalysisError("missing_model")
        self._api_key = SecretStr(api_key.strip())
        self.model = model.strip()
        self._transport = transport

    def analyze(self, text: str) -> AIAnalysis:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"complaint": text}, ensure_ascii=False)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "resident_complaint", "strict": True, "schema": response_schema()},
            },
            "provider": {"require_parameters": True, "allow_fallbacks": False},
            "stream": False,
            "max_tokens": 4096,
        }
        try:
            with httpx.Client(timeout=TIMEOUT, transport=self._transport, follow_redirects=False) as client:
                response = client.post(
                    ENDPOINT,
                    headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                    json=payload,
                )
        except httpx.TimeoutException:
            raise AnalysisError("timeout") from None
        except httpx.RequestError:
            raise AnalysisError("network") from None

        # Do not expose or log raw response bodies, headers, or exception details.
        if response.status_code == 429:
            raise AnalysisError("rate_limit")
        if response.status_code in (401, 403):
            raise AnalysisError("authentication")
        if not response.is_success:
            raise AnalysisError("api_error")
        if not response.content.strip():
            raise AnalysisError("empty_response")
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Invalid envelope")
            if "error" in body:
                raise AnalysisError("api_error")
            choices = body["choices"]
            if not isinstance(choices, list):
                raise ValueError("Invalid choices")
            if not choices:
                raise AnalysisError("empty_response")
            choice = choices[0]
            if choice.get("finish_reason") == "length":
                raise AnalysisError("invalid_response", reason="truncated")
            if choice.get("finish_reason") not in (None, "stop"):
                raise AnalysisError("invalid_response", reason="incomplete")
            content = choice["message"]["content"]
            if content is None or (isinstance(content, str) and not content.strip()):
                raise AnalysisError("empty_response")
            if not isinstance(content, str):
                raise ValueError("Invalid content type")
        except (ValueError, KeyError, TypeError, AttributeError):
            raise AnalysisError("invalid_response", reason="envelope") from None
        return parse_analysis(content, text)
