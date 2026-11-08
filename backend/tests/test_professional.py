"""实际运行 DeepEval 算法，LLM JSON 为显式替身，不算真实模型验收。"""

import json
from types import SimpleNamespace
import pytest
from app.adapters.base import AgentResponse


@pytest.mark.asyncio
async def test_deepeval_real_metric_with_explicit_model_fixture(monkeypatch):
    from app.integrations.professional import deep_eval

    calls = []

    async def fixture(config, key, messages):
        text = "\n".join(m[1] for m in messages)
        calls.append(text)
        if '"statements"' in text and '"verdicts"' not in text:
            content = {"statements": ["你好"]}
        elif '"verdicts"' in text:
            content = {"verdicts": [{"verdict": "yes", "reason": "fixture"}]}
        else:
            content = {"reason": "fixture explanation"}
        return SimpleNamespace(content=json.dumps(content))

    monkeypatch.setattr("app.integrations.professional.invoke", fixture)
    result = await deep_eval(
        {"user_input": "你好", "expected_result": "问候"},
        AgentResponse("你好", None, 1, []),
        {"model": "contract-fixture"},
        "fixture-key",
    )
    assert result["passed"] and result["score"] == 1
    assert result["metrics"][0]["name"] == "Answer Relevancy"
    assert len(calls) >= 3
