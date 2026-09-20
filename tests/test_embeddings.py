import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.embeddings import DEFAULT_EMBEDDING_MODEL, get_embedding_provider
from app.embeddings.base import EmbeddingError, cosine_similarity, validate_vectors
from app.embeddings.cache import HistoryEmbeddingCache
from app.embeddings.mock import MockEmbeddingProvider
from app.embeddings.openrouter import ENDPOINT, OpenRouterEmbeddingProvider
from app.models import HistoricalReport

MODEL = DEFAULT_EMBEDDING_MODEL
KEY = 'unit-test-only-no-secret'


def adapter(handler):
    return OpenRouterEmbeddingProvider(KEY, MODEL, transport=httpx.MockTransport(handler))


def test_request_and_out_of_order_response_without_paid_fallback():
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url) == ENDPOINT
        assert request.headers['Authorization'] == f'Bearer {KEY}'
        payload = json.loads(request.content)
        assert payload == {'model': MODEL, 'input': ['a', 'b'], 'encoding_format':'float',
                           'provider': {'allow_fallbacks':False}}
        assert request.extensions['timeout']['read'] == 15
        return httpx.Response(200,json={'data':[{'index':1,'embedding':[0,1]}, {'index':0,'embedding':[1,0]}]})
    provider = adapter(handler)
    assert provider.embed(['a','b']) == [(1,0),(0,1)]
    assert len(calls) == 1
    assert KEY not in repr(provider) and KEY not in repr(provider._api_key)


@pytest.mark.parametrize('body', [None, [], {}, {'error':'secret'}, {'data':[]},
    {'data':[{'index':0,'embedding':[]}]}, {'data':[{'index':0,'embedding':[0,0]}]},
    {'data':[{'index':False,'embedding':[1]}]}, {'data':[{'index':1,'embedding':[1]}]},
    {'data':[{'index':0,'embedding':['1']}]}, {'data':[{'index':0,'embedding':[True]}]},
    {'data':[{'index':0,'embedding':[float('nan')]}]}, {'data':[{'index':0,'embedding':[float('inf')]}]},
    {'data':[None]}, {'data':[{'index':0,'embedding':'base64'}]}])
def test_malformed_response(body):
    provider = adapter(lambda _:httpx.Response(200,content=json.dumps(body)))
    with pytest.raises(EmbeddingError,match='invalid_response'):
        provider.embed(['text'])


@pytest.mark.parametrize('rows', [
    [{'index':0,'embedding':[1]},{'index':0,'embedding':[1]}],
    [{'index':0,'embedding':[1]},{'index':1,'embedding':[1,2]}]])
def test_duplicate_indices_or_dimension_mismatch(rows):
    with pytest.raises(EmbeddingError,match='invalid_response'):
        adapter(lambda _:httpx.Response(200,json={'data':rows})).embed(['a','b'])


@pytest.mark.parametrize('content,code', [(b'', 'empty_response'),(b'   ','empty_response'),(b'{broken','invalid_response')])
def test_empty_or_invalid_json(content,code):
    with pytest.raises(EmbeddingError,match=code):
        adapter(lambda _:httpx.Response(200,content=content)).embed(['a'])


@pytest.mark.parametrize('status,code', [(401,'authentication'),(403,'authentication'),(429,'rate_limit'),
                                        (302,'api_error'),(404,'api_error'),(500,'api_error')])
def test_api_errors_no_retry_or_body_leak(status,code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status,text=KEY,headers={'Location':'https://example.com'})
    with pytest.raises(EmbeddingError) as caught:
        adapter(handler).embed(['a'])
    assert caught.value.code == code and KEY not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize('exception,code', [(httpx.ReadTimeout,'timeout'),(httpx.ConnectError,'network')])
def test_network_errors(exception,code):
    def handler(request):
        raise exception(KEY,request=request)
    with pytest.raises(EmbeddingError,match=code) as caught:
        adapter(handler).embed(['a'])
    assert KEY not in str(caught.value)


def test_factory_selection_and_configurable_free_model(monkeypatch):
    assert get_embedding_provider() is None
    monkeypatch.setenv('EMBEDDING_PROVIDER','mock')
    assert isinstance(get_embedding_provider(),MockEmbeddingProvider)
    monkeypatch.setenv('EMBEDDING_PROVIDER','openrouter')
    with pytest.raises(EmbeddingError,match='missing_key'):
        get_embedding_provider()
    monkeypatch.setenv('OPENROUTER_API_KEY',KEY)
    assert get_embedding_provider().model == MODEL
    monkeypatch.setenv('OPENROUTER_EMBEDDING_MODEL','custom/configured:free')
    assert get_embedding_provider().model == 'custom/configured:free'
    monkeypatch.setenv('OPENROUTER_EMBEDDING_MODEL','paid/model')
    with pytest.raises(EmbeddingError,match='free_model_required'):
        get_embedding_provider()
    monkeypatch.setenv('EMBEDDING_PROVIDER','unexpected')
    with pytest.raises(EmbeddingError,match='configuration'):
        get_embedding_provider()


@pytest.mark.parametrize('vectors', [[[1],[1,2]], [[0,0],[1,0]], [[1e309],[1]], [[True],[1]], [[1]*16385]])
def test_vector_validation(vectors):
    with pytest.raises(EmbeddingError):
        validate_vectors(vectors,len(vectors))


def test_cosine_bounds_and_numerical_stability():
    assert cosine_similarity([1,0],[1,0]) == 1
    assert cosine_similarity([1,0],[-1,0]) == -1
    assert cosine_similarity([1,0],[0,1]) == 0
    assert cosine_similarity([1e300,1e300],[1e300,1e300]) == pytest.approx(1)


def report(text='history',id='R'):
    return HistoricalReport(id=id,text=text,category='Освещение',location='Учебная 12')


def test_cache_reuses_history_but_never_query_and_invalidates_by_content_model():
    cache = HistoryEmbeddingCache()
    provider = MockEmbeddingProvider()
    cache.vectors(provider,'query1',[report()])
    cache.vectors(provider,'query2',[report()])
    assert provider.calls == [('query1','history'),('query2',)]
    cache.vectors(provider,'query3',[report('edited')])
    assert provider.calls[-1] == ('query3','edited')
    provider.model = 'new-model'
    cache.vectors(provider,'query4',[report('edited')])
    assert provider.calls[-1] == ('query4','edited')
    assert len(cache._values) == 3
    assert all('query' not in str(key) for key in cache._values)


def test_cache_is_bounded_and_thread_safe():
    cache = HistoryEmbeddingCache(capacity=2)
    provider = MockEmbeddingProvider()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i:cache.vectors(provider,f'query{i}',[report()]),range(4)))
    assert sum('history' in call for call in provider.calls) == 1
    for i in range(4):
        cache.vectors(provider,'q',[report(str(i),str(i))])
    assert len(cache._values) == 2


def test_failed_fill_not_cached_and_dimension_change_recovers():
    cache = HistoryEmbeddingCache()
    provider = MockEmbeddingProvider({'q':[1,0],'history':[1]})
    with pytest.raises(EmbeddingError):
        cache.vectors(provider,'q',[report()])
    assert not cache._values
    provider.vectors = {'q':[1,0],'history':[1,0]}
    cache.vectors(provider,'q',[report()])
    provider.vectors = {'q':[1,0,0],'history':[1,0,0]}
    with pytest.raises(EmbeddingError):
        cache.vectors(provider,'q',[report()])
    assert not cache._values
    assert len(cache.vectors(provider,'q',[report()])[0]) == 3
