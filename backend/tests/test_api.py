import json
from datetime import datetime, timedelta, timezone
import jwt
import pytest
from sqlalchemy import select
from app.models.entities import User, Agent, AgentVersion, OperationLog
from app.db.session import make_engine
from app.core.config import Settings
from conftest import authenticate


def agent_body(project, **overrides):
    return {'project_id': project['id'], 'name': '协议验证助手', 'kind': 'python', **overrides}


def test_registration_login_and_invalid_password(client):
    headers = authenticate(client)
    assert client.get('/api/v1/auth/me', headers=headers).json()['role'] == 'tester'
    assert client.post('/api/v1/auth/register', json={'username':'tester_a','password':'test-password-123'}).status_code == 409
    assert client.post('/api/v1/auth/login', json={'username':'tester_a','password':'wrong-pass-123'}).status_code == 401


def test_password_stored_as_hash(client, auth, application):
    with application.state.sessions() as db:
        value = db.scalar(select(User)).password_hash
        assert value != 'test-password-123'
        assert 'test-password' not in value


def test_cannot_register_admin_or_leak_password(client):
    response = client.post('/api/v1/auth/register', json={'username':'admin','password':'secret-test-123','role':'admin'})
    assert response.status_code == 422
    assert 'secret-test-123' not in response.text
    assert 'request_id' in response.json()


@pytest.mark.parametrize('token', ['', 'garbage'])
def test_invalid_token(client, token):
    assert client.get('/api/v1/projects', headers={'Authorization':'Bearer '+token}).status_code == 401


def test_expired_token(client, auth, application):
    user_id = client.get('/api/v1/auth/me', headers=auth).json()['id']
    token = jwt.encode({'sub':user_id,'exp':datetime.now(timezone.utc)-timedelta(seconds=1),
        'iat':datetime.now(timezone.utc)-timedelta(hours=1),'aud':'agenttestlab-api','iss':'agenttestlab'}, 'a'*48, algorithm='HS256')
    assert client.get('/api/v1/projects', headers={'Authorization':'Bearer '+token}).status_code == 401


def test_project_crud(client, auth, project):
    pid = project['id']
    assert client.get('/api/v1/projects', headers=auth).json()['total'] == 1
    response = client.put('/api/v1/projects/'+pid, headers=auth, json={'name':'更新项目','description':'新说明'})
    assert response.json()['name'] == '更新项目'
    assert client.get('/api/v1/projects/'+pid, headers=auth).json()['description'] == '新说明'
    assert client.delete('/api/v1/projects/'+pid, headers=auth).status_code == 204
    assert client.get('/api/v1/projects/'+pid, headers=auth).status_code == 404


def test_isolation_for_projects_agents_versions_and_connection(client, auth, project):
    aid = client.post('/api/v1/agents', headers=auth, json=agent_body(project)).json()['id']
    other = authenticate(client, 'tester_b')
    assert client.get('/api/v1/projects', headers=other).json()['total'] == 0
    assert client.get('/api/v1/agents', headers=other).json()['total'] == 0
    for path in ['/projects/'+project['id'], '/agents/'+aid, '/agents/'+aid+'/versions']:
        assert client.get('/api/v1'+path, headers=other).status_code == 404
    assert client.put('/api/v1/agents/'+aid, headers=other, json=agent_body(project, expected_version=1)).status_code == 404
    assert client.delete('/api/v1/agents/'+aid, headers=other).status_code == 404
    assert client.post('/api/v1/agents/'+aid+'/test-connection', headers=other, json={}).status_code == 404


