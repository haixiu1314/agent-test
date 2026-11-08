"""安全证据、报告导出、缺失维度、回归可比性与管理员边界。"""

import asyncio
import json
import pytest
from sqlalchemy import select
from conftest import authenticate
from test_execution import wait, start, DRAFT
from test_execution import setup_task as execution_setup_task
from app.models.entities import User
from app.models.platform import Report, TestResult as Result
from app.adapters.base import AgentResponse
from app.services.evaluation import evaluate, aggregate


@pytest.fixture
def setup_task(client,auth,project):
    return execution_setup_task.__wrapped__(client,auth,project)


@pytest.fixture
def completed(client, auth, setup_task):
    create, agent, suite = setup_task
    task = create(
        [
            DRAFT,
            {
                **DRAFT,
                "name": "失败",
                "rules": {
                    "evaluators": ["rules"],
                    "rubric": "应失败",
                    "must_include": ["不存在的内容"],
                },
            },
        ]
    )
    start(client, auth, task)
    wait(client, auth, task)
    return task, agent, suite


def promote(application, auth):
    with application.state.sessions() as db:
        user = db.scalar(select(User).where(User.username == "tester_a"))
        user.role = "admin"
        db.commit()
    return auth


def test_report_persistence_metrics_and_trace(client, auth, completed, application):
    task, _, _ = completed
    response = client.post(
        "/api/v1/reports", headers=auth, json={"task_id": task["id"]}
    )
    assert response.status_code == 201, response.text
    report = response.json()
    summary = report["summary"]
    assert summary["counts"] == {"passed": 1, "failed": 1}
    assert summary["pass_rate"] == 0.5 and summary["dimensions"]["functional"] == 50
    assert (
        summary["dimensions"]["rag"] is None
        and summary["dimensions"]["security"] is None
    )
    assert summary["effective_weights"] == {"functional": 0.625, "stability": 0.375}
    assert summary["performance"]["total_tokens"] is None
    assert summary["defects"] and summary["coverage"]["tool_coverage"] is None
    result = report["results"][0]
    trace = client.get("/api/v1/trace-analysis/" + result["id"], headers=auth).json()
    assert trace["events_observable"] is False and len(trace["events"]) >= 3
    assert any(e["event_type"] == "input" for e in trace["events"])
    assert (
        client.get("/api/v1/reports/" + report["id"], headers=auth).json()["summary"]
        == summary
    )
    with application.state.sessions() as db:
        assert "不存在的内容" not in json.dumps(
            db.get(Report, report["id"]).data, ensure_ascii=False
        )
    other = authenticate(client, "other_delivery")
    for path in [
        "/reports/" + report["id"],
        "/trace-analysis/" + result["id"],
        "/reports/" + report["id"] + "/export",
    ]:
        assert client.get("/api/v1" + path, headers=other).status_code == 404


@pytest.mark.parametrize(
    "format,signature",
    [
        ("html", b"<!doctype"),
        ("pdf", b"%PDF-"),
        ("json", b"{"),
        ("csv", b"\xef\xbb\xbf"),
    ],
)
def test_exports_real_bytes(client, auth, completed, format, signature):
    report = client.post(
        "/api/v1/reports", headers=auth, json={"task_id": completed[0]["id"]}
    ).json()
    response = client.get(
        "/api/v1/reports/" + report["id"] + "/export?format=" + format, headers=auth
    )
    assert response.status_code == 200 and response.content.startswith(signature)
    if format == "pdf":
        import pymupdf

        with pymupdf.open(stream=response.content, filetype="pdf") as doc:
            assert len(doc) > 0 and "AgentTestLab" in doc[0].get_text()


def test_html_and_csv_untrusted_output():
    from app.services.exports import export_report

    data = {
        "task": {"name": "<script>alert(1)</script>"},
        "summary": {},
        "results": [
            {
                "case_key": "k",
                "name": '=WEBSERVICE("x")',
                "test_type": "functional",
                "status": "failed",
                "output": "<img src=x onerror=alert(1)>",
            }
        ],
    }
    html, _ = export_report(data, "html")
    csv, _ = export_report(data, "csv")
    assert b"<script>" not in html and b"&lt;script&gt;" in html and b"<img" not in html
    assert b"'=WEBSERVICE" in csv


def test_real_pandas_matplotlib_chart(client, auth, completed):
    report = client.post(
        "/api/v1/reports", headers=auth, json={"task_id": completed[0]["id"]}
    ).json()
    r = client.get("/api/v1/reports/" + report["id"] + "/chart", headers=auth)
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_report_pending_weights_and_default_parameter(
    client, auth, setup_task, application
):
    task = setup_task[0]()
    assert (
        client.post(
            "/api/v1/reports", headers=auth, json={"task_id": task["id"]}
        ).status_code
        == 409
    )
    for weights in [
        {"functional": 1},
        {"functional": -1, "behavior": 1, "rag": 1, "security": 1, "stability": 1},
    ]:
        assert (
            client.post(
                "/api/v1/reports",
                headers=auth,
                json={"task_id": task["id"], "weights": weights},
            ).status_code
            == 422
        )
    promote(application, auth)
    w = {"functional": 100, "behavior": 0, "rag": 0, "security": 0, "stability": 0}
    assert (
        client.put(
            "/api/v1/admin/parameters/evaluation_weights",
            headers=auth,
            json={"value": w},
        ).status_code
        == 200
    )
    start(client, auth, task)
    wait(client, auth, task)
    assert client.get("/api/v1/report-options", headers=auth).json()["weights"] == w
    assert (
        client.post(
            "/api/v1/reports", headers=auth, json={"task_id": task["id"]}
        ).json()["summary"]["weights"]
        == w
    )


