"""结构化模型响应为显式测试替身；不计为真实 AI 验收。"""
import json
import pytest
from types import SimpleNamespace
from sqlalchemy import select
from conftest import authenticate
from app.models.entities import User,ModelConfig,GenerationRun,DemoRun
from app.services.demo import calculate,execute_tool

DRAFT={'name':'有效问候','test_type':'functional','scenario':'普通问候', 'user_input':'你好',
       'expected_behavior':'礼貌回应','expected_result':'包含问候',
       'rules':{'evaluators':['rules'],'rubric':'包含礼貌问候','must_include':['你好']}}

@pytest.fixture
def suite(client,auth,project):
    r=client.post('/api/v1/suites',headers=auth,json={'project_id':project['id'],'name':'测试套件'})
    assert r.status_code==201,r.text
    return r.json()

def create(client,auth,suite,draft=None,revision=1):
    return client.post('/api/v1/cases',params={'expected_revision':revision},headers=auth,json={**(draft or DRAFT),'suite_id':suite['id']})

def test_case_lifecycle_versions(client,auth,suite):
    item=create(client,auth,suite).json()
    assert item['source']=='manual'
    assert create(client,auth,suite).status_code==409
    updated=client.put('/api/v1/cases/'+item['id'],headers=auth,json={**DRAFT,'name':'已修改','expected_revision':1})
    assert updated.status_code==200,updated.text
    assert updated.json()['revision']==2
    assert client.put('/api/v1/cases/'+item['id'],headers=auth,json={**DRAFT,'expected_revision':1}).status_code==409
    versions=client.get(f"/api/v1/suites/{suite['id']}/versions",headers=auth).json()['items']
    assert [v['revision'] for v in versions]==[3,2,1]
    assert versions[1]['snapshot']['cases'][0]['name']=='有效问候'
    assert client.delete('/api/v1/cases/'+item['id'],headers=auth,params={'expected_revision':1}).status_code==409
    assert client.delete('/api/v1/cases/'+item['id'],headers=auth,params={'expected_revision':2}).status_code==204

def test_ownership(client,auth,suite,project):
    other=authenticate(client,'other_case_tester')
    assert client.get('/api/v1/suites',headers=other,params={'project_id':project['id']}).status_code==404
    assert client.get('/api/v1/cases',headers=other,params={'suite_id':suite['id']}).status_code==404
    assert create(client,other,suite).status_code==404
    assert client.get(f"/api/v1/suites/{suite['id']}/export",headers=other).status_code==404

@pytest.mark.parametrize('format',['json','csv'])
def test_import_round_trip_atomic(client,auth,suite,format):
    draft={**DRAFT,'name':'=HYPERLINK("bad")','user_input':'多行\n含逗号,引号"与中文'}
    assert create(client,auth,suite,draft).status_code==201
    url=f"/api/v1/suites/{suite['id']}"
    exported=client.get(url+'/export',headers=auth,params={'format':format}).json()['content']
    r=client.post(url+'/import',headers=auth,json={'format':format,'content':exported,'expected_revision':2})
    assert r.status_code==200,r.text
    assert r.json()['imported']==1
    rows=client.get('/api/v1/cases',headers=auth,params={'suite_id':suite['id']}).json()['items']
    assert len(rows)==2 and all(c['user_input']==draft['user_input'] for c in rows)
    bad=json.dumps([DRAFT,{**DRAFT,'name':''}])
    assert client.post(url+'/import',headers=auth,json={'format':'json','content':bad,'expected_revision':3}).status_code==422
    assert client.get('/api/v1/cases',headers=auth,params={'suite_id':suite['id']}).json()['total']==2

@pytest.mark.parametrize('type',['tool','memory','security','rag'])
def test_type_requires_evidence(client,auth,suite,type):
    assert create(client,auth,suite,{**DRAFT,'test_type':type}).status_code==422

def test_sources_cannot_be_forged(client,auth,suite):
    assert create(client,auth,suite,{**DRAFT,'source':'ai'}).status_code==422

def test_project_and_suite_delete(client,auth,suite,project):
    assert client.delete('/api/v1/projects/'+project['id'],headers=auth).status_code==409
    assert client.delete('/api/v1/suites/'+suite['id'],headers=auth,params={'expected_revision':1}).status_code==204
    assert client.delete('/api/v1/projects/'+project['id'],headers=auth).status_code==204