def test_encryption_and_immutable_versions(client, auth, project, application):
    secret = 'sample-private-token'
    response = client.post('/api/v1/agents', headers=auth, json=agent_body(project, api_key=secret, headers={'X-Token':secret}))
    assert response.status_code == 201
    assert secret not in response.text
    aid = response.json()['id']
    assert response.json()['has_api_key'] is True
    with application.state.sessions() as db:
        assert secret not in db.get(Agent, aid).secret
        version = db.scalar(select(AgentVersion))
        assert secret not in version.secret
        assert secret not in json.dumps(version.snapshot)
    result = client.put('/api/v1/agents/'+aid, headers=auth, json=agent_body(project, name='改名', expected_version=1))
    assert result.json()['version'] == 2
    assert result.json()['has_api_key'] is True
    versions = client.get('/api/v1/agents/'+aid+'/versions', headers=auth).json()['items']
    assert versions[1]['snapshot']['name'] == '协议验证助手'
    assert secret not in json.dumps(versions)
    assert client.put('/api/v1/agents/'+aid, headers=auth, json=agent_body(project, expected_version=1)).status_code == 409
    assert client.put('/api/v1/agents/'+aid, headers=auth, json=agent_body(project, expected_version=2, api_key='', headers={})).json()['has_api_key'] is False


def test_delete_project_refuses_linked_agents(client, auth, project):
    aid = client.post('/api/v1/agents', headers=auth, json=agent_body(project)).json()['id']
    assert client.delete('/api/v1/projects/'+project['id'], headers=auth).status_code == 409
    assert client.delete('/api/v1/agents/'+aid, headers=auth).status_code == 204
    assert client.delete('/api/v1/projects/'+project['id'], headers=auth).status_code == 204


def test_connection_is_real_controlled_adapter_and_audited(client, auth, project, application):
    aid = client.post('/api/v1/agents', headers=auth, json=agent_body(project)).json()['id']
    data = client.post('/api/v1/agents/'+aid+'/test-connection', headers=auth, json={'input':'hello'}).json()
    assert data['success'] is True and data['output_received'] is True
    assert data['tool_events'] == '不可观测'
    with application.state.sessions() as db:
        assert db.scalar(select(OperationLog).where(OperationLog.action == 'agent.connection.ok'))


@pytest.mark.parametrize('override', [
    {'kind':'http','endpoint':'file:///etc/passwd'},
    {'kind':'http','endpoint':'http://name:password@localhost/chat'},
    {'kind':'http','endpoint':'http://localhost/chat?key=secret'},
    {'adapter_name':'os.system'}, {'input_field':'a..b'},
    {'history_field':'input.history'}, {'retries':100}, {'timeout_seconds':0},
    {'headers':{'X-Token':'private\r\nInjection: yes'}},
])
def test_invalid_agent_configuration(client, auth, project, override):
    response = client.post('/api/v1/agents', headers=auth, json=agent_body(project, **override))
    assert response.status_code == 422
    assert 'password@' not in response.text and 'Injection:' not in response.text


def test_admin_authorization(client, auth, application):
    assert client.get('/api/v1/system/operation-logs', headers=auth).status_code == 403
    with application.state.sessions() as db:
        user = db.scalar(select(User))
        user.role = 'admin'
        db.commit()
    assert client.get('/api/v1/system/operation-logs', headers=auth).status_code == 200


def test_invalid_pagination(client, auth):
    assert client.get('/api/v1/projects?page=0', headers=auth).status_code == 422
    assert client.get('/api/v1/agents?page_size=1000', headers=auth).status_code == 422


def test_auth_rate_limit(client):
    for i in range(15):
        assert client.post('/api/v1/auth/login',json={'username':'unknown','password':'wrong-password-123'}).status_code == 401
    assert client.post('/api/v1/auth/login',json={'username':'unknown','password':'wrong-password-123'}).status_code == 429


def test_production_rejects_sqlite():
    with pytest.raises(ValueError):
        make_engine('sqlite:///production.db')


def test_missing_secrets_refused():
    with pytest.raises(ValueError):
        Settings(_env_file=None, database_url='unused', jwt_secret_key='short', encryption_key='invalid')


def test_live_and_openapi(client):
    response=client.get('/health/live')
    assert response.status_code == 200 and response.headers['x-request-id']
    assert '/api/v1/agents/{agent_id}/versions' in client.get('/openapi.json').json()['paths']


def test_readiness_does_not_hide_missing_migration_table(client):
    assert client.get('/health/ready').status_code == 503


def test_oversized_body_refused(client):
    assert client.post('/api/v1/auth/login', content=b'x'*(1024*1024+1)).status_code == 413
