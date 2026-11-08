"""防止取消被计为满分，校验真实知识库工具接线和用户归属。"""

import asyncio
from types import SimpleNamespace
from langchain_core.messages import AIMessage
from app.services.analysis import summarize
from app.schemas.platform import ReportInput


def test_cancelled_not_perfect_stability():
    row = {
        "id": "r",
        "case_key": "c",
        "test_type": "functional",
        "status": "cancelled",
        "duration_ms": None,
        "usage": {},
        "case": {"rules": {}},
        "events": [],
        "evaluations": [],
    }
    data = summarize([row], ReportInput(task_id="t").weights, [])
    assert data["score"] is None and data["pass_rate"] == 0
    assert data["dimensions"]["stability"] is None


def test_demo_milvus_tool_wiring(monkeypatch):
    from app.services.demo import chat

    responses = iter(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "knowledge_search",
                        "args": {"query": "保修期"},
                        "id": "call-kb",
                    }
                ],
            ),
            AIMessage(content="依据资料为一年"),
        ]
    )

    async def invoke(*args):
        return next(responses)

    calls = []

    async def search(query):
        calls.append(query)
        return {
            "source": "milvus",
            "milvus": True,
            "snippets": [{"id": "source", "text": "保修一年"}],
        }

    monkeypatch.setattr("app.services.demo.invoke", invoke)
    body = SimpleNamespace(input="保修期？", history=[], defect="none")
    data = asyncio.run(chat({}, "fixture-key", body, search))
    event = next(e for e in data["events"] if e["type"] == "tool_result")
    assert calls == ["保修期"] and event["result"]["milvus"] is True
    assert (
        data["events"][0]["type"] == "memory_read"
        and data["events"][-1]["type"] == "memory_write"
    )


def test_demo_kb_project_validation(client, auth, project):
    second = client.post(
        "/api/v1/projects", headers=auth, json={"name": "另一个项目"}
    ).json()
    kb = client.post(
        "/api/v1/rag/knowledge-bases",
        headers=auth,
        json={"project_id": second["id"], "name": "另库"},
    ).json()
    response = client.post(
        "/api/v1/demo/chat",
        headers=auth,
        json={
            "project_id": project["id"],
            "knowledge_base_id": kb["id"],
            "input": "保修期",
        },
    )
    assert response.status_code == 422
