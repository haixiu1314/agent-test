"""任务、评估、轨迹、知识与报告分表持久化。"""
from sqlalchemy import String, Text, Integer, Float, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from app.models.entities import Base, Record

LONG = Text().with_variant(MEDIUMTEXT(), 'mysql')


class TestTask(Record, Base):
    __tablename__ = 'test_tasks'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey('agents.id'), index=True)
    suite_id: Mapped[str] = mapped_column(ForeignKey('test_suites.id'))
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default='pending', index=True)
    kind: Mapped[str] = mapped_column(String(20), default='quality')
    config: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[dict] = mapped_column(JSON)
    secrets: Mapped[str] = mapped_column(LONG)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class TestResult(Record, Base):
    __tablename__ = 'test_results'
    __table_args__ = (UniqueConstraint('task_id','case_key'),)
    task_id: Mapped[str] = mapped_column(ForeignKey('test_tasks.id'), index=True)
    case_key: Mapped[str] = mapped_column(String(36))
    case_name: Mapped[str] = mapped_column(String(160))
    test_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default='pending')
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[str] = mapped_column(LONG)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)


class EvaluationDetail(Record, Base):
    __tablename__ = 'evaluation_details'
    result_id: Mapped[str] = mapped_column(ForeignKey('test_results.id'), index=True)
    evaluator: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON)


class TraceEvent(Record, Base):
    __tablename__ = 'trace_events'
    task_id: Mapped[str] = mapped_column(ForeignKey('test_tasks.id'), index=True)
    result_id: Mapped[str] = mapped_column(ForeignKey('test_results.id'), index=True)
    parent_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50))
    event_name: Mapped[str] = mapped_column(String(160))
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    payload: Mapped[str] = mapped_column(LONG)


class KnowledgeBase(Record, Base):
    __tablename__ = 'knowledge_bases'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default='')
    config: Mapped[dict] = mapped_column(JSON)
    secrets: Mapped[str] = mapped_column(LONG)
    status: Mapped[str] = mapped_column(String(30), default='active')


class RagDocument(Record, Base):
    __tablename__ = 'rag_documents'
    kb_id: Mapped[str] = mapped_column(ForeignKey('knowledge_bases.id'), index=True)
    name: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(30), default='parsed')
    content_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(LONG)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class RagChunk(Record, Base):
    __tablename__ = 'rag_chunks'
    kb_id: Mapped[str] = mapped_column(ForeignKey('knowledge_bases.id'), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey('rag_documents.id'), index=True)
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    meta: Mapped[dict] = mapped_column(JSON)


class RagIssue(Record, Base):
    __tablename__ = 'rag_issues'
    kb_id: Mapped[str] = mapped_column(ForeignKey('knowledge_bases.id'), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey('rag_documents.id'), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20))
    detail: Mapped[dict] = mapped_column(JSON)
    confirmation: Mapped[str] = mapped_column(String(30), default='pending')


class RagEvaluation(Record, Base):
    __tablename__ = 'rag_evaluations'
    kb_id: Mapped[str] = mapped_column(ForeignKey('knowledge_bases.id'), index=True)
    status: Mapped[str] = mapped_column(String(30))
    config: Mapped[dict] = mapped_column(JSON)
    payload: Mapped[str] = mapped_column(LONG)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class RagDataset(Record, Base):
    __tablename__ = 'rag_datasets'
    kb_id: Mapped[str] = mapped_column(ForeignKey('knowledge_bases.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default='ready')
    source: Mapped[str] = mapped_column(String(20), default='manual')
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    payload: Mapped[str] = mapped_column(LONG)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class SecurityFinding(Record, Base):
    __tablename__ = 'security_findings'
    task_id: Mapped[str] = mapped_column(ForeignKey('test_tasks.id'), index=True)
    result_id: Mapped[str] = mapped_column(ForeignKey('test_results.id'), index=True)
    category: Mapped[str] = mapped_column(String(60))
    risk: Mapped[str] = mapped_column(String(20))
    violated: Mapped[str] = mapped_column(String(20))
    detail: Mapped[dict] = mapped_column(JSON)


class Report(Record, Base):
    __tablename__ = 'reports'
    task_id: Mapped[str] = mapped_column(ForeignKey('test_tasks.id'), index=True)
    name: Mapped[str] = mapped_column(String(160))
    data: Mapped[dict] = mapped_column(JSON)


class RegressionRecord(Record, Base):
    __tablename__ = 'regression_records'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    baseline_id: Mapped[str] = mapped_column(ForeignKey('test_tasks.id'))
    candidate_id: Mapped[str] = mapped_column(ForeignKey('test_tasks.id'))
    data: Mapped[dict] = mapped_column(JSON)


class SystemParameter(Record, Base):
    __tablename__ = 'system_parameters'
    key: Mapped[str] = mapped_column(String(80), unique=True)
    value: Mapped[dict] = mapped_column(JSON)
