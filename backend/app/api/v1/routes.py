import time
from collections import defaultdict, deque
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
import jwt
from app.models.entities import User, Project, Agent, AgentVersion, OperationLog, TestSuite, GenerationRun, DemoRun
from app.schemas.inputs import Credentials, ProjectInput, AgentInput, ConnectionInput
from app.schemas.outputs import Page, UserPublic, TokenPublic, ProjectPublic, AgentPublic, VersionPublic, ConnectionPublic
from app.core.security import hash_password, verify_password, issue_token, read_token
from app.services.catalog import (project_for_user, agent_for_user, log_operation,
    project_dict, agent_dict, paginate, snapshot_agent)
from app.adapters.http import HttpAgentAdapter
from app.adapters.local import local_adapter
from app.adapters.base import AdapterError

router = APIRouter(prefix='/api/v1')
bearer = HTTPBearer(auto_error=False)


def database(request: Request):
    with request.app.state.sessions() as db:
        yield db


def current_user(request: Request, auth: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(database)):
    if not auth:
        raise HTTPException(401, '请先登录', headers={'WWW-Authenticate': 'Bearer'})
    try:
        user = db.get(User, read_token(auth.credentials, request.app.state.settings.jwt_secret_key.get_secret_value()))
    except (jwt.PyJWTError, ValueError, TypeError):
        user = None
    if not user:
        raise HTTPException(401, '登录已失效，请重新登录')
    return user


def admin(user=Depends(current_user)):
    if user.role != 'admin':
        raise HTTPException(403, '需要管理员权限')
    return user


def auth_limit(request: Request):
    """开发单进程限流；部署多 worker 前必须替换为共享存储限流。"""
    limits = request.app.state.auth_limits
    key = request.client.host if request.client else 'unknown'
    now = time.monotonic()
    # 限制最多保留 5000 个来源，防止无界增长。
    if key not in limits and len(limits) >= 5000:
        limits.clear()
    bucket = limits[key]
    while bucket and bucket[0] < now - 60:
        bucket.popleft()
    if len(bucket) >= 15:
        raise HTTPException(429, '操作过于频繁，请一分钟后重试')
    bucket.append(now)


@router.post('/auth/register', status_code=201, dependencies=[Depends(auth_limit)], response_model=UserPublic)
def register(body: Credentials, request: Request, db=Depends(database)):
    user = User(username=body.username.lower(), password_hash=hash_password(body.password.get_secret_value()), role='tester')
    db.add(user)
    try:
        db.flush()
        log_operation(db, user, 'auth.register', user.id, request.state.request_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '用户名已存在') from None
    return {'id': user.id, 'username': user.username, 'role': user.role}


@router.post('/auth/login', dependencies=[Depends(auth_limit)], response_model=TokenPublic)
def login(body: Credentials, request: Request, db=Depends(database)):
    user = db.scalar(select(User).where(User.username == body.username.lower()))
    stored = user.password_hash if user else request.app.state.dummy_hash
    valid = verify_password(body.password.get_secret_value(), stored)
    if not user or not valid:
        raise HTTPException(401, '用户名或密码错误')
    log_operation(db, user, 'auth.login', user.id, request.state.request_id)
    db.commit()
    return {'access_token': issue_token(user.id, request.app.state.settings.jwt_secret_key.get_secret_value()),
            'token_type': 'bearer', 'expires_in': 7200}


@router.get('/auth/me', response_model=UserPublic)
def me(user=Depends(current_user)):
    return {'id': user.id, 'username': user.username, 'role': user.role}


@router.get('/projects', response_model=Page[ProjectPublic])
def projects(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
             user=Depends(current_user), db=Depends(database)):
    statement = select(Project).order_by(Project.created_at.desc(), Project.id)
    if user.role != 'admin':
        statement = statement.where(Project.owner_id == user.id)
    rows, count = paginate(db, statement, page, page_size)
    return {'items': [project_dict(p) for p in rows], 'total': count, 'page': page, 'page_size': page_size}


