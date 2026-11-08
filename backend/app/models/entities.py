"""业务表映射：外键维护关联；配置凭证及演示载荷加密保存。"""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, JSON, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.mysql import MEDIUMTEXT


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class User(Record, Base):
    __tablename__ = 'users'
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default='tester')


class Project(Record, Base):
    __tablename__ = 'projects'
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default='')
    business_type: Mapped[str] = mapped_column(String(50), default='通用助手')


class Agent(Record, Base):
    __tablename__ = 'agents'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict] = mapped_column(JSON)
    secret: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)


class AgentVersion(Record, Base):
    __tablename__ = 'agent_versions'
    __table_args__ = (UniqueConstraint('agent_id', 'version'),)
    agent_id: Mapped[str] = mapped_column(ForeignKey('agents.id', ondelete='CASCADE'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    secret: Mapped[str] = mapped_column(Text)


class OperationLog(Record, Base):
    __tablename__ = 'operation_logs'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    action: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(36))
    request_id: Mapped[str] = mapped_column(String(36))


class TestSuite(Record, Base):
    __tablename__ = 'test_suites'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default='')
    revision: Mapped[int] = mapped_column(Integer, default=1)


class TestSuiteVersion(Record, Base):
    __tablename__ = 'test_suite_versions'
    __table_args__ = (UniqueConstraint('suite_id', 'revision'),)
    suite_id: Mapped[str] = mapped_column(ForeignKey('test_suites.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)


class ModelConfig(Record, Base):
    __tablename__ = 'model_configs'
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    name: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(String(30))
    config: Mapped[dict] = mapped_column(JSON)
    secret: Mapped[str] = mapped_column(Text)


class GenerationRun(Record, Base):
    __tablename__ = 'generation_runs'
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    model_config_id: Mapped[str | None] = mapped_column(ForeignKey('model_configs.id', ondelete='SET NULL'), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default='generating')
    request_data: Mapped[dict] = mapped_column(JSON)
    model_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text().with_variant(MEDIUMTEXT(), 'mysql'), nullable=True)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    saved_indexes: Mapped[list] = mapped_column(JSON, default=list)


class TestCase(Record, Base):
    __tablename__ = 'test_cases'
    suite_id: Mapped[str] = mapped_column(ForeignKey('test_suites.id'), index=True)
    name: Mapped[str] = mapped_column(String(160))
    test_type: Mapped[str] = mapped_column(String(30), index=True)
    scenario: Mapped[str] = mapped_column(Text)
    preconditions: Mapped[str] = mapped_column(Text, default='')
    user_input: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT(),'mysql'))
    history: Mapped[list] = mapped_column(JSON, default=list)
    expected_behavior: Mapped[str] = mapped_column(Text)
    expected_result: Mapped[str] = mapped_column(Text)
    rules: Mapped[dict] = mapped_column(JSON)
    priority: Mapped[str] = mapped_column(String(5))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(10), default='manual')
    generation_run_id: Mapped[str | None] = mapped_column(ForeignKey('generation_runs.id'), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class DemoRun(Record, Base):
    __tablename__ = 'demo_runs'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(30))
    model_snapshot: Mapped[dict] = mapped_column(JSON)
    payload: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT(), 'mysql'))


# 导入扩展表以供 Alembic 和测试统一读取完整 metadata。
from app.models import platform  # noqa: E402,F401
