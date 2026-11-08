"""公开响应模型，防止 ORM 密钥字段意外进入 API。"""
from datetime import datetime
from typing import Generic, TypeVar, Literal
from pydantic import BaseModel

T = TypeVar('T')


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class UserPublic(BaseModel):
    id: str
    username: str
    role: str


class TokenPublic(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


class ProjectPublic(BaseModel):
    id: str
    name: str
    description: str
    business_type: str
    created_at: datetime
    updated_at: datetime


class AgentPublic(BaseModel):
    id: str
    project_id: str
    name: str
    kind: Literal['http','python']
    endpoint: str
    method: str
    request_template: dict
    input_field: str
    output_field: str
    history_field: str | None
    adapter_name: str
    timeout_seconds: float
    retries: int
    auth_header: str
    version_label: str
    version: int
    has_api_key: bool
    header_names: list[str]
    created_at: datetime
    updated_at: datetime
    trace_field: str | None = None
    usage_field: str | None = None
    contexts_field: str | None = None


class VersionPublic(BaseModel):
    id: str
    version: int
    snapshot: dict
    created_at: datetime


class ConnectionPublic(BaseModel):
    success: bool
    error_code: str | None
    duration_ms: float
    status_code: int | None
    attempts: int | None
    output_received: bool
    tool_events: str
    request_id: str