@router.post('/projects', status_code=201, response_model=ProjectPublic)
def create_project(body: ProjectInput, request: Request, user=Depends(current_user), db=Depends(database)):
    project = Project(owner_id=user.id, **body.model_dump())
    db.add(project)
    db.flush()
    log_operation(db, user, 'project.create', project.id, request.state.request_id)
    db.commit()
    return project_dict(project)


@router.get('/projects/{project_id}', response_model=ProjectPublic)
def get_project(project_id: str, user=Depends(current_user), db=Depends(database)):
    return project_dict(project_for_user(db, project_id, user))


@router.put('/projects/{project_id}', response_model=ProjectPublic)
def update_project(project_id: str, body: ProjectInput, request: Request, user=Depends(current_user), db=Depends(database)):
    item = project_for_user(db, project_id, user)
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    log_operation(db, user, 'project.update', item.id, request.state.request_id)
    db.commit()
    return project_dict(item)


@router.delete('/projects/{project_id}', status_code=204)
def delete_project(project_id: str, request: Request, user=Depends(current_user), db=Depends(database)):
    item = project_for_user(db, project_id, user)
    from app.models.platform import TestTask,KnowledgeBase
    if db.scalar(select(TestTask.id).where(TestTask.project_id==item.id).limit(1)) or db.scalar(select(KnowledgeBase.id).where(KnowledgeBase.project_id==item.id).limit(1)):
        raise HTTPException(409,'项目仍有关联任务或知识库')
    if db.scalar(select(Agent.id).where(Agent.project_id == item.id).limit(1)):
        raise HTTPException(409, '请先删除项目关联的 Agent')
    if db.scalar(select(TestSuite.id).where(TestSuite.project_id == item.id).limit(1)) or db.scalar(select(GenerationRun.id).where(GenerationRun.project_id == item.id).limit(1)) or db.scalar(select(DemoRun.id).where(DemoRun.project_id == item.id).limit(1)):
        raise HTTPException(409, '项目仍有关联套件或生成审计记录，请保留项目以便追溯')
    log_operation(db, user, 'project.delete', item.id, request.state.request_id)
    db.delete(item)
    db.commit()


@router.get('/agents', response_model=Page[AgentPublic])
def agents(request: Request, project_id: str | None = None, page: int = Query(1, ge=1),
           page_size: int = Query(20, ge=1, le=100), user=Depends(current_user), db=Depends(database)):
    statement = select(Agent).join(Project).order_by(Agent.created_at.desc(), Agent.id)
    if user.role != 'admin':
        statement = statement.where(Project.owner_id == user.id)
    if project_id:
        project_for_user(db, project_id, user)
        statement = statement.where(Agent.project_id == project_id)
    rows, count = paginate(db, statement, page, page_size)
    return {'items': [agent_dict(a, request.app.state.vault) for a in rows], 'total': count, 'page': page, 'page_size': page_size}


def apply_agent(item, body, vault, creating=False):
    public = body.model_dump(exclude={'headers', 'api_key', 'project_id', 'name', 'kind', 'expected_version'})
    secrets = {} if creating else vault.decrypt(item.secret)
    # null 或未提交表示保留；空 dict / 空字符串表示明确清除。
    if body.headers is not None:
        secrets['headers'] = body.headers
    if body.api_key is not None:
        secrets['api_key'] = body.api_key.get_secret_value()
    item.name, item.kind, item.config = body.name, body.kind, public
    item.secret = vault.encrypt(secrets)


@router.post('/agents', status_code=201, response_model=AgentPublic)
def create_agent(body: AgentInput, request: Request, user=Depends(current_user), db=Depends(database)):
    project_for_user(db, body.project_id, user)
    agent = Agent(project_id=body.project_id, version=1)
    apply_agent(agent, body, request.app.state.vault, creating=True)
    db.add(agent)
    db.flush()
    snapshot_agent(db, agent, request.app.state.vault)
    log_operation(db, user, 'agent.create', agent.id, request.state.request_id)
    db.commit()
    return agent_dict(agent, request.app.state.vault)


