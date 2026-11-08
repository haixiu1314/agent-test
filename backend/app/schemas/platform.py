from typing import Literal
from pydantic import Field, model_validator
from app.schemas.inputs import Input


class TaskInput(Input):
    knowledge_base_id: str | None = None
    name: str = Field(min_length=1, max_length=160)
    agent_id: str
    suite_id: str
    agent_version: int | None = Field(default=None, ge=1)
    suite_revision: int | None = Field(default=None, ge=1)
    case_ids: list[str] = Field(default_factory=list, max_length=1000)
    concurrency: int = Field(default=2, ge=1, le=10)
    timeout_seconds: float = Field(default=60, ge=1, le=180)
    retries: int = Field(default=0, ge=0, le=3)
    judge_model_id: str | None = None
    rag_model_id: str | None = None
    embedding_model_id: str | None = None
    demo_model_id: str | None = None
    demo_defect: Literal[
        "none",
        "wrong_tool_description",
        "missing_knowledge",
        "conflicting_knowledge",
        "bad_prompt",
        "tool_timeout",
    ] = "none"
    kind: Literal["quality", "security"] = "quality"
    isolated_target: bool = False

    @model_validator(mode="after")
    def valid_task(self):
        if not self.name.strip():
            raise ValueError("name required")
        if len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("duplicate cases")
        if self.kind == "security" and not self.isolated_target:
            raise ValueError("security target must be isolated")
        return self


class KnowledgeInput(Input):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=5000)
    embedding_model_id: str | None = None
    dimension: int = Field(default=1536, ge=8, le=4096)
    chunk_size: int = Field(default=700, ge=100, le=2000)
    overlap: int = Field(default=100, ge=0, le=500)

    @model_validator(mode="after")
    def overlap_valid(self):
        if self.overlap >= self.chunk_size or not self.name.strip():
            raise ValueError("invalid chunk/name")
        return self


class DocumentInput(Input):
    name: str = Field(min_length=1, max_length=240)
    content_base64: str = Field(min_length=1, max_length=720000)


class RagQuestion(Input):
    question: str = Field(min_length=1, max_length=5000)
    reference: str = Field(min_length=1, max_length=10000)
    source_chunk_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def not_blank(self):
        if not self.question.strip() or not self.reference.strip():
            raise ValueError("question/reference required")
        return self


class DatasetInput(Input):
    name: str = Field(min_length=1, max_length=120)
    questions: list[RagQuestion] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def name_valid(self):
        if not self.name.strip():
            raise ValueError("name required")
        return self


class GenerateQuestions(Input):
    name: str = Field(default="AI 问题草稿", min_length=1, max_length=120)
    count: int = Field(default=5, ge=1, le=20)
    model_config_id: str | None = None


class RetrieveInput(Input):
    question: str = Field(min_length=1, max_length=5000)
    top_k: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def query_valid(self):
        if not self.question.strip():
            raise ValueError("question required")
        return self


class RagEvaluationInput(Input):
    questions: list[RagQuestion] = Field(default_factory=list, max_length=20)
    dataset_id: str | None = None
    model_config_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=10)
    mode: Literal["retrieval", "generation", "combined"] = "combined"

    @model_validator(mode="after")
    def source_valid(self):
        if bool(self.questions) == bool(self.dataset_id):
            raise ValueError("choose questions or dataset")
        return self


class QualityInput(Input):
    semantic_conflicts: bool = False
    model_config_id: str | None = None


class ReportInput(Input):
    task_id: str
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "functional": 25,
            "behavior": 20,
            "rag": 20,
            "security": 20,
            "stability": 15,
        }
    )

    @model_validator(mode="after")
    def valid_weights(self):
        if set(self.weights) != {
            "functional",
            "behavior",
            "rag",
            "security",
            "stability",
        }:
            raise ValueError("invalid dimensions")
        if (
            any(not 0 <= v <= 100 for v in self.weights.values())
            or sum(self.weights.values()) <= 0
        ):
            raise ValueError("invalid weights")
        return self


class RegressionInput(Input):
    baseline_id: str
    candidate_id: str


class UserUpdate(Input):
    role: Literal["tester", "admin"]


class ProfileInput(Input):
    password: str = Field(min_length=10, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)
