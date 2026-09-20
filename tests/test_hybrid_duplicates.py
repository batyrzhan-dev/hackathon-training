import pytest
from fastapi.testclient import TestClient

from app import hybrid_duplicates
from app.duplicates import HISTORY, find_candidates, text_similarity
from app.embeddings.base import EmbeddingError
from app.embeddings.mock import MockEmbeddingProvider
from app.examples import EXAMPLES
from app.hybrid_duplicates import hybrid_score, match_duplicates
from app.main import app
from app.mock_ai import analyze
from app.models import Category, HistoricalReport

A = 'Уличный светильник у здания погас, ночью темно.'
B = 'Сломан фонарь около подъезда, нужна замена.'
SOURCE = EXAMPLES[0]['text']


def fixture_pair(monkeypatch, category='Освещение', location='Учебная 12'):
    analysis = analyze(A)
    analysis.location = 'улица Учебная, дом 12'
    analysis.category = Category.LIGHTING  # supplied by structured extraction, not the regex mock
    report = HistoricalReport(id='semantic-demo',text=B,category=category,location=location)
    provider = MockEmbeddingProvider({A:[1,0],B:[.99,.01]})
    monkeypatch.setattr(hybrid_duplicates,'get_embedding_provider',lambda:provider)
    return analysis, report, provider


def test_semantic_signal_adds_low_lexical_paraphrase_using_fixture_vectors(monkeypatch):
    # Tests pipeline decisions with controlled vectors, not real model accuracy.
    analysis,report,provider = fixture_pair(monkeypatch)
    assert text_similarity(A,B) < 50
    assert find_candidates(A,analysis,(report,)) == []
    result = match_duplicates(A,analysis,(report,))
    assert result.status == 'mock'
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.semantic_similarity > 99
    assert candidate.matching_method == 'hybrid'
    assert 'Семантически похожее описание' in candidate.reasons
    assert candidate.similarity >= 86


@pytest.mark.parametrize('category,location', [('Мусор','Учебная 12'),('Освещение','Учебная 13'),
                                              ('Освещение','Учебная 12а'),('Освещение',None)])
def test_gates_block_even_identical_semantic_vectors(monkeypatch,category,location):
    analysis,report,provider = fixture_pair(monkeypatch,category,location)
    result = match_duplicates(A,analysis,(report,))
    assert result.candidates == [] and result.status == 'not_needed'
    assert provider.calls == []


@pytest.mark.parametrize('text', ['Фонарь исправен, раньше было темно.', 'Не работает лампа внутри квартиры.'])
def test_resolved_and_indoor_guards_remain(monkeypatch,text):
    analysis,report,provider = fixture_pair(monkeypatch)
    report.text = text
    assert match_duplicates(A,analysis,(report,)).candidates == []
    assert provider.calls == []


@pytest.mark.parametrize('lexical,semantic', [(0,0),(0,100),(100,0),(100,100),(62,91),(40,99)])
def test_hybrid_formula_and_bounds(lexical,semantic):
    assert hybrid_score(lexical,semantic) == pytest.approx(60+.4*(.25*lexical+.75*semantic))
    assert 0 <= hybrid_score(lexical,semantic) <= 100


def test_weak_semantics_does_not_add_candidate(monkeypatch):
    analysis,report,provider = fixture_pair(monkeypatch)
    provider.vectors[B] = [0,1]
    assert match_duplicates(A,analysis,(report,)).candidates == []


def test_low_semantics_does_not_remove_existing_lexical_candidates(monkeypatch):
    vectors = {r.text:[0,1] for r in HISTORY}
    vectors[SOURCE] = [1,0]
    monkeypatch.setattr(hybrid_duplicates,'get_embedding_provider',lambda:MockEmbeddingProvider(vectors))
    result = match_duplicates(SOURCE,analyze(SOURCE))
    assert {c.id for c in result.candidates} == {c.id for c in find_candidates(SOURCE,analyze(SOURCE))}
    assert all(c.matching_method == 'lexical' and c.semantic_similarity == 0 for c in result.candidates)


