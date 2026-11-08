import httpx
import pytest
from app.adapters.http import HttpAgentAdapter
from app.adapters.base import AdapterError
from app.adapters.local import local_adapter


def config(**kwargs):
    return {'endpoint':'http://agent.test/chat','method':'POST','request_template':{'model':'test'},
        'input_field':'payload.question','output_field':'data.answer','history_field':'payload.history',
        'auth_header':'Authorization','timeout_seconds':0.5,'retries':0, **kwargs}


async def test_nested_mapping_headers_and_history():
    import json
    def handle(request):
        payload=json.loads(request.content)
        assert payload['payload']['question'] == 'hello'
        assert payload['payload']['history'] == [{'role':'user','content':'before'}]
        assert payload['model'] == 'test'
        assert request.headers['authorization'] == 'Bearer test'
        return httpx.Response(200,json={'data':{'answer':'ok'}})
    result=await HttpAgentAdapter(config(),{'api_key':'Bearer test'},httpx.MockTransport(handle)).invoke('hello',[{'role':'user','content':'before'}])
    assert result.output == 'ok' and result.attempts == 1
    assert result.observable_events == []


async def test_get_mapping():
    def handle(request):
        assert request.url.params['question'] == '你好'
        return httpx.Response(200,json={'output':'valid'})
    result=await HttpAgentAdapter(config(method='GET',input_field='question',output_field='output',history_field=None),{},httpx.MockTransport(handle)).invoke('你好',[])
    assert result.output == 'valid'


@pytest.mark.parametrize('response,code', [
    (httpx.Response(200,text='not json'),'invalid_json_response'),
    (httpx.Response(200,json={}),'output_field_missing'),
    (httpx.Response(200,json={'data':{'answer':123}}),'output_must_be_string'),
    (httpx.Response(401,text='secret-upstream-body'),'upstream_http_error'),
    (httpx.Response(302,headers={'location':'http://another.test'}),'upstream_http_error'),
    (httpx.Response(200,text='x'*(1024*1024+1)),'response_too_large'),
])
async def test_invalid_responses_are_sanitized(response,code):
    with pytest.raises(AdapterError) as caught:
        await HttpAgentAdapter(config(),{},httpx.MockTransport(lambda r:response)).invoke('test',[])
    assert caught.value.code == code
    assert 'secret-upstream-body' not in str(caught.value)


async def test_retry_bounds_and_success():
    calls=[]
    def handle(request):
        calls.append(1)
        return httpx.Response(503) if len(calls)<3 else httpx.Response(200,json={'data':{'answer':'ok'}})
    result=await HttpAgentAdapter(config(retries=2),{},httpx.MockTransport(handle)).invoke('test',[])
    assert result.attempts == 3 and len(calls) == 3


async def test_timeout_retry_exhaustion():
    calls=[]
    def handle(request):
        calls.append(1)
        raise httpx.ReadTimeout('private endpoint secret')
    with pytest.raises(AdapterError) as caught:
        await HttpAgentAdapter(config(retries=1),{},httpx.MockTransport(handle)).invoke('test',[])
    assert caught.value.code == 'upstream_timeout'
    assert len(calls) == 2


async def test_nonretryable_401_called_once():
    calls=[]
    def handle(request):
        calls.append(1)
        return httpx.Response(401)
    with pytest.raises(AdapterError):
        await HttpAgentAdapter(config(retries=3),{},httpx.MockTransport(handle)).invoke('test',[])
    assert len(calls) == 1


def test_only_registered_python_adapter():
    with pytest.raises(AdapterError):
        local_adapter('os.system')
