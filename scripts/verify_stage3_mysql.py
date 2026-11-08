"""通过真实 HTTP API 与真实 MySQL 验证第三阶段，不使用模型替身。目标为明确的非 AI 测试服务。"""

import json
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import Settings
from app.db.session import make_engine
import httpx
from sqlalchemy import text


def main():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            time.sleep(0.2)
            answer = json.dumps(
                {
                    "reply": {"text": "HTTP 执行成功：" + body["query"]},
                    "events": [
                        {
                            "type": "tool_result",
                            "name": "echo",
                            "arguments": {},
                            "success": True,
                        }
                    ],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(answer)

        def log_message(self, *args):
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=target.serve_forever, daemon=True)
    worker.start()
    checks = []
    engine = None
    try:
        with httpx.Client(
            base_url="http://127.0.0.1:8000/api/v1", timeout=15, trust_env=False
        ) as client:
            credentials = {
                "username": "stage3_" + uuid4().hex[:12],
                "password": uuid4().hex + "Aa1!",
            }
            assert client.post("/auth/register", json=credentials).status_code == 201
            client.headers["Authorization"] = (
                "Bearer "
                + client.post("/auth/login", json=credentials).json()["access_token"]
            )
            project = client.post(
                "/projects", json={"name": "第三阶段真实 HTTP/MySQL 验收"}
            ).json()
            agent = client.post(
                "/agents",
                json={
                    "project_id": project["id"],
                    "name": "非 AI 本地 HTTP 验收目标",
                    "kind": "http",
                    "endpoint": f"http://127.0.0.1:{target.server_port}/chat",
                    "input_field": "query",
                    "output_field": "reply.text",
                    "trace_field": "events",
                },
            ).json()
            suite = client.post(
                "/suites", json={"project_id": project["id"], "name": "执行与判定验收"}
            ).json()
            for index, kind in enumerate(["passed", "failed", "inconclusive"]):
                rules = {
                    "evaluators": ["rules"],
                    "rubric": "检测实际响应",
                    "must_include": [
                        "执行成功" if kind == "passed" else "不会出现的内容"
                    ],
                }
                if kind == "inconclusive":
                    rules = {"evaluators": ["llm_judge"], "rubric": "需模型的语义判定"}
                response = client.post(
                    "/cases",
                    params={"expected_revision": index + 1},
                    json={
                        "suite_id": suite["id"],
                        "name": "验收_" + kind,
                        "test_type": "functional",
                        "scenario": "真实 HTTP 执行",
                        "user_input": "中文输入" + str(index),
                        "expected_behavior": "响应输入",
                        "expected_result": "执行成功",
                        "rules": rules,
                    },
                )
                assert response.status_code == 201, response.status_code
            task = client.post(
                "/test-tasks",
                json={
                    "name": "第三阶段执行验收",
                    "agent_id": agent["id"],
                    "suite_id": suite["id"],
                    "concurrency": 1,
                    "retries": 1,
                    "timeout_seconds": 3,
                },
            ).json()
            assert (
                client.post("/test-tasks/" + task["id"] + "/start").status_code == 200
            )

            def wait(states):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    data = client.get("/test-tasks/" + task["id"]).json()
                    if data["status"] in states:
                        return data
                    time.sleep(0.03)
                raise AssertionError("Task did not finish")

            # 等待第一条在途调用后发送暂停请求，确保剩余条目未执行。
            time.sleep(0.08)
            assert (
                client.post("/test-tasks/" + task["id"] + "/pause").status_code == 200
            )
            paused = wait(["paused"])
            assert paused["counts"]["pending"] >= 1
            checks.append("pause_at_dispatch_boundary")
            assert (
                client.post("/test-tasks/" + task["id"] + "/start").status_code == 200
            )
            done = wait(["completed"])
            assert (
                done["counts"]["passed"] == 1
                and done["counts"]["failed"] == 1
                and done["counts"]["inconclusive"] == 1
            )
            checks += [
                "real_http_batch",
                "resume",
                "mixed_verdicts",
                "missing_model_not_passed",
            ]
            rows = client.get("/test-tasks/" + task["id"] + "/results").json()["items"]
            assert all(r["duration_ms"] > 100 and r["attempts"] == 1 for r in rows)
            assert all(r["usage"] == {} and r["tool_call_count"] == 1 for r in rows)
            checks += [
                "real_latency",
                "attempts_recorded",
                "missing_token_not_fabricated",
                "observable_tool_count",
            ]
            events = client.get("/traces/" + rows[0]["id"]).json()["items"]
            assert {"input", "output", "tool_result", "evaluation"}.issubset(
                {e["event_type"] for e in events}
            )
            checks.append("persisted_observable_events")
            assert (
                "event: progress"
                in client.get("/test-tasks/" + task["id"] + "/events").text
            )
            checks.append("authenticated_sse")
            rerun = client.post("/test-tasks/" + task["id"] + "/retry-failed").json()
            assert rerun["total"] == 2
            assert (
                client.post("/test-tasks/" + rerun["id"] + "/cancel").json()["status"]
                == "cancelled"
            )
            checks += ["retry_only_not_passed", "cancel_pending"]
            fresh = httpx.get(
                "http://127.0.0.1:8000/api/v1/test-tasks/" + task["id"],
                headers=dict(client.headers),
                trust_env=False,
            )
            assert fresh.json()["completed"] == 3
            settings = Settings()
            engine = make_engine(settings.database_url.get_secret_value())
            with engine.connect() as conn:
                assert (
                    conn.scalar(
                        text("SELECT COUNT(*) FROM test_results WHERE task_id=:id"),
                        {"id": task["id"]},
                    )
                    == 3
                )
                assert (
                    conn.scalar(
                        text(
                            "SELECT COUNT(*) FROM evaluation_details WHERE result_id IN (SELECT id FROM test_results WHERE task_id=:id)"
                        ),
                        {"id": task["id"]},
                    )
                    == 3
                )
                payload = conn.scalar(
                    text("SELECT payload FROM test_results WHERE task_id=:id LIMIT 1"),
                    {"id": task["id"]},
                )
                assert "中文输入" not in payload
            checks += [
                "fresh_http_read",
                "mysql_result_rows",
                "mysql_evaluations",
                "encrypted_result_payload",
            ]
            output = {
                "status": "passed",
                "count": len(checks),
                "checks": checks,
                "task_id": task["id"],
                "retained_test_username": credentials["username"],
                "target": "explicit non-AI local HTTP service",
                "real_model_calls": 0,
            }
            evidence = (
                Path(__file__).resolve().parents[1] / "docs/evidence/stage3-mysql.json"
            )
            evidence.write_text(
                json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(output, ensure_ascii=False, indent=2))
    finally:
        target.shutdown()
        target.server_close()
        worker.join(timeout=2)
        if engine:
            engine.dispose()


if __name__ == "__main__":
    main()
