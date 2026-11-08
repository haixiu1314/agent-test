"""SQLite 只作快速测试替身，不能作为 MySQL 集成验收证据。"""
import pytest
from sqlalchemy import create_engine, event
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from app.core.config import Settings
from app.main import create_app
from app.models.entities import Base


@pytest.fixture
def application(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'unit-tests.db'), connect_args={'check_same_thread': False})
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, record):
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    settings = Settings(_env_file=None, database_url='test-only-engine-injection', jwt_secret_key='a'*48,
                        encryption_key=Fernet.generate_key().decode())
    app = create_app(settings, test_engine=engine)
    yield app
    engine.dispose()


@pytest.fixture
def client(application):
    with TestClient(application) as result:
        yield result


def authenticate(client, name='tester_a'):
    payload = {'username': name, 'password': 'test-password-123'}
    assert client.post('/api/v1/auth/register', json=payload).status_code == 201
    response = client.post('/api/v1/auth/login', json=payload)
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


@pytest.fixture
def auth(client):
    return authenticate(client)


@pytest.fixture
def project(client, auth):
    return client.post('/api/v1/projects', headers=auth, json={'name': '企业助手测试'}).json()
