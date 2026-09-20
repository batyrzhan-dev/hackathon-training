from .. import mock_ai
from ..models import AIAnalysis


class MockProvider:
    name = "mock"
    model = None

    def analyze(self, text: str) -> AIAnalysis:
        return mock_ai.analyze(text)