@router.get('/agents/{agent_id}', response_model=AgentPublic)
def get_agent(agent_id: str, request: Request, user=Depends(current_user), db=Depends(database)):
    return agent_dict(agent_for_user(db, agent_id, user), request.app.state.vault)


@router.put('/agents/{agent_id}', response_model=AgentPublic)
def update_agent(agent_id: str, body: AgentInput, request: Request, user=Depends(current_user), db=Depends(database)):
    agent = agent_for_user(db, agent_id, user, lock=True)
    if body.project_id != agent.project_id:
        raise HTTPException(422, '不允许通过更新移动 Agent 所属项目')
    if body.expected_version is None or body.expected_version != agent.version:
        raise HTTPException(409, '配置版本已变化，请刷新后重试')
    apply_agent(agent, body, request.app.state.vault)
    agent.version += 1
    db.flush()
    snapshot_agent(db, agent, request.app.state.vault)
    log_operation(db, user, 'agent.update', agent.id, request.state.request_id)
    db.commit()
    return agent_dict(agent, request.app.state.vault)


@router.delete('/agents/{agent_id}', status_code=204)
def delete_agent(agent_id: str, request: Request, user=Depends(current_user), db=Depends(database)):
    agent = agent_for_user(db, agent_id, user, lock=True)
    from app.models.platform import TestTask
    if db.scalar(select(TestTask.id).where(TestTask.agent_id==agent_id).limit(1)):
        raise HTTPException(409,'Agent 已有关联任务，请保留历史版本')
    db.execute(delete(AgentVersion).where(AgentVersion.agent_id == agent.id))
    log_operation(db, user, 'agent.delete', agent.id, request.state.request_id)
    db.delete(agent)
    db.commit()


@router.get('/agents/{agent_id}/versions', response_model=Page[VersionPublic])
def versions(agent_id: str, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
             user=Depends(current_user), db=Depends(database)):
    agent_for_user(db, agent_id, user)
    rows, count = paginate(db, select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc()), page, page_size)
    return {'items': [{'id': r.id, 'version': r.version, 'snapshot': r.snapshot, 'created_at': r.created_at} for r in rows],
            'total': count, 'page': page, 'page_size': page_size}


@router.post('/agents/{agent_id}/test-connection', response_model=ConnectionPublic)
async def connection(agent_id: str, body: ConnectionInput, request: Request, user=Depends(current_user), db=Depends(database)):
    item = agent_for_user(db, agent_id, user)
    config, secrets = dict(item.config), request.app.state.vault.decrypt(item.secret)
    started = time.perf_counter()
    success, error = True, None
    try:
        if item.kind=='http':adapter=HttpAgentAdapter(config,secrets)
        elif config['adapter_name']=='enterprise_demo':
            from app.services.models import resolve_model
            from app.adapters.enterprise import EnterpriseAdapter
            model,key=resolve_model(db,request.app.state.settings,request.app.state.vault,purpose='demo')
            adapter=EnterpriseAdapter(model,key)
        else:adapter=local_adapter(config['adapter_name'])
        result = await adapter.invoke(body.input, body.history)
    except AdapterError as exc:
        success, error, result = False, exc.code, None
    duration = round((time.perf_counter() - started) * 1000, 2)
    log_operation(db, user, 'agent.connection.ok' if success else 'agent.connection.failed', item.id, request.state.request_id)
    db.commit()
    # 不回显上游回答：它可能含敏感数据；后续执行任务会实现有权限控制的结果存储。
    return {'success': success, 'error_code': error, 'duration_ms': duration,
            'status_code': result.status_code if result else None, 'attempts': result.attempts if result else None,
            'output_received': bool(result is not None), 'tool_events': '不可观测', 'request_id': request.state.request_id}


@router.get('/system/operation-logs')
def operation_logs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   user=Depends(admin), db=Depends(database)):
    rows, count = paginate(db, select(OperationLog).order_by(OperationLog.created_at.desc()), page, page_size)
    return {'items': [{'id': r.id, 'action': r.action, 'resource_id': r.resource_id, 'user_id': r.user_id,
                       'request_id': r.request_id, 'created_at': r.created_at} for r in rows], 'total': count}
