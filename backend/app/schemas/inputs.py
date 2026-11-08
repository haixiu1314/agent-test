"""接口校验契约，未知字段一律拒绝，避免角色等字段被悄悄写入。"""
import re
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Credentials(Input):
    username: str = Field(min_length=3, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$')
    password: SecretStr = Field(min_length=10, max_length=128)


class ProjectInput(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=5000)
    business_type: str = Field(default='通用助手', min_length=1, max_length=50)

    @field_validator('name', 'business_type')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('must not be blank')
        return value.strip()


class AgentInput(Input):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    kind: Literal['http', 'python'] = 'http'
    endpoint: str = Field(default='', max_length=2000)
    method: Literal['POST', 'GET'] = 'POST'
    request_template: dict = Field(default_factory=dict)
    input_field: str = Field(default='input', min_length=1, max_length=120)
    output_field: str = Field(default='output', min_length=1, max_length=120)
    history_field: str | None = Field(default=None, max_length=120)
    adapter_name: Literal['protocol_echo','enterprise_demo'] = 'protocol_echo'
    trace_field: str | None = Field(default=None,max_length=120)
    usage_field: str | None = Field(default=None,max_length=120)
    contexts_field: str | None = Field(default=None,max_length=120)
    timeout_seconds: float = Field(default=15, ge=0.1, le=60)
    retries: int = Field(default=0, ge=0, le=3)
    headers: dict[str, str] | None = None
    api_key: SecretStr | None = None
    auth_header: str = Field(default='Authorization', max_length=80, pattern=r'^[A-Za-z0-9-]+$')
    version_label: str = Field(default='初始配置', max_length=120)
    expected_version: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def valid_agent(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError('name must not be blank')
        if len(str(self.request_template)) > 32000:
            raise ValueError('request_template too large')
        for path in [self.input_field, self.output_field, self.history_field,self.trace_field,self.usage_field,self.contexts_field]:
            if path is not None and not re.fullmatch(r'[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)*', path):
                raise ValueError('mapping must be a dotted object field path')
        if self.history_field and (self.input_field == self.history_field or
            self.input_field.startswith(self.history_field + '.') or self.history_field.startswith(self.input_field + '.')):
            raise ValueError('input/history mapping paths overlap')
        if self.kind == 'http':
            address = urlsplit(self.endpoint)
            if address.scheme not in ['http', 'https'] or not address.hostname or address.username or address.password or address.fragment:
                raise ValueError('endpoint must be an HTTP URL without credentials or fragment')
            if address.query:
                raise ValueError('put query parameters in request_template, not endpoint')
        if self.headers and (len(self.headers) > 30 or any('\r' in k+v or '\n' in k+v for k, v in self.headers.items())):
            raise ValueError('invalid request headers')
        return self


class ConnectionInput(Input):
    input: str = Field(default='连接验证', max_length=10000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=30)
