"""个人配置和真实本机OpenAI兼容协议验证；不把协议替身当真实模型效果。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from conftest import authenticate
from app.models.entities import ModelConfig, User, OperationLog
from app.services.models import resolve_model, resolve_embedding


@pytest.fixture
def provider():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append({'path': self.path, 'model': body['model'], 'output_limit': body.get('max_tokens', body.get('max_completion_tokens')), 'input': body.get('messages', body.get('input'))})
            status = 200
            if self.headers.get('Authorization') != 'Bearer personal-test-key':
                status, data = 401, {'error': {'message': 'never echo supplied credentials', 'type': 'invalid_api_key'}}
            elif body['model'] == 'missing':
                status, data = 404, {'error': {'message': 'missing model'}}
            elif self.path == '/v1/embeddings':
                data = {'object': 'list', 'data': [{'object': 'embedding', 'index': 0, 'embedding': [0.1, 0.2, 0.3]}], 'model': body['model'], 'usage': {'prompt_tokens': 1, 'total_tokens': 1}}
            else:
                data = {'id': 'local-test', 'object': 'chat.completion', 'created': 1, 'model': body['model'], 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '' if body['model'] == 'empty' else 'OK'}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
            encoded = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}/v1', calls
    server.shutdown()
    server.server_close()
    thread.join()


def draft(url, **changes):
    return {'name': '我的模型', 'base_url': url, 'model': 'protocol-only', 'api_key': 'personal-test-key', **changes}


def test_personal_crud_isolation_and_encryption(application, client, auth, provider, project):
    body = draft(provider[0])
    response = client.post('/api/v1/models', headers=auth, json=body)
    assert response.status_code == 201
    model_id = response.json()['id']
    assert 'personal-test-key' not in response.text
    other = authenticate(client, 'other_owner')
    assert client.get('/api/v1/models', headers=other).json()['items'] == []
    assert client.put('/api/v1/models/' + model_id, headers=other, json=body).status_code == 404
    assert client.post('/api/v1/models/test', headers=other, json={**body, 'saved_model_id': model_id}).status_code == 404
    other_project = client.post('/api/v1/projects', headers=other, json={'name': '另一个项目'}).json()
    assert client.post('/api/v1/generation-runs', headers=other, json={'project_id': other_project['id'], 'model_config_id': model_id, 'requirements': '验证账号隔离规则', 'types': ['functional'], 'count': 1}).status_code == 404
    assert client.post('/api/v1/demo/chat', headers=other, json={'project_id': other_project['id'], 'model_config_id': model_id, 'input': '你好'}).status_code == 404
    with application.state.sessions() as db:
        other_user = db.scalar(select(User).where(User.username == 'other_owner'))
        other_user.role = 'admin'
        db.commit()
        assert 'personal-test-key' not in db.get(ModelConfig, model_id).secret
        with pytest.raises(HTTPException) as error:
            resolve_model(db, application.state.settings, application.state.vault, model_id, user_id=other_user.id)
        assert error.value.status_code == 404
        with pytest.raises(HTTPException):
            resolve_embedding(db, application.state.settings, application.state.vault, model_id, user_id=other_user.id)
    assert client.get('/api/v1/models', headers=other).json()['items'] == []
    assert client.get('/api/v1/models', headers=auth).json()['items'][0]['id'] == model_id


def test_unsaved_chat_test_really_calls_provider_without_saving(application, client, auth, provider):
    response = client.post('/api/v1/models/test', headers=auth, json=draft(provider[0]))
    assert response.status_code == 200 and response.json()['success']
    assert response.json()['latency_ms'] >= 0
    assert provider[1][0]['path'] == '/v1/chat/completions'
    assert provider[1][0]['output_limit'] == 1
    assert provider[1][0]['input'] == [{'content': '.', 'role': 'user'}]
    assert 'personal-test-key' not in response.text
    with application.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ModelConfig)) == 0
        assert 'personal-test-key' not in str([r.resource_id for r in db.scalars(select(OperationLog))])


def test_saved_key_can_be_reused_and_replaced(client, auth, provider):
    body = draft(provider[0])
    model_id = client.post('/api/v1/models', headers=auth, json=body).json()['id']
    for key_value in (None, ''):
        response = client.post('/api/v1/models/test', headers=auth, json={**body, 'api_key': key_value, 'saved_model_id': model_id})
        assert response.json()['success']
    assert client.put('/api/v1/models/' + model_id, headers=auth, json={**body, 'api_key': None, 'name': '更名'}).json()['has_api_key']
    replaced = client.post('/api/v1/models/test', headers=auth, json={**body, 'api_key': 'wrong-secret', 'saved_model_id': model_id})
    assert replaced.json()['code'] == 'authentication_failed'
    assert 'wrong-secret' not in replaced.text


@pytest.mark.parametrize(('changes', 'code'), [({'api_key': 'wrong-secret'}, 'authentication_failed'), ({'model': 'missing'}, 'not_found'), ({'model': 'empty'}, 'call_failed')])
def test_provider_failures_are_honest_and_sanitized(client, auth, provider, changes, code):
    response = client.post('/api/v1/models/test', headers=auth, json=draft(provider[0], **changes))
    assert response.status_code == 200
    assert not response.json()['success'] and response.json()['code'] == code
    assert 'wrong-secret' not in response.text and 'never echo' not in response.text


def test_embedding_test_uses_embeddings_endpoint(client, auth, provider):
    response = client.post('/api/v1/models/test', headers=auth, json=draft(provider[0], purpose='embedding'))
    assert response.json()['success'] and '3 维' in response.json()['message']
    assert provider[1][0]['path'] == '/v1/embeddings'


def test_timeout_and_validation(client, auth, provider, monkeypatch):
    async def timeout(*args, **kwargs):
        raise TimeoutError('must never echo provider text')
    monkeypatch.setattr('app.api.v1.generation.invoke', timeout)
    response = client.post('/api/v1/models/test', headers=auth, json=draft(provider[0]))
    assert response.json()['code'] == 'timeout' and 'must never echo' not in response.text
    assert client.post('/api/v1/models/test', headers=auth, json=draft(provider[0], api_key=None)).status_code == 422
    assert client.post('/api/v1/models/test', json=draft(provider[0])).status_code == 401
    assert client.post('/api/v1/models/test', headers=auth, json=draft('https://u:password@invalid/v1')).status_code == 422
