"""执行引擎专项测试；模型替身只验证契约，不作为真实 AI 验收。"""

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from conftest import authenticate
from app.adapters.base import AgentResponse, AdapterError
from app.models.platform import TestTask as Task, TestResult as Result, TraceEvent
from app.services.evaluation import evaluate, aggregate

DRAFT = {
    "name": "问候",
    "test_type": "functional",
    "scenario": "普通请求",
    "user_input": "你好",
    "expected_behavior": "回应",
    "expected_result": "你好",
    "rules": {
        "evaluators": ["rules"],
        "rubric": "按规则判断",
        "must_include": ["你好"],
    },
}


@pytest.fixture
def setup_task(client, auth, project):
    agent = client.post(
        "/api/v1/agents",
        headers=auth,
        json={
            "project_id": project["id"],
            "name": "协议目标",
            "kind": "python",
            "adapter_name": "protocol_echo",
        },
    ).json()
    suite = client.post(
        "/api/v1/suites",
        headers=auth,
        json={"project_id": project["id"], "name": "执行测试套件"},
    ).json()

    def create(drafts=None, **options):
        drafts = drafts or [DRAFT]
        revision = client.get(
            "/api/v1/suites/" + suite["id"] + "/versions", headers=auth
        ).json()["items"][0]["revision"]
        for index, draft in enumerate(drafts):
            r = client.post(
                "/api/v1/cases",
                headers=auth,
                params={"expected_revision": revision},
                json={
                    **draft,
                    "name": draft["name"] + str(index) + str(revision),
                    "suite_id": suite["id"],
                },
            )
            assert r.status_code == 201, r.text
            revision += 1
        body = {
            "name": "执行测试",
            "agent_id": agent["id"],
            "suite_id": suite["id"],
            **options,
        }
        r = client.post("/api/v1/test-tasks", headers=auth, json=body)
        assert r.status_code == 201, r.text
        return r.json()

    return create, agent, suite


