"""适配器统一契约：只承诺最终回答，不伪造不可观测事件。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentResponse:
    output: str
    status_code: int | None
    attempts: int
    observable_events: list[dict]
    events_observable: bool = False
    usage: dict = field(default_factory=dict)
    contexts: list[str] = field(default_factory=list)


class AdapterError(Exception):
    """对外提供固定错误码，避免上游异常中包含凭证或响应体。"""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class AgentAdapter(ABC):
    @abstractmethod
    async def invoke(self, input_text: str, history: list[dict]) -> AgentResponse:
        raise NotImplementedError
