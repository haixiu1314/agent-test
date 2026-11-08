"""第二阶段真实 MySQL 验收：无真实模型密钥，不执行或冒充 AI 调用。"""
import json
import sys
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import create_app
from app.core.config import Settings
from app.db.session import make_engine

def main():
    settings=Settings();checks=[]
    username='stage2_'+uuid4().hex[:12];password='stage2-only-password-123'
    app=create_app(settings)
    with TestClient(app) as client:
        assert client.post('/api/v1/auth/register',json={'username':username,'password':password}).status_code==201
        auth={'Authorization':'Bearer '+client.post('/api/v1/auth/login',json={'username':username,'password':password}).json()['access_token']}
        project=client.post('/api/v1/projects',headers=auth,json={'name':'第二阶段真实 MySQL 验收'}).json()
        suite=client.post('/api/v1/suites',headers=auth,json={'project_id':project['id'],'name':'用例持久化'}).json()
        draft={'name':'真实数据库用例','test_type':'functional','scenario':'中文输入','user_input':'你好\n测试',
               'expected_behavior':'礼貌回应','expected_result':'包含问候','rules':{'evaluators':['rules'],'rubric':'按问候判定'}}
        def concurrent_create(_):
            return client.post('/api/v1/cases',headers=auth,params={'expected_revision':1},json={**draft,'suite_id':suite['id']}).status_code
        with ThreadPoolExecutor(2) as executor:statuses=sorted(executor.map(concurrent_create,range(2)))
        assert statuses==[201,409],statuses
        checks+=['suite_insert','mysql_row_lock_conflict']
        for format,revision in [('json',2),('csv',3)]:
            exported=client.get(f"/api/v1/suites/{suite['id']}/export",headers=auth,params={'format':format}).json()['content']
            r=client.post(f"/api/v1/suites/{suite['id']}/import",headers=auth,json={'content':exported,'format':format,'expected_revision':revision})
            assert r.status_code==200,r.text
            checks.append(format+'_round_trip')
        bad=client.post(f"/api/v1/suites/{suite['id']}/import",headers=auth,json={'content':json.dumps([draft,{}]),'format':'json','expected_revision':4})
        assert bad.status_code==422
        assert client.get('/api/v1/cases',headers=auth,params={'suite_id':suite['id']}).json()['total']==4
        checks+=['atomic_import_rollback']
        versions=client.get(f"/api/v1/suites/{suite['id']}/versions",headers=auth).json()['items']
        assert [len(v['snapshot']['cases']) for v in versions]==[4,2,1,0]
        checks+=['immutable_suite_versions']
        if not settings.llm_api_key.get_secret_value():
            run=client.post('/api/v1/generation-runs',headers=auth,json={'project_id':project['id'],'requirements':'测试普通问候功能','types':['functional'],'count':1}).json()
            assert run['error_code']=='model_not_configured' and run['result'] is None
            checks+=['missing_model_audit']
        unicode_suite=client.post('/api/v1/suites',headers=auth,json={'project_id':project['id'],'name':'Unicode 容量验收'}).json()
        unicode_case=client.post('/api/v1/cases',headers=auth,params={'expected_revision':1},json={**draft,'user_input':'\U0001f600'*20000,'suite_id':unicode_suite['id']})
        assert unicode_case.status_code==201,unicode_case.text[:200]
    with TestClient(create_app(settings)) as client:
        rows=client.get('/api/v1/cases',headers=auth,params={'suite_id':suite['id']}).json()
        assert rows['total']==4
        assert all(r['user_input']==draft['user_input'] for r in rows['items'])
        checks+=['fresh_app_persistence']
        unicode_rows=client.get('/api/v1/cases',headers=auth,params={'suite_id':unicode_suite['id']}).json()['items']
        assert unicode_rows[0]['user_input']=='\U0001f600'*20000
        checks+=['unicode_20000_char_persistence']
    engine=make_engine(settings.database_url.get_secret_value())
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='generation_runs' AND COLUMN_NAME='raw_response'"))=='mediumtext'
        assert conn.scalar(text('SELECT COUNT(*) FROM test_suite_versions WHERE suite_id=:id'),{'id':suite['id']})==4
        checks+=['response_column_capacity','database_snapshot_count']
    engine.dispose()
    print(json.dumps({'status':'passed','count':len(checks),'checks':checks,'real_model_test':'not_run_no_credentials','retained_test_username':username},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
