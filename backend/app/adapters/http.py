import asyncio
import copy
import json
import httpx
from app.adapters.base import AgentAdapter, AgentResponse, AdapterError


def set_field(data: dict, path: str, value):
    """把内部统一输入写入目标 Agent 的嵌套对象字段。"""
    parts = path.split('.')
    node = data
    for part in parts[:-1]:
        if part not in node:
            node[part] = {}
        if not isinstance(node[part], dict):
            raise AdapterError('invalid_input_mapping')
        node = node[part]
    node[parts[-1]] = value


def get_field(data: dict, path: str):
    node = data
    try:
        for part in path.split('.'):
            node = node[part]
    except (KeyError, TypeError):
        raise AdapterError('output_field_missing') from None
    if not isinstance(node, str):
        raise AdapterError('output_must_be_string')
    return node


def optional_value(data,path,expected):
    if not path:return None
    value=data
    try:
        for part in path.split('.'):value=value[part]
    except (KeyError,TypeError):raise AdapterError('observable_field_missing') from None
    if not isinstance(value,expected):raise AdapterError('invalid_observable_field')
    return value


class HttpAgentAdapter(AgentAdapter):
    def __init__(self, config: dict, secrets: dict, transport=None):
        self.config, self.secrets, self.transport = config, secrets, transport

    async def invoke(self, input_text: str, history: list[dict]) -> AgentResponse:
        c = self.config
        payload = copy.deepcopy(c['request_template'])
        set_field(payload, c['input_field'], input_text)
        if c.get('history_field'):
            set_field(payload, c['history_field'], history)
        headers = dict(self.secrets.get('headers') or {})
        if self.secrets.get('api_key'):
            headers[c['auth_header']] = self.secrets['api_key']
        last_error = 'upstream_error'
        async with httpx.AsyncClient(timeout=c['timeout_seconds'], follow_redirects=False,
                                     transport=self.transport, trust_env=False) as client:
            for attempt in range(c['retries'] + 1):
                try:
                    kwargs = {'json': payload} if c['method'] == 'POST' else {'params': {
                        k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in payload.items()}}
                    async with asyncio.timeout(c['timeout_seconds']):
                        async with client.stream(c['method'], c['endpoint'], headers=headers, **kwargs) as response:
                            if response.status_code in [502, 503, 504]:
                                raise AdapterError('upstream_unavailable')
                            if not 200 <= response.status_code < 300:
                                raise AdapterError('upstream_http_error')
                            content = bytearray()
                            async for piece in response.aiter_bytes():
                                content.extend(piece)
                                if len(content) > 1024 * 1024:
                                    raise AdapterError('response_too_large')
                            try:
                                data = json.loads(content)
                            except (ValueError, UnicodeDecodeError):
                                raise AdapterError('invalid_json_response') from None
                            output = get_field(data, c['output_field'])
                            events=optional_value(data,c.get('trace_field'),list)
                            usage=optional_value(data,c.get('usage_field'),dict) or {}
                            contexts=optional_value(data,c.get('contexts_field'),list) or []
                            if events is not None and (len(events)>100 or any(not isinstance(e,dict) for e in events)):
                                raise AdapterError('invalid_observable_field')
                            if len(contexts)>30 or any(not isinstance(t,str) or len(t)>20000 for t in contexts):
                                raise AdapterError('invalid_observable_field')
                            return AgentResponse(output, response.status_code, attempt + 1, events or [],events is not None,usage,contexts)
                except (httpx.TimeoutException, TimeoutError):
                    last_error = 'upstream_timeout'
                except httpx.RequestError:
                    last_error = 'upstream_network_error'
                except AdapterError as exc:
                    last_error = exc.code
                    if exc.code != 'upstream_unavailable':
                        raise
                if attempt < c['retries']:
                    await asyncio.sleep(0.1 * (attempt + 1))
        raise AdapterError(last_error)
