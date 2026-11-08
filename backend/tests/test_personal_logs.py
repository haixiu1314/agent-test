from sqlalchemy import select
from conftest import authenticate
from app.models.entities import User


def test_personal_logs_always_belong_to_current_user(client, auth, application):
    other = authenticate(client, 'another_log_owner')
    other_id = client.get('/api/v1/auth/me', headers=other).json()['id']
    own_id = client.get('/api/v1/auth/me', headers=auth).json()['id']
    # 旧账号保留的内部角色不能让个人日志变成全站日志。
    with application.state.sessions() as db:
        db.scalar(select(User).where(User.id == own_id)).role = 'admin'
        db.commit()
    logs = client.get('/api/v1/operation-logs', headers=auth).json()
    assert logs['items'] and all(row['user_id'] == own_id for row in logs['items'])
    assert not any(row['user_id'] == other_id for row in logs['items'])
    assert client.get('/api/v1/admin/users', headers=auth).status_code == 404
    assert client.put('/api/v1/admin/users/' + other_id, headers=auth, json={'role': 'admin'}).status_code == 404
