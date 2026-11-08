"""用户配置密钥后执行的真实 AI 验收；无密钥返回阻塞，不使用替身。会消耗模型额度。"""
import json
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings

def main():
    settings=Settings()
    if not all([settings.llm_api_key.get_secret_value(),settings.llm_base_url,settings.llm_model]):
        print(json.dumps({'status':'blocked','reason':'LLM configuration missing','real_model_calls':0}))
        return 2
    checks=[]
    with TestClient(create_app(settings)) as client:
        credentials={'username':'real_model_'+uuid4().hex[:12],'password':uuid4().hex+'Aa1!'}
        assert client.post('/api/v1/auth/register',json=credentials).status_code==201
        auth={'Authorization':'Bearer '+client.post('/api/v1/auth/login',json=credentials).json()['access_token']}
        project=client.post('/api/v1/projects',headers=auth,json={'name':'真实模型验收（实际调用）'}).json()
        suite=client.post('/api/v1/suites',headers=auth,json={'project_id':project['id'],'name':'AI 审阅保存验收'}).json()
        types=['functional','boundary','planning','memory','tool','rag','security','exception']
        response=client.post('/api/v1/generation-runs',headers=auth,json={'project_id':project['id'],
            'requirements':'测试企业知识助手：制度问答引用来源、计算器、模拟天气、多轮记忆、任务规划，拒绝泄密，未知知识说明无依据。',
            'tools':[{'name':'calculator','arguments':{'expression':'string'}},{'name':'weather','arguments':{'city':'string'}}],
            'types':types,'count':8})
        run=response.json()
        if response.status_code!=201 or run.get('status')!='review':
            print(json.dumps({'status':'failed','step':'generation','error_code':run.get('error_code','request_failed'),'run_id':run.get('id')}));return 1
        checks+=['real_generation','all_eight_types','structured_schema_validation']
        save=client.post('/api/v1/generation-runs/'+run['id']+'/save',headers=auth,json={'suite_id':suite['id'],'expected_revision':1,'indexes':list(range(8)),'cases':run['result']['cases']})
        assert save.status_code==200
        checks+=['review_save_association']
        demo=client.post('/api/v1/demo/chat',headers=auth,json={'project_id':project['id'],'input':'请必须调用 calculator 计算 (125+75)/4，然后依据工具结果回答。'})
        if demo.status_code!=200:
            print(json.dumps({'status':'failed','step':'demo','run_id':run['id']}));return 1
        result=demo.json()
        assert any(e.get('type')=='tool_result' and e.get('name')=='calculator' and e.get('success') and e.get('result',{}).get('value')==50 for e in result['events'])
        assert result['output'].strip()
        checks+=['real_demo_model','observable_calculator_execution']
        print(json.dumps({'status':'passed','count':len(checks),'checks':checks,'generation_run_id':run['id'],'demo_run_id':result['id'],
                          'note':'仅本次样本通过，不代表模型质量、安全或所有缺陷场景通过'},ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