@pytest.mark.parametrize('code', ['timeout','invalid_response','missing_key','rate_limit','network','api_error'])
def test_provider_failure_uses_exact_phase3_fallback(monkeypatch,code):
    class Failing:
        name = 'openrouter'
        model = 'test:free'
        def embed(self,texts):
            raise EmbeddingError(code)
    monkeypatch.setattr(hybrid_duplicates,'get_embedding_provider',lambda:Failing())
    analysis = analyze(SOURCE)
    result = match_duplicates(SOURCE,analysis)
    assert result.status == 'fallback' and result.error
    assert result.candidates == find_candidates(SOURCE,analysis)
    assert all(c.semantic_similarity is None for c in result.candidates)


def test_missing_credentials_fallback_visible_in_html_and_api(monkeypatch):
    monkeypatch.setenv('EMBEDDING_PROVIDER','openrouter')
    with TestClient(app) as client:
        result = client.post('/api/analyze',json={'text':SOURCE}).json()
        assert result['semantic_matching_status'] == 'fallback'
        assert result['scoring']['score'] == 70
        page = client.post('/analyze',data={'text':SOURCE})
        assert page.status_code == 200
        assert 'Semantic matching temporarily unavailable. Used lexical fallback.' in page.text
        assert 'Не задан OPENROUTER_API_KEY' in page.text
        assert 'Semantic: не рассчитан' in page.text


def test_hybrid_review_and_feature_overrides_never_reembed(monkeypatch):
    vectors = {r.text:[1,0] for r in HISTORY}
    vectors[SOURCE] = [1,0]
    provider = MockEmbeddingProvider(vectors)
    monkeypatch.setattr(hybrid_duplicates,'get_embedding_provider',lambda:provider)
    with TestClient(app) as client:
        original = client.post('/api/analyze',json={'text':SOURCE}).json()
        assert original['semantic_matching_status'] == 'mock'
        assert original['scoring']['score'] == 70
        card_id = original['card_id']
        for report_id in ('R-001','R-002'):
            result = client.patch(f'/api/cards/{card_id}/duplicates/{report_id}',json={'status':'rejected'}).json()
        assert result['scoring']['score'] == 50 and result['probable_duplicate_count'] == 2
        result = client.patch(f'/api/cards/{card_id}/duplicates/R-001',json={'status':'confirmed'}).json()
        assert result['scoring']['score'] == 70
        result = client.patch(f'/api/cards/{card_id}/features',json={'field':'critical_outage','value':'unknown'}).json()
        assert result['scoring']['priority'] is None and result['scoring']['subtotal'] == 70
        assert result['analysis'] == original['analysis']
        assert len(provider.calls) == 1
        page = client.post('/analyze',data={'text':SOURCE})
        assert 'Lexical:' in page.text and 'Semantic: 100.0/100' in page.text
        assert 'Mock embeddings' in page.text


def test_malformed_vectors_from_provider_fall_back(monkeypatch):
    provider = MockEmbeddingProvider()
    monkeypatch.setattr(provider,'embed',lambda _: [[float('nan')]])
    monkeypatch.setattr(hybrid_duplicates,'get_embedding_provider',lambda:provider)
    result = match_duplicates(SOURCE,analyze(SOURCE))
    assert result.status == 'fallback'
    assert len(result.candidates) == 4


def test_openrouter_adapter_in_complete_flow_with_mock_http(monkeypatch):
    import json
    import httpx
    from app import embeddings
    from app.embeddings.openrouter import OpenRouterEmbeddingProvider
    batches = []
    def handler(request):
        inputs = json.loads(request.content)['input']
        batches.append(inputs)
        return httpx.Response(200,json={'data':[{'index':i,'embedding':[1,0]} for i in range(len(inputs))]})
    transport = httpx.MockTransport(handler)
    monkeypatch.setenv('EMBEDDING_PROVIDER','openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY','unit-test-only')
    monkeypatch.setattr(embeddings,'OpenRouterEmbeddingProvider',
        lambda **kw:OpenRouterEmbeddingProvider(**kw,transport=transport))
    with TestClient(app) as client:
        result = client.post('/api/analyze',json={'text':SOURCE}).json()
        assert result['semantic_matching_status'] == 'complete'
        assert result['embedding_model'] == 'nvidia/nemotron-3-embed-1b:free'
        page = client.post('/analyze',data={'text':SOURCE})
        assert page.status_code == 200 and 'Hybrid matching' in page.text
        assert 'Semantic: 100.0/100' in page.text
    assert len(batches) == 2 and len(batches[0]) == 5 and batches[1] == [SOURCE]
