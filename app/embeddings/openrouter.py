"""One OpenRouter embeddings request; no retries, redirects or paid fallback."""
import httpx
from pydantic import SecretStr

from .base import EmbeddingError, validate_vectors

ENDPOINT = "https://openrouter.ai/api/v1/embeddings"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class OpenRouterEmbeddingProvider:
    name = "openrouter"

    def __init__(self, api_key: str, model: str, *, transport=None):
        if not api_key.strip():
            raise EmbeddingError("missing_key")
        if not model.strip() or not model.strip().endswith(":free"):
            raise EmbeddingError("free_model_required")
        self._api_key = SecretStr(api_key.strip())
        self.model = model.strip()
        self._transport = transport

    def embed(self, texts: list[str]) -> list[tuple[float, ...]]:
        if not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise EmbeddingError("invalid_input")
        try:
            with httpx.Client(timeout=TIMEOUT, transport=self._transport, follow_redirects=False) as client:
                response = client.post(ENDPOINT,
                    headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                    json={"model": self.model, "input": texts, "encoding_format": "float",
                          "provider": {"allow_fallbacks": False}})
        except httpx.TimeoutException:
            raise EmbeddingError("timeout") from None
        except httpx.RequestError:
            raise EmbeddingError("network") from None
        if response.status_code == 429:
            raise EmbeddingError("rate_limit")
        if response.status_code in (401, 403):
            raise EmbeddingError("authentication")
        if not response.is_success:
            raise EmbeddingError("api_error")
        if not response.content.strip():
            raise EmbeddingError("empty_response")
        try:
            body = response.json()
            if not isinstance(body, dict) or "error" in body:
                raise ValueError()
            rows = body["data"]
            if not isinstance(rows, list) or len(rows) != len(texts):
                raise ValueError()
            by_index = {}
            for row in rows:
                index = row["index"]
                if type(index) is not int or not 0 <= index < len(texts) or index in by_index:
                    raise ValueError()
                by_index[index] = row["embedding"]
            return validate_vectors([by_index[i] for i in range(len(texts))], len(texts))
        except (ValueError, KeyError, TypeError):
            raise EmbeddingError("invalid_response") from None