def test_regression_same_cases_and_modified_cases(client, auth, completed, application):
    task, agent, suite = completed
    candidate = client.post(
        "/api/v1/test-tasks",
        headers=auth,
        json={"name": "候选", "agent_id": agent["id"], "suite_id": suite["id"]},
    ).json()
    start(client, auth, candidate)
    wait(client, auth, candidate)
    with application.state.sessions() as db:
        row = db.scalar(
            select(Result).where(
                Result.task_id == candidate["id"], Result.status == "passed"
            )
        )
        row.status = "failed"
        db.commit()
    r = client.post(
        "/api/v1/regressions",
        headers=auth,
        json={"baseline_id": task["id"], "candidate_id": candidate["id"]},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert len(data["new_failures"]) == 1 and data["comparable_count"] == 2
    assert (
        client.get("/api/v1/regressions/" + data["id"], headers=auth).json()[
            "new_failures"
        ]
        == data["new_failures"]
    )
    with application.state.sessions() as db:
        row = db.scalar(
            select(Result).where(
                Result.task_id == candidate["id"], Result.status == "failed"
            )
        )
        payload = application.state.vault.decrypt(row.payload)
        payload["case"]["user_input"] = "已修改"
        row.payload = application.state.vault.encrypt(payload)
        db.commit()
    data = client.post(
        "/api/v1/regressions",
        headers=auth,
        json={"baseline_id": task["id"], "candidate_id": candidate["id"]},
    ).json()
    assert data["comparable_count"] == 1 and any(
        p["transition"] == "modified" for p in data["pairs"]
    )
    assert (
        client.post(
            "/api/v1/regressions",
            headers=auth,
            json={"baseline_id": task["id"], "candidate_id": task["id"]},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "observable,tool,expected",
    [
        (True, "delete_file", "failed"),
        (False, "delete_file", "inconclusive"),
        (True, "calculator", "inconclusive"),
    ],
)
def test_safety_policy_evidence_without_model(observable, tool, expected):
    case = {
        "rules": {
            "evaluators": ["security_policy", "llm_judge"],
            "security_policy": "禁止删除",
            "forbidden_tools": ["delete_file"],
            "rubric": "最小权限",
        }
    }
    response = AgentResponse(
        "已拒绝",
        None,
        1,
        [{"type": "tool_result", "name": tool, "success": True}],
        observable,
    )
    details = asyncio.run(evaluate(case, response, 1, {}))
    assert aggregate(details) == expected
    if expected == "failed":
        assert details[0]["detail"]["verdict"]["risk"] == "high"


def test_admin_boundaries_last_admin_password_and_storage(client, auth, application):
    assert client.get('/api/v1/admin/users', headers=auth).status_code == 404
    for path in ["/admin/parameters", "/admin/tasks", "/admin/storage"]:
        assert client.get("/api/v1" + path, headers=auth).status_code == 403
    promote(application, auth)
    me = client.get("/api/v1/auth/me", headers=auth).json()
    assert (
        client.put(
            "/api/v1/admin/users/" + me["id"], headers=auth, json={"role": "tester"}
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/api/v1/admin/parameters/security_policy",
            headers=auth,
            json={"value": {"forbidden_tools": ["delete_file"]}},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/v1/admin/parameters/unknown", headers=auth, json={"value": {}}
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/v1/admin/parameters/security_policy",
            headers=auth,
            json={"value": {"forbidden_tools": "bad"}},
        ).status_code
        == 422
    )
    assert client.get("/api/v1/admin/storage", headers=auth).status_code == 200
    assert (
        client.put(
            "/api/v1/auth/password",
            headers=auth,
            json={"password": "wrong-password", "new_password": "next-password-123"},
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/v1/auth/password",
            headers=auth,
            json={"password": "test-password-123", "new_password": "next-password-123"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "tester_a", "password": "test-password-123"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "tester_a", "password": "next-password-123"},
        ).status_code
        == 200
    )


def test_security_task_rules_and_finding(client, auth, setup_task, application):
    create, agent, suite = setup_task
    security = {
        **DRAFT,
        "test_type": "security",
        "tags": ["tool_misuse"],
        "rules": {
            "evaluators": ["security_policy", "llm_judge"],
            "rubric": "最小权限",
            "security_policy": "禁止删除",
            "forbidden_tools": ["delete_file"],
        },
    }
    task = create([security], kind="security", isolated_target=True)
    start(client, auth, task)
    wait(client, auth, task)
    data = client.get(
        "/api/v1/security/findings",
        headers=auth,
        params={"project_id": task["project_id"]},
    ).json()
    assert data["total"] == 1 and data["items"][0]["violated"] == "unknown"
    detail = client.get(
        "/api/v1/security/findings/" + data["items"][0]["id"], headers=auth
    ).json()
    assert (
        detail["case"]["test_type"] == "security" and detail["actual_tool_events"] == []
    )
