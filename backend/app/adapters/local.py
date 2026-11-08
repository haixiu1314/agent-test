"""服务器白名单适配器，无动态 import、eval、上传代码执行能力。"""
from app.adapters.base import AgentAdapter, AgentResponse, AdapterError


class ProtocolEchoAdapter(AgentAdapter):
    async def invoke(self, input_text: str, history: list[dict]) -> AgentResponse:
        return AgentResponse(f'协议连接成功：{input_text}', None, 1, [])


def local_adapter(name: str) -> AgentAdapter:
    if name != 'protocol_echo':
        raise AdapterError('adapter_not_registered')
    return ProtocolEchoAdapter()
