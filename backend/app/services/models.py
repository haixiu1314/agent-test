"""模型访问统一入口：无自动模拟降级，不向客户端返回供应商异常原文。"""
import asyncio
from fastapi import HTTPException
from langchain_openai import ChatOpenAI
from app.models.entities import ModelConfig


def owned_model(db, model_id, user_id):
    """配置和密钥属于创建者；管理员也不能引用别人的个人模型密钥。"""
    item = db.get(ModelConfig, model_id)
    if not item or item.created_by != user_id:
        raise HTTPException(404, '模型配置不存在')
    return item


def resolve_model(db, settings, vault, model_id=None, purpose='generation', *, user_id=None):
    if model_id:
        item=owned_model(db, model_id, user_id)
        if item.purpose!=purpose:raise HTTPException(422,'模型用途不匹配')
        config=dict(item.config)
        key=vault.decrypt(item.secret).get('api_key','')
    else:
        config={'base_url':settings.llm_base_url,'model':settings.llm_model,
                'temperature':0,'timeout_seconds':settings.llm_timeout_seconds,'max_tokens':12000}
        key=settings.llm_api_key.get_secret_value()
    if not key or not config.get('model') or not config.get('base_url'):
        raise HTTPException(409,'模型尚未配置：请在模型配置中添加自己的模型，或填写本地 .env 的 LLM_*')
    return config,key


async def invoke(config,key,messages,tools=None):
    model=ChatOpenAI(api_key=key,base_url=config['base_url'],model=config['model'],
        temperature=config['temperature'],timeout=config['timeout_seconds'],max_retries=0,
        max_tokens=config['max_tokens'])
    if tools:model=model.bind_tools(tools)
    return await asyncio.wait_for(model.ainvoke(messages),timeout=config['timeout_seconds']+2)


def resolve_embedding(db,settings,vault,model_id=None, *, user_id=None):
    if model_id:return resolve_model(db,settings,vault,model_id,'embedding',user_id=user_id)
    if not settings.embedding_model or not settings.llm_api_key.get_secret_value() or not settings.llm_base_url:
        raise HTTPException(409,'未配置 embedding 模型')
    return {'base_url':settings.llm_base_url,'model':settings.embedding_model,'timeout_seconds':settings.llm_timeout_seconds},settings.llm_api_key.get_secret_value()
