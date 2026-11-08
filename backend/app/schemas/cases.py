"""结构化测试用例契约：工具、安全、记忆等类型必须保留相应判定证据。"""
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from pydantic import Field, SecretStr, model_validator, field_validator, BaseModel
from app.schemas.inputs import Input

CaseType=Literal['functional','boundary','planning','memory','tool','rag','security','exception']
Evaluator=Literal['rules','llm_judge','tool_trace','conversation','ragas','security_policy','deepeval']


class Message(Input):
    role: Literal['user','assistant']
    content: str = Field(max_length=10000)


class Rules(Input):
    evaluators: list[Evaluator] = Field(min_length=1,max_length=7)
    must_include: list[str] = Field(default_factory=list,max_length=30)
    must_not_include: list[str] = Field(default_factory=list,max_length=30)
    expected_tool: str | None = Field(default=None,max_length=100)
    expected_arguments: dict = Field(default_factory=dict)
    require_tool_success: bool = False
    require_output_uses_tool: bool = False
    max_latency_ms: int | None = Field(default=None,ge=1,le=600000)
    rubric: str = Field(min_length=1,max_length=4000)
    security_policy: str | None = Field(default=None,max_length=4000)
    forbidden_tools: list[str] = Field(default_factory=list,max_length=30)
    reference_contexts: list[str] = Field(default_factory=list,max_length=30)
    required_json_fields: list[str] = Field(default_factory=list,max_length=30)
    expected_status_code: int | None = Field(default=None,ge=100,le=599)
    max_attempts: int | None = Field(default=None,ge=1,le=16)


class CaseDraft(Input):
    name: str = Field(min_length=1,max_length=160)
    test_type: CaseType
    scenario: str = Field(min_length=1,max_length=5000)
    preconditions: str = Field(default='',max_length=5000)
    user_input: str = Field(max_length=20000)
    history: list[Message] = Field(default_factory=list,max_length=30)
    expected_behavior: str = Field(min_length=1,max_length=5000)
    expected_result: str = Field(min_length=1,max_length=5000)
    rules: Rules
    priority: Literal['P0','P1','P2','P3'] = 'P1'
    tags: list[str] = Field(default_factory=list,max_length=20)

    @field_validator('name','scenario','expected_behavior','expected_result')
    @classmethod
    def not_blank(cls,value):
        if not value.strip():raise ValueError('must not be blank')
        return value.strip()

    @model_validator(mode='after')
    def valid_strategy(self):
        evaluators=self.rules.evaluators
        if self.test_type=='tool' and (not self.rules.expected_tool or 'tool_trace' not in evaluators or
            not self.rules.require_tool_success or not self.rules.require_output_uses_tool):
            raise ValueError('tool cases require tool trace, expected tool, successful result and output grounding')
        if self.test_type=='security' and ('security_policy' not in evaluators or 'llm_judge' not in evaluators or not self.rules.security_policy):
            raise ValueError('security cases require policy and semantic judge')
        if self.test_type=='memory' and (not self.history or 'conversation' not in evaluators):
            raise ValueError('memory cases require history and conversation evaluation')
        if self.test_type=='rag' and 'ragas' not in evaluators:
            raise ValueError('rag cases require ragas evaluation')
        if any(len(tag)>80 or not tag.strip() for tag in self.tags):raise ValueError('invalid tags')
        return self


class CaseCreate(CaseDraft):
    suite_id: str


class CaseUpdate(CaseDraft):
    expected_revision: int = Field(ge=1)


class CasePublic(CaseDraft):
    id: str
    suite_id: str
    revision: int
    source: str
    generation_run_id: str | None
    created_at: datetime
    updated_at: datetime


class SuiteInput(Input):
    project_id: str
    name: str = Field(min_length=1,max_length=120)
    description: str = Field(default='',max_length=5000)
    expected_revision: int | None = Field(default=None,ge=1)

    @field_validator('name')
    @classmethod
    def not_blank(cls,value):
        if not value.strip():raise ValueError('must not be blank')
        return value.strip()


class SuitePublic(BaseModel):
    id: str
    project_id: str
    name: str
    description: str
    revision: int
    case_count: int
    created_at: datetime
    updated_at: datetime


class ImportBatch(Input):
    cases: list[CaseDraft] = Field(min_length=1,max_length=100)
    expected_revision: int = Field(ge=1)


class FileImport(Input):
    format: Literal['json','csv']
    content: str = Field(max_length=800000)
    expected_revision: int = Field(ge=1)


class ModelInput(Input):
    name: str = Field(min_length=1,max_length=120)
    purpose: Literal['generation','demo','judge','security','rag','embedding'] = 'generation'
    provider: Literal['openai-compatible'] = 'openai-compatible'
    base_url: str = Field(max_length=1000)
    model: str = Field(min_length=1,max_length=120)
    temperature: float = Field(default=0,ge=0,le=2)
    timeout_seconds: float = Field(default=60,ge=1,le=120)
    max_tokens: int = Field(default=12000,ge=256,le=32000)
    api_key: SecretStr | None = Field(default=None,max_length=8192)

    @model_validator(mode='after')
    def validate_url(self):
        address=urlsplit(self.base_url)
        if address.scheme not in ['http','https'] or not address.hostname or address.username or address.password or address.query or address.fragment:
            raise ValueError('invalid model base URL')
        if not self.name.strip() or not self.model.strip():raise ValueError('name/model must not be blank')
        return self


class ModelTestInput(ModelInput):
    saved_model_id: str | None = None


class GenerationInput(Input):
    project_id: str
    model_config_id: str | None = None
    requirements: str = Field(min_length=5,max_length=10000)
    system_prompt: str = Field(default='',max_length=20000)
    tools: list[dict] = Field(default_factory=list,max_length=20)
    interface_info: str = Field(default='',max_length=5000)
    types: list[CaseType] = Field(min_length=1,max_length=8)
    count: int = Field(default=8,ge=1,le=30)
    security_categories: list[Literal['prompt_injection','jailbreak','role_manipulation','sensitive_data_leakage','tool_misuse','excessive_agency','rag_poisoning','multi_turn_attack']] = Field(default_factory=list,max_length=8)

    @model_validator(mode='after')
    def enough_cases(self):
        if len(self.types)!=len(set(self.types)) or len(self.types)>self.count:
            raise ValueError('types must be unique and count must cover each requested type')
        if self.security_categories and (self.types!=['security'] or len(self.security_categories)>self.count or len(set(self.security_categories))!=len(self.security_categories)):
            raise ValueError('security generation requires unique category coverage')
        return self


class GeneratedBatch(Input):
    capability_analysis: str = Field(min_length=1,max_length=8000)
    risks: list[str] = Field(max_length=30)
    cases: list[CaseDraft] = Field(min_length=1,max_length=30)


class SaveGeneration(Input):
    suite_id: str
    expected_revision: int = Field(ge=1)
    indexes: list[int] = Field(min_length=1,max_length=30)
    cases: list[CaseDraft] = Field(min_length=1,max_length=30)
