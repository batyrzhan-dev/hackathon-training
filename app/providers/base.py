"""Provider-independent analysis interface and safe user-facing errors."""
from typing import Literal, Protocol

from ..models import AIAnalysis

ProviderName = Literal["mock", "openrouter"]


class AnalysisProvider(Protocol):
    name: ProviderName
    model: str | None

    def analyze(self, text: str) -> AIAnalysis: ...


ERRORS = {
    "configuration": (503, "Неизвестный AI_PROVIDER. Выберите mock или openrouter в environment."),
    "missing_key": (503, "OpenRouter не настроен: отсутствует OPENROUTER_API_KEY. Настройте ключ в environment сервера."),
    "missing_model": (503, "OpenRouter не настроен: задайте OPENROUTER_MODEL в environment сервера."),
    "timeout": (504, "OpenRouter не ответил вовремя. Повторите попытку позже."),
    "rate_limit": (429, "Лимит запросов OpenRouter исчерпан. Повторите попытку позже."),
    "network": (502, "Не удалось связаться с OpenRouter. Проверьте соединение и повторите попытку."),
    "authentication": (503, "OpenRouter отклонил авторизацию. Проверьте ключ и доступ на сервере."),
    "api_error": (502, "OpenRouter вернул ошибку API. Проверьте доступность выбранной модели; автоматической замены модели нет."),
    "empty_response": (502, "OpenRouter вернул пустой результат. Повторите попытку позже."),
    "invalid_response": (502, "Не удалось проверить результат анализа: AI вернул некорректные structured data. Повторите попытку."),
    "invalid_evidence": (502, "Не удалось проверить результат анализа: цитата AI отсутствует в исходном обращении. Повторите попытку."),
}


DIAGNOSTICS = {
    "truncated": "Ответ модели обрезан по лимиту токенов; полный JSON не получен.",
    "json": "Ответ модели не является корректным JSON.",
    "fields": "В ответе отсутствуют обязательные поля или присутствуют лишние поля.",
    "feature_shape": "Признак должен содержать value и список evidence.",
    "schema": "Типы или значения полей не соответствуют контракту анализа.",
    "negative_without_evidence": "Модель вернула no без подтверждающей цитаты; такой вывод нельзя считать проверенным.",
    "envelope": "Ответ API не содержит ожидаемой структуры message/content.",
    "incomplete": "Модель не завершила обычный ответ (остановка, фильтр или вызов инструмента).",
}


class AnalysisError(Exception):
    """Only static messages: no provider response, credentials or request data."""
    def __init__(self, code: str, *, reason: str | None = None):
        self.code = code
        self.reason = reason if reason in DIAGNOSTICS else None
        self.status_code, self.message = ERRORS[code]
        if self.reason:
            self.message += " " + DIAGNOSTICS[self.reason]
        super().__init__(self.message)
