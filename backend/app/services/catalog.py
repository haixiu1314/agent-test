"""统一授权与序列化；修改和审计记录在同一数据库事务提交。"""
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models.entities import Project, Agent, AgentVersion, OperationLog


def project_for_user(db, project_id, user):
    project = db.get(Project, project_id)
    if not project or (project.owner_id != user.id and user.role != 'admin'):
        raise HTTPException(404, '项目不存在')
    return project


def agent_for_user(db, agent_id, user, lock=False):
    statement = select(Agent).where(Agent.id == agent_id)
    if lock:
        statement = statement.with_for_update()
    agent = db.scalar(statement)
    if not agent:
        raise HTTPException(404, 'Agent 不存在')
    project_for_user(db, agent.project_id, user)
    return agent


def log_operation(db, user, action, resource_id, request_id):
    db.add(OperationLog(user_id=user.id, action=action, resource_id=resource_id, request_id=request_id))


def project_dict(item):
    return {key: getattr(item, key) for key in ['id', 'name', 'description', 'business_type', 'created_at', 'updated_at']}


def agent_dict(item, vault):
    secret = vault.decrypt(item.secret)
    return {'id': item.id, 'project_id': item.project_id, 'name': item.name, 'kind': item.kind,
            **item.config, 'version': item.version, 'has_api_key': bool(secret.get('api_key')),
            'header_names': sorted((secret.get('headers') or {}).keys()),
            'created_at': item.created_at, 'updated_at': item.updated_at}


def paginate(db, statement, page, page_size):
    count = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    return db.scalars(statement.offset((page - 1) * page_size).limit(page_size)).all(), count


def snapshot_agent(db, agent, vault):
    """版本包含公开配置快照及独立密文，不向版本查询接口暴露密文。"""
    snapshot = agent_dict(agent, vault)
    snapshot.pop('created_at', None)
    snapshot.pop('updated_at', None)
    db.add(AgentVersion(agent_id=agent.id, version=agent.version, snapshot=snapshot, secret=agent.secret))