def wait(client, auth, task, states=("completed",), timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        r = client.get("/api/v1/test-tasks/" + task["id"], headers=auth).json()
        if r["status"] in states:
            return r
        time.sleep(0.02)
    pytest.fail("task timeout: " + str(r))


def start(client, auth, task):
    r = client.post(f"/api/v1/test-tasks/{task['id']}/start", headers=auth)
    assert r.status_code == 200, r.text


def results(client, auth, task):
    return client.get(f"/api/v1/test-tasks/{task['id']}/results", headers=auth).json()[
        "items"
    ]


def test_execution_persistence_snapshot_isolation(
    client, auth, project, setup_task, application
):
    create, agent, suite = setup_task
    task = create(
        [
            DRAFT,
            {**DRAFT, "rules": {**DRAFT["rules"], "must_include": ["不可能出现"]}},
            {**DRAFT, "rules": {"evaluators": ["llm_judge"], "rubric": "语义"}},
        ]
    )
    case = client.get(
        "/api/v1/cases", headers=auth, params={"suite_id": suite["id"]}
    ).json()["items"][0]
    assert (
        client.put(
            "/api/v1/cases/" + case["id"],
            headers=auth,
            json={
                **DRAFT,
                "user_input": "编辑后的新输入",
                "expected_revision": case["revision"],
            },
        ).status_code
        == 200
    )
    start(client, auth, task)
    done = wait(client, auth, task)
    assert (
        done["counts"]["passed"] == 1
        and done["counts"]["failed"] == 1
        and done["counts"]["inconclusive"] == 1
    )
    rows = results(client, auth, task)
    assert all(r["case"]["user_input"] == "你好" and r["attempts"] == 1 for r in rows)
    assert all(r["usage"] == {} for r in rows)
    with application.state.sessions() as db:
        assert (
            len(db.scalars(select(Result).where(Result.task_id == task["id"])).all())
            == 3
        )
        assert all("你好" not in r.payload for r in db.scalars(select(Result)))
        assert db.scalar(select(TraceEvent)) is not None
    other = authenticate(client, "task_other")
    for path in ["", "/results", "/events"]:
        assert (
            client.get(
                "/api/v1/test-tasks/" + task["id"] + path, headers=other
            ).status_code
            == 404
        )
    assert (
        client.get("/api/v1/traces/" + rows[0]["id"], headers=other).status_code == 404
    )
    retry = client.post(
        "/api/v1/test-tasks/" + task["id"] + "/retry-failed", headers=auth
    )
    assert retry.status_code == 201 and retry.json()["total"] == 2
    assert (
        client.delete("/api/v1/agents/" + agent["id"], headers=auth).status_code == 409
    )
    stream = client.get("/api/v1/test-tasks/" + task["id"] + "/events", headers=auth)
    assert "event: progress" in stream.text and "completed" in stream.text


@pytest.mark.parametrize(
    "control,final", [("pause", "paused"), ("cancel", "cancelled")]
)
def test_control_and_resume(client, auth, setup_task, monkeypatch, control, final):
    async def slow(self, input_text, history):
        await asyncio.sleep(0.22)
        return AgentResponse("你好", None, 1, [])

    monkeypatch.setattr("app.adapters.local.ProtocolEchoAdapter.invoke", slow)
    task = setup_task[0]([DRAFT] * 4, concurrency=1)
    start(client, auth, task)
    wait_started = time.monotonic() + 3
    while time.monotonic() < wait_started:
        if any(r["status"] == "running" for r in results(client, auth, task)):
            break
        time.sleep(0.01)
    assert (
        client.post(
            f"/api/v1/test-tasks/{task['id']}/{control}", headers=auth
        ).status_code
        == 200
    )
    done = wait(client, auth, task, (final,))
    assert done["counts"]["passed"] == 1
    if control == "pause":
        assert done["counts"]["pending"] == 3
        start(client, auth, task)
        assert wait(client, auth, task)["counts"]["passed"] == 4
    else:
        assert done["counts"]["cancelled"] == 3


def test_timeout_retry_and_error_isolation(client, auth, setup_task, monkeypatch):
    calls = {}

    async def target(self, input_text, history):
        calls[input_text] = calls.get(input_text, 0) + 1
        if input_text == "慢":
            await asyncio.sleep(2)
        if input_text == "重试" and calls[input_text] == 1:
            raise AdapterError("temporary_error")
        return AgentResponse("你好", 200, 1, [])

    monkeypatch.setattr("app.adapters.local.ProtocolEchoAdapter.invoke", target)
    task = setup_task[0](
        [{**DRAFT, "user_input": s} for s in ["慢", "重试", "正常"]],
        concurrency=3,
        timeout_seconds=1,
        retries=1,
    )
    start(client, auth, task)
    done = wait(client, auth, task)
    assert done["counts"]["error"] == 1 and done["counts"]["passed"] == 2
    rows = {r["case"]["user_input"]: r for r in results(client, auth, task)}
    assert rows["慢"]["error_code"] == "case_timeout" and rows["慢"]["attempts"] == 2
    assert rows["重试"]["attempts"] == 2 and rows["正常"]["attempts"] == 1


def test_real_http_agent(client, auth, setup_task):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            raw = json.dumps(
                {
                    "data": {"answer": "你好 " + body["text"]},
                    "usage": {"total_tokens": 7},
                    "events": [
                        {
                            "type": "tool_result",
                            "name": "calc",
                            "success": True,
                            "arguments": {"x": 1},
                        }
                    ],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, agent, _ = setup_task
        body = {
            "project_id": agent["project_id"],
            "name": "真实 HTTP 测试目标",
            "kind": "http",
            "endpoint": f"http://127.0.0.1:{server.server_port}/chat",
            "request_template": {},
            "input_field": "text",
            "output_field": "data.answer",
            "trace_field": "events",
            "usage_field": "usage",
        }
        r = client.post("/api/v1/agents", headers=auth, json=body)
        assert r.status_code == 201, r.text
        task = setup_task[0]([DRAFT] * 3, agent_id=r.json()["id"], concurrency=2)
        start(client, auth, task)
        assert wait(client, auth, task)["counts"]["passed"] == 3
        rows = results(client, auth, task)
        assert all(
            r["usage"]["total_tokens"] == 7 and r["events_observable"] for r in rows
        )
        events = client.get("/api/v1/traces/" + rows[0]["id"], headers=auth).json()[
            "items"
        ]
        assert any(
            e["event_type"] == "tool_result" and e["event_name"] == "calc"
            for e in events
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_restart_marks_and_resumes(application, auth, client, setup_task):
    from fastapi.testclient import TestClient

    task = setup_task[0]([DRAFT] * 2)
    with application.state.sessions() as db:
        db.get(Task, task["id"]).status = "running"
        row = db.scalar(select(Result).where(Result.task_id == task["id"]))
        row.status = "running"
        db.commit()
    # 实际执行应用 lifespan，验证启动恢复，而非只预填恢复后的状态。
    with TestClient(application) as restarted:
        recovered = restarted.get(
            "/api/v1/test-tasks/" + task["id"], headers=auth
        ).json()
        assert recovered["status"] == "interrupted"
        assert any(
            r["error_code"] == "execution_interrupted"
            for r in results(restarted, auth, task)
        )
    start(client, auth, task)
    assert wait(client, auth, task)["counts"]["passed"] == 2


@pytest.mark.asyncio
async def test_evaluators_require_evidence_and_isolate_errors(monkeypatch):
    response = AgentResponse("你好", 200, 2, [])
    case = {
        **DRAFT,
        "rules": {
            "evaluators": ["rules", "llm_judge", "deepeval"],
            "rubric": "语义",
            "expected_status_code": 200,
            "max_attempts": 1,
        },
    }
    data = await evaluate(case, response, 20, {})
    assert [d["status"] for d in data] == ["failed", "unavailable", "unavailable"]
    assert aggregate(data) == "failed"
    case["rules"] = {
        "evaluators": ["tool_trace"],
        "expected_tool": "calc",
        "expected_arguments": {"x": 1},
        "require_output_uses_tool": True,
    }
    assert (await evaluate(case, response, 1, {}))[0]["status"] == "unavailable"
    response.events_observable = True
    assert (await evaluate(case, response, 1, {}))[0]["status"] == "failed"
    response.observable_events = [
        {"type": "tool_result", "name": "calc", "arguments": {"x": 1}, "success": True}
    ]
    assert (await evaluate(case, response, 1, {}))[0]["status"] == "unavailable"

    async def broken(*args):
        raise ValueError("private secret")

    monkeypatch.setattr("app.services.evaluation.semantic", broken)
    case["rules"] = {"evaluators": ["rules", "llm_judge"], "must_include": ["你好"]}
    data = await evaluate(case, response, 1, {"judge": ({}, "secret")})
    assert [d["status"] for d in data] == [
        "passed",
        "error",
    ] and "private secret" not in str(data)


@pytest.mark.parametrize(
    "field,value",
    [("concurrency", 0), ("concurrency", 11), ("retries", 4), ("timeout_seconds", 0)],
)
def test_invalid_execution_configuration(client, auth, setup_task, field, value):
    _, agent, suite = setup_task
    assert (
        client.post(
            "/api/v1/test-tasks",
            headers=auth,
            json={
                "name": "无效任务",
                "agent_id": agent["id"],
                "suite_id": suite["id"],
                field: value,
            },
        ).status_code
        == 422
    )


@pytest.mark.asyncio
async def test_semantic_contract(monkeypatch):
    async def judge(*args):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "score": 0.9,
                    "passed": True,
                    "reason": "测试替身判断",
                    "risk": "none",
                    "recommendation": "",
                }
            )
        )

    monkeypatch.setattr("app.services.evaluation.invoke", judge)
    result = await evaluate(
        {**DRAFT, "rules": {"evaluators": ["llm_judge"], "rubric": "符合预期"}},
        AgentResponse("你好", None, 1, []),
        1,
        {"judge": ({}, "fixture-key")},
    )
    assert result[0]["status"] == "passed" and result[0]["score"] == 0.9


def test_configured_concurrency_bound(client, auth, setup_task, monkeypatch):
    active = 0
    peak = 0

    async def target(self, input_text, history):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.08)
        active -= 1
        return AgentResponse("你好", None, 1, [])

    monkeypatch.setattr("app.adapters.local.ProtocolEchoAdapter.invoke", target)
    task = setup_task[0]([DRAFT] * 6, concurrency=2)
    start(client, auth, task)
    assert wait(client, auth, task)["counts"]["passed"] == 6
    assert peak == 2 and active == 0


