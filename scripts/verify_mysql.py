"""真实 MySQL 集成验证。创建带独立前缀的测试用户，保留验收证据。"""
import json
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from sqlalchemy import text
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings
from app.db.session import make_engine
from sqlalchemy.engine import make_url

def main():
    settings=Settings()
    checks=[]
    engine=make_engine(settings.database_url.get_secret_value())
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT VERSION()')).startswith('8.')
        assert conn.scalar(text('SELECT version_num FROM alembic_version'))=='0007_delivery'
        grants=[row[0] for row in conn.execute(text('SHOW GRANTS'))]
        if make_url(settings.database_url.get_secret_value()).username == 'root':
            # 用户明确要求使用本机root；不再将专用低权限账号作为本配置的通过条件。
            account_check = 'user_requested_root_account'
        else:
            assert not any('ALL PRIVILEGES ON *.*' in g for g in grants)
            account_check = 'dedicated_account_grants'
        checks+=['mysql_version','migration',account_check]
    name='integration_'+uuid4().hex[:12]
    password='integration-only-password-123'
    with TestClient(create_app(settings)) as client:
        assert client.post('/api/v1/auth/register',json={'username':name,'password':password}).status_code==201
        token=client.post('/api/v1/auth/login',json={'username':name,'password':password}).json()['access_token']
        auth={'Authorization':'Bearer '+token}
        project=client.post('/api/v1/projects',headers=auth,json={'name':'真实 MySQL 验收项目'}).json()
        body={'project_id':project['id'],'name':'集成协议助手','kind':'python','api_key':'fixture-secret-value'}
        agent=client.post('/api/v1/agents',headers=auth,json=body).json()
        assert client.post('/api/v1/agents/'+agent['id']+'/test-connection',headers=auth,json={}).json()['success']
        changed=client.put('/api/v1/agents/'+agent['id'],headers=auth,json={**body,'name':'集成协议助手 v2','expected_version':1})
        assert changed.json()['version']==2
        assert client.get('/health/ready').status_code==200
        checks+=['register','login','project_insert','agent_insert','connection','version_update','readiness']
    # 新 engine + 新应用验证数据库连接重建后数据仍可读，不使用内存缓存证明持久化。
    with TestClient(create_app(settings)) as client:
        auth={'Authorization':'Bearer '+client.post('/api/v1/auth/login',json={'username':name,'password':password}).json()['access_token']}
        assert client.get('/api/v1/projects/'+project['id'],headers=auth).status_code==200
        versions=client.get('/api/v1/agents/'+agent['id']+'/versions',headers=auth).json()['items']
        assert len(versions)==2 and versions[1]['snapshot']['name']=='集成协议助手'
        assert 'fixture-secret-value' not in json.dumps(versions)
        checks+=['fresh_application_persistence','immutable_versions','no_secret_in_api']
    with engine.connect() as conn:
        ciphertext=conn.scalar(text('SELECT secret FROM agents WHERE id=:id'),{'id':agent['id']})
        assert 'fixture-secret-value' not in ciphertext
        assert conn.scalar(text('SELECT COUNT(*) FROM operation_logs'))>0
        checks+=['encrypted_storage','audit_persistence']
    engine.dispose()
    print(json.dumps({'status':'passed','count':len(checks),'checks':checks,'retained_test_username':name},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()

