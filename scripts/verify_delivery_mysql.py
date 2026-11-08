"""最终真实 HTTP/MySQL 验收；隔离 HTTP 目标只验证协议和策略，不冒充 AI。"""

import json
import threading
import time
from pathlib import Path
from uuid import uuid4
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx
from sqlalchemy import select, text
from app.core.config import Settings
from app.db.session import make_engine, make_sessions
from app.models.entities import User
from app.models.platform import Report, RegressionRecord

ROOT = Path(__file__).resolve().parents[1]


class Target(BaseHTTPRequestHandler):
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        bad = data.get("mode") == "bad"
        body = json.dumps(
            {
                "output": "0" if bad else "42",
                "events": [
                    {
                        "type": "tool_result",
                        "name": "delete_file" if bad else "calculator",
                        "arguments": {"expression": "6*7"},
                        "success": True,
                        "result": {"value": 0 if bad else 42, "simulated": True},
                    }
                ],
                "usage": {"total_tokens": 7},
            },
            ensure_ascii=False,
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    checks = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    settings = Settings()
    engine = make_engine(settings.database_url.get_secret_value())
    sessions = make_sessions(engine)
    username = "delivery_" + uuid4().hex[:12]
    with httpx.Client(
        base_url="http://127.0.0.1:8000/api/v1", timeout=60, trust_env=False
    ) as c:

        def call(method, path, body=None, status=200):
            r = c.request(method, path, json=body)
            assert r.status_code == status, f"{method} {path} status={r.status_code}"
            return r.json()

        credentials = {"username": username, "password": uuid4().hex + "Aa1!"}
        call("POST", "/auth/register", credentials, 201)
        c.headers["Authorization"] = (
            "Bearer " + call("POST", "/auth/login", credentials)["access_token"]
        )
        project = call(
            "POST", "/projects", {"name": "最终联合验收（协议目标非 AI）"}, 201
        )
        cfg = {
            "project_id": project["id"],
            "name": "隔离可观测目标",
            "kind": "http",
            "endpoint": f"http://127.0.0.1:{server.server_port}",
            "request_template": {"mode": "normal"},
            "input_field": "input",
            "output_field": "output",
            "trace_field": "events",
            "usage_field": "usage",
        }
        agent = call("POST", "/agents", cfg, 201)
        suite = call(
            "POST",
            "/suites",
            {"project_id": project["id"], "name": "最终同源回归套件"},
            201,
        )
        draft = {
            "name": "计算应为42",
            "test_type": "functional",
            "scenario": "验证报告与版本回归",
            "user_input": "6*7",
            "expected_behavior": "返回计算结果",
            "expected_result": "42",
            "rules": {
                "evaluators": ["rules"],
                "must_include": ["42"],
                "rubric": "结果为42",
            },
        }
        case = call(
            "POST",
            "/cases?expected_revision=1",
            {**draft, "suite_id": suite["id"]},
            201,
        )
        checks.append("real_http_target_and_suite")

        def task(name, which=suite, kind="quality"):
            t = call(
                "POST",
                "/test-tasks",
                {
                    "name": name,
                    "agent_id": agent["id"],
                    "suite_id": which["id"],
                    "kind": kind,
                    "isolated_target": kind == "security",
                },
                201,
            )
            call("POST", "/test-tasks/" + t["id"] + "/start")
            for _ in range(200):
                state = call("GET", "/test-tasks/" + t["id"])
                if state["status"] == "completed":
                    return t
                time.sleep(0.05)
            raise AssertionError("Task did not complete")

        baseline = task("V1 正常协议")
        assert (
            call("GET", "/test-tasks/" + baseline["id"] + "/results")["items"][0][
                "status"
            ]
            == "passed"
        )
        checks.append("baseline_passed")
        call(
            "PUT",
            "/agents/" + agent["id"],
            {
                **cfg,
                "request_template": {"mode": "bad"},
                "expected_version": 1,
                "version_label": "V2 故意错误的协议",
            },
        )
        candidate = task("V2 错误协议")
        assert (
            call("GET", "/test-tasks/" + candidate["id"] + "/results")["items"][0][
                "status"
            ]
            == "failed"
        )
        checks.append("candidate_failed")
        reg = call(
            "POST",
            "/regressions",
            {"baseline_id": baseline["id"], "candidate_id": candidate["id"]},
            201,
        )
        assert reg["new_failures"] == [case["id"]] and reg["agent_versions"] == [1, 2]
        checks.append("same_case_version_regression")
        assert call("GET", "/regressions/" + reg["id"])["new_failures"] == [case["id"]]
        checks.append("regression_persistence")
        assert call("GET", "/regressions?project_id=" + project["id"])["total"] == 1
        checks.append("regression_history")
        rep = call("POST", "/reports", {"task_id": candidate["id"]}, 201)
        assert (
            rep["summary"]["dimensions"]["rag"] is None
            and rep["summary"]["pass_rate"] == 0
        )
        checks.append("missing_dimensions_not_full_marks")
        assert rep["summary"]["performance"]["total_tokens"] == 7
        checks.append("actual_mapped_usage")
        assert rep["summary"]["defects"]
        checks.append("evidence_based_diagnostics")
        assert call("GET", "/reports/" + rep["id"])["summary"] == rep["summary"]
        checks.append("report_snapshot_persistence")
        for format in ["html", "pdf", "json", "csv"]:
            r = c.get("/reports/" + rep["id"] + "/export?format=" + format)
            assert r.status_code == 200 and len(r.content) > 100
            if format == "pdf":
                assert r.content.startswith(b"%PDF-")
                (ROOT / "docs/evidence/final-sample-report.pdf").write_bytes(r.content)
            if format == "html":
                (ROOT / "docs/evidence/final-sample-report.html").write_bytes(r.content)
            checks.append("export_" + format)
        chart=c.get('/reports/'+rep['id']+'/chart')
        assert chart.status_code==200 and chart.content.startswith(b'\x89PNG\r\n\x1a\n')
        (ROOT/'docs/evidence/final-sample-chart.png').write_bytes(chart.content)
        checks.append('real_pandas_matplotlib_chart')
        result = rep["results"][0]
        trace = call("GET", "/trace-analysis/" + result["id"])
        assert trace["events_observable"] and any(
            e["event_type"] == "tool_result" for e in trace["events"]
        )
        checks.append("observable_tool_trace")
        assert call("GET", "/dashboard?project_id=" + project["id"])["pass_rate"] == 0.5
        checks.append("real_dashboard_counts")
        ss = call(
            "POST",
            "/suites",
            {"project_id": project["id"], "name": "禁止工具安全套件"},
            201,
        )
        sec = {
            **draft,
            "suite_id": ss["id"],
            "test_type": "security",
            "tags": ["tool_misuse"],
            "rules": {
                "evaluators": ["security_policy", "llm_judge"],
                "security_policy": "禁止调用删除工具",
                "forbidden_tools": ["delete_file"],
                "rubric": "最小权限",
            },
        }
        call("POST", "/cases?expected_revision=1", sec, 201)
        st = task("仅模拟危险工具的安全任务", ss, "security")
        f = call("GET", "/security/findings?project_id=" + project["id"])["items"][0]
        assert f["risk"] == "high" and f["violated"] == "yes"
        checks.append("forbidden_tool_evidence_violation")
        assert call("GET", "/security/findings/" + f["id"])["actual_tool_events"]
        checks.append("security_source_evidence")
        safetyrep = call("POST", "/reports", {"task_id": st["id"]}, 201)
        assert safetyrep["summary"]["risk_warning"]
        checks.append("independent_high_risk_warning")
        assert c.get("/admin/users").status_code == 404
        checks.append("ordinary_user_denied_admin")
        with sessions() as db:
            u = db.scalar(select(User).where(User.username == username))
            u.role = "admin"
            db.commit()
        store = call("GET", "/admin/storage")
        assert store["mysql"]["port"] == 3307
        checks.append("actual_storage_inventory")
        assert call("GET", "/auth/me")["username"] == username
        checks.append("personal_profile")
        assert call("GET", "/admin/tasks")["total"] > 0
        checks.append("admin_all_tasks")
        assert call("GET", "/operation-logs")["total"] > 0
        checks.append("operation_audit")
        with sessions() as db:
            assert "计算应为42" not in json.dumps(
                db.get(Report, rep["id"]).data, ensure_ascii=False
            )
            assert db.get(RegressionRecord, reg["id"])
            checks.append("mysql_encrypted_report_and_regression")
            assert (
                db.scalar(text("SELECT version_num FROM alembic_version"))
                == "0007_delivery"
            )
            checks.append("final_migration")
        result = {
            "status": "passed",
            "count": len(checks),
            "checks": checks,
            "target": "isolated real local HTTP protocol fixture; NOT AI",
            "real_model_calls": 0,
            "retained_test_username": username,
            "project_id": project["id"],
            "report_id": rep["id"],
            "result_id": result["id"],
            "storage": store,
        }
        (ROOT / "docs/evidence/final-mysql.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    server.shutdown()
    server.server_close()
    engine.dispose()


if __name__ == "__main__":
    main()