def model_setup(application,client,auth):
    assert client.post('/api/v1/models',headers=auth,json={}).status_code==422
    data={'name':'fixture model','base_url':'http://fixture.invalid/v1','model':'fixture-only','api_key':'fixture-secret'}
    r=client.post('/api/v1/models',headers=auth,json=data)
    assert r.status_code==201,r.text
    assert 'fixture-secret' not in r.text
    with application.state.sessions() as db:
        assert 'fixture-secret' not in db.get(ModelConfig,r.json()['id']).secret
    return r.json()['id']

def test_missing_model_is_audited(client,auth,project):
    r=client.post('/api/v1/generation-runs',headers=auth,json={'project_id':project['id'],'requirements':'测试问候场景','types':['functional'],'count':1})
    assert r.status_code==201,r.text
    assert r.json()['error_code']=='model_not_configured'
    assert r.json()['result'] is None
    assert client.post('/api/v1/demo/chat',headers=auth,json={'project_id':project['id'],'input':'你好'}).status_code==409

def test_generation_review_save_fixture(application,client,auth,project,suite,monkeypatch):
    model=model_setup(application,client,auth)
    async def fixture(*args,**kwargs):return SimpleNamespace(content=json.dumps({'capability_analysis':'测试替身分析','risks':[],'cases':[DRAFT]}),usage_metadata={'output_tokens':50})
    monkeypatch.setattr('app.api.v1.generation.invoke',fixture)
    r=client.post('/api/v1/generation-runs',headers=auth,json={'project_id':project['id'],'model_config_id':model,'requirements':'测试问候场景','types':['functional'],'count':1})
    assert r.status_code==201,r.text
    run=r.json();assert run['status']=='review'
    assert client.get('/api/v1/cases',headers=auth,params={'suite_id':suite['id']}).json()['total']==0
    save={'suite_id':suite['id'],'expected_revision':1,'indexes':[0],'cases':[{**DRAFT,'name':'审阅后名称'}]}
    assert client.post(f"/api/v1/generation-runs/{run['id']}/save",headers=auth,json={**save,'indexes':[1]}).status_code==422
    assert client.post(f"/api/v1/generation-runs/{run['id']}/save",headers=auth,json=save).status_code==200
    assert client.post(f"/api/v1/generation-runs/{run['id']}/save",headers=auth,json=save).status_code==409
    item=client.get('/api/v1/cases',headers=auth,params={'suite_id':suite['id']}).json()['items'][0]
    assert item['source']=='ai' and item['generation_run_id']==run['id']
    other=authenticate(client,'generation_other')
    assert client.get('/api/v1/generation-runs/'+run['id'],headers=other).status_code==404
    with application.state.sessions() as db:
        raw=db.get(GenerationRun,run['id']).raw_response
        assert '测试替身分析' not in raw

@pytest.mark.parametrize('response',['not-json',json.dumps({'capability_analysis':'fixture','risks':[],'cases':[DRAFT,DRAFT]})])
def test_invalid_model_output(application,client,auth,project,monkeypatch,response):
    model=model_setup(application,client,auth)
    async def fixture(*args,**kwargs):return SimpleNamespace(content=response,usage_metadata=None)
    monkeypatch.setattr('app.api.v1.generation.invoke',fixture)
    run=client.post('/api/v1/generation-runs',headers=auth,json={'project_id':project['id'],'model_config_id':model,'requirements':'测试问候场景','types':['functional'],'count':1}).json()
    assert run['status']=='failed' and run['error_code']=='invalid_structured_output'
    assert not application.state.model_busy

@pytest.mark.parametrize('expression',['__import__("os")','2**10000','a+1','1/0','9'*121])
def test_calculator_rejects_code(expression):
    with pytest.raises((ValueError,ZeroDivisionError)):calculate(expression)

def test_controlled_tools():
    assert calculate('(125+75)/4')==50
    assert execute_tool('weather',{'city':'北京'},'none')['simulated']
    assert execute_tool('calculator',{'expression':'1+1'},'tool_timeout')['error']=='simulated_timeout'
    assert execute_tool('knowledge_search',{'query':'年假'},'missing_knowledge')['snippets']==[]
    assert len(execute_tool('knowledge_search',{'query':'年假'},'conflicting_knowledge')['snippets'])==2