@pytest.mark.asyncio
async def test_active_task_capacity(application, monkeypatch):
    from fastapi import HTTPException

    manager = application.state.task_manager
    gate = asyncio.Event()

    async def job(task_id):
        await gate.wait()

    monkeypatch.setattr(manager, "run", job)
    for task_id in ["a", "b", "c"]:
        manager.schedule(task_id)
    with pytest.raises(HTTPException) as exc:
        manager.schedule("d")
    assert exc.value.status_code == 429
    with pytest.raises(HTTPException) as exc:
        manager.schedule("a")
    assert exc.value.status_code == 409
    await manager.shutdown()
    await asyncio.sleep(0)
    assert not manager.running


def test_single_case_and_task_ownership(client, auth, setup_task):
    original = setup_task[0]([DRAFT] * 2)
    rows = results(client, auth, original)
    other = authenticate(client, "task_create_other")
    body = {
        "name": "单条执行",
        "agent_id": original["agent_id"],
        "suite_id": original["suite_id"],
        "case_ids": [rows[0]["case_key"]],
        "suite_revision": original["suite_revision"],
    }
    assert (
        client.post("/api/v1/test-tasks", headers=other, json=body).status_code == 404
    )
    single = client.post("/api/v1/test-tasks", headers=auth, json=body)
    assert single.status_code == 201 and single.json()["total"] == 1
    start(client, auth, single.json())
    assert wait(client, auth, single.json())["counts"]["passed"] == 1
    for case_ids in [["missing"], [rows[0]["case_key"]] * 2]:
        assert (
            client.post(
                "/api/v1/test-tasks", headers=auth, json={**body, "case_ids": case_ids}
            ).status_code
            == 422
        )
