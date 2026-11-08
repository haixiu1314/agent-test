import asyncio
from typing import Literal
from fastapi import APIRouter,Depends,Request,HTTPException
from pydantic import Field
from sqlalchemy import select
from app.api.v1.routes import database,current_user
from app.api.v1.cases import audit
from app.schemas.inputs import Input
from app.schemas.cases import Message
from app.models.entities import DemoRun
from app.services.catalog import project_for_user
from app.services.models import resolve_model
from app.services.demo import chat

class DemoInput(Input):
    project_id:str
    model_config_id:str|None=None
    knowledge_base_id:str|None=None
    input:str=Field(min_length=1,max_length=10000)
    history:list[Message]=Field(default_factory=list,max_length=30)
    defect:Literal['none','wrong_tool_description','missing_knowledge','conflicting_knowledge','bad_prompt','tool_timeout']='none'

router=APIRouter(prefix='/api/v1/demo',tags=['demo'])

@router.post('/chat')
async def demo_chat(body:DemoInput,request:Request,user=Depends(current_user),db=Depends(database)):
    project_for_user(db,body.project_id,user)
    retriever=None
    if body.knowledge_base_id:
        from app.services.rag import kb_for_user, make_retriever
        kb=kb_for_user(db,body.knowledge_base_id,user)
        if kb.project_id!=body.project_id:raise HTTPException(422,'知识库必须属于所选项目')
        retriever=make_retriever(request.app,kb.id)
    config,key=resolve_model(db,request.app.state.settings,request.app.state.vault,body.model_config_id,'demo',user_id=user.id)
    if request.app.state.model_busy:raise HTTPException(429,'模型正在处理请求')
    request.app.state.model_busy=True
    run=DemoRun(project_id=body.project_id,owner_id=user.id,model_snapshot=config,
                payload=request.app.state.vault.encrypt({'request':body.model_dump(mode='json')}),status='running')
    db.add(run);db.flush();audit(db,user,request,'demo.started',run.id)
    try:
        result=await asyncio.wait_for(chat(config,key,body,retriever) if retriever else chat(config,key,body),timeout=120)
        run.payload=request.app.state.vault.encrypt({'request':body.model_dump(mode='json'),'result':result})
        run.status='completed'
    except BaseException as exc:
        run.status='failed'
        audit(db,user,request,'demo.failed',run.id)
        if isinstance(exc,asyncio.CancelledError):raise
        raise HTTPException(502,'演示模型调用失败或超过工具/时间上限，请查看运行记录') from None
    finally:request.app.state.model_busy=False
    audit(db,user,request,'demo.completed',run.id)
    return {'id':run.id,**result,'knowledge_mode':'真实 Milvus 检索' if retriever else '本地样例关键词检索，未选择 Milvus 知识库'}

@router.get('/runs')
def runs(project_id:str,request:Request,user=Depends(current_user),db=Depends(database)):
    project_for_user(db,project_id,user)
    rows=db.scalars(select(DemoRun).where(DemoRun.project_id==project_id).order_by(DemoRun.created_at.desc()).limit(30))
    return {'items':[{'id':r.id,'status':r.status,'model_snapshot':r.model_snapshot,'created_at':r.created_at,
                      **request.app.state.vault.decrypt(r.payload)} for r in rows]}