def test_demo_fixture_tool_events(application,client,auth,project,monkeypatch):
    model=model_setup(application,client,auth)
    with application.state.sessions() as db:db.get(ModelConfig,model).purpose='demo';db.commit()
    from langchain_core.messages import AIMessage
    responses=iter([AIMessage(content='',tool_calls=[{'name':'calculator','args':{'expression':'2+3'},'id':'fixture-call'}]),AIMessage(content='测试替身回答：5')])
    async def fixture(*args,**kwargs):return next(responses)
    monkeypatch.setattr('app.services.demo.invoke',fixture)
    r=client.post('/api/v1/demo/chat',headers=auth,json={'project_id':project['id'],'model_config_id':model,'input':'2+3'})
    assert r.status_code==200,r.text
    tool_result=next(e for e in r.json()['events'] if e['type']=='tool_result')
    assert tool_result['result']['value']==5
    with application.state.sessions() as db:assert '测试替身回答' not in db.get(DemoRun,r.json()['id']).payload
    other=authenticate(client,'demo_other')
    assert client.get('/api/v1/demo/runs',headers=other,params={'project_id':project['id']}).status_code==404


def test_provider_error_is_sanitized(application,client,auth,project,monkeypatch):
    model=model_setup(application,client,auth)
    async def fixture(*args,**kwargs):raise RuntimeError('fixture-secret upstream private content')
    monkeypatch.setattr('app.api.v1.generation.invoke',fixture)
    r=client.post('/api/v1/generation-runs',headers=auth,json={'project_id':project['id'],'model_config_id':model,'requirements':'测试错误处理路径','types':['functional'],'count':1})
    assert r.json()['error_code']=='model_call_failed'
    assert 'fixture-secret' not in r.text and not application.state.model_busy


def test_demo_failure_is_persisted(application,client,auth,project,monkeypatch):
    model=model_setup(application,client,auth)
    with application.state.sessions() as db:db.get(ModelConfig,model).purpose='demo';db.commit()
    async def fixture(*args,**kwargs):raise TimeoutError('fixture-secret')
    monkeypatch.setattr('app.services.demo.invoke',fixture)
    r=client.post('/api/v1/demo/chat',headers=auth,json={'project_id':project['id'],'model_config_id':model,'input':'失败实验'})
    assert r.status_code==502 and 'fixture-secret' not in r.text
    assert not application.state.model_busy
    rows=client.get('/api/v1/demo/runs',headers=auth,params={'project_id':project['id']}).json()['items']
    assert rows[0]['status']=='failed' and 'result' not in rows[0]


def test_model_update_preserves_key(application,client,auth):
    model=model_setup(application,client,auth)
    data={'name':'renamed','base_url':'http://fixture.invalid/v1','model':'fixture-only'}
    r=client.put('/api/v1/models/'+model,headers=auth,json=data)
    assert r.json()['has_api_key'] and 'fixture-secret' not in r.text
    assert client.put('/api/v1/models/'+model,headers=auth,json={**data,'base_url':'https://name:secret@example.com/v1'}).status_code==422


def test_duplicate_save_indexes(application,client,auth,project,suite):
    with application.state.sessions() as db:
        owner=db.scalar(select(User))
        run=GenerationRun(owner_id=owner.id,project_id=project['id'],status='review',request_data={},result={'cases':[DRAFT,DRAFT]})
        db.add(run);db.commit();run_id=run.id
    r=client.post(f'/api/v1/generation-runs/{run_id}/save',headers=auth,json={'suite_id':suite['id'],'expected_revision':1,'indexes':[0,0],'cases':[DRAFT,DRAFT]})
    assert r.status_code==422
    assert client.get('/api/v1/cases',headers=auth,params={'suite_id':suite['id']}).json()['total']==0


def test_documented_manual_examples():
    from pathlib import Path
    from app.schemas.cases import CaseDraft
    examples=json.loads((Path(__file__).resolve().parents[2]/'docs/examples/人工用例模板.json').read_text(encoding='utf-8'))
    assert len(examples)==4
    for row in examples:CaseDraft.model_validate(row)
