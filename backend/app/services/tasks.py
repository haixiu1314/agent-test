"""单进程持久化任务执行器。每条用例独立事务，控制状态在调度边界生效。"""

import asyncio
import time
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select, delete, update
from app.models.platform import (
    TestTask,
    TestResult,
    EvaluationDetail,
    TraceEvent,
    SecurityFinding,
)
from app.models.entities import AgentVersion, TestSuiteVersion
from app.services.catalog import project_for_user, agent_for_user
from app.services.cases import suite_for_user
from app.services.models import resolve_model, resolve_embedding
from app.services.evaluation import evaluate, aggregate
from app.services.rag import make_retriever
from app.adapters.http import HttpAgentAdapter
from app.adapters.local import local_adapter
from app.adapters.enterprise import EnterpriseAdapter
from app.adapters.base import AdapterError


def now():
    return datetime.now(timezone.utc).isoformat()


def task_for_user(db, task_id, user, lock=False):
    stmt = select(TestTask).where(TestTask.id == task_id)
    if lock:
        stmt = stmt.with_for_update()
    task = db.scalar(stmt)
    if not task:
        raise HTTPException(404, "测试任务不存在")
    project_for_user(db, task.project_id, user)
    return task


def task_public(db, task):
    rows = db.scalars(select(TestResult).where(TestResult.task_id == task.id)).all()
    counts = {
        state: sum(r.status == state for r in rows)
        for state in [
            "pending",
            "running",
            "passed",
            "failed",
            "error",
            "inconclusive",
            "cancelled",
        ]
    }
    completed = sum(
        counts[s] for s in ["passed", "failed", "error", "inconclusive", "cancelled"]
    )
    return {
        k: getattr(task, k)
        for k in [
            "id",
            "project_id",
            "agent_id",
            "suite_id",
            "name",
            "status",
            "kind",
            "config",
            "error_code",
            "started_at",
            "finished_at",
            "created_at",
        ]
    } | {
        "agent_version": task.snapshot["agent"]["version"],
        "suite_revision": task.snapshot["suite_revision"],
        "total": len(rows),
        "completed": completed,
        "counts": counts,
    }


def create_task(db, body, user, app):
    agent = agent_for_user(db, body.agent_id, user)
    if body.knowledge_base_id:
        from app.services.rag import kb_for_user
        kb=kb_for_user(db,body.knowledge_base_id,user)
        if kb.project_id!=agent.project_id:
            raise HTTPException(422,'知识库必须属于 Agent 项目')
    suite = suite_for_user(db, body.suite_id, user)
    if suite.project_id != agent.project_id:
        raise HTTPException(422, "Agent 与测试套件必须属于同一项目")
    agent_version = body.agent_version or agent.version
    av = db.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == agent_version
        )
    )
    revision = body.suite_revision or suite.revision
    sv = db.scalar(
        select(TestSuiteVersion).where(
            TestSuiteVersion.suite_id == suite.id, TestSuiteVersion.revision == revision
        )
    )
    if not av or not sv:
        raise HTTPException(404, "指定快照版本不存在")
    from copy import deepcopy
    cases = deepcopy(sv.snapshot["cases"])
    if body.case_ids:
        if not set(body.case_ids).issubset({c["id"] for c in cases}):
            raise HTTPException(422, "用例不在指定套件版本中")
        cases = [c for c in cases if c["id"] in body.case_ids]
    if not cases:
        raise HTTPException(422, "套件中没有可执行用例")
    if body.kind == "security":
        from app.models.platform import SystemParameter
        param = db.scalar(select(SystemParameter).where(SystemParameter.key == 'security_policy'))
        if param:
            for case in cases:
                case['rules']['forbidden_tools'] = sorted(set(case['rules'].get('forbidden_tools', [])) | set(param.value['forbidden_tools']))
        if any(c["test_type"] != "security" for c in cases):
            raise HTTPException(422, "安全任务只能选择安全用例")
        if av.snapshot["kind"] == "http":
            from urllib.parse import urlsplit

            if urlsplit(av.snapshot["endpoint"]).hostname not in [
                "127.0.0.1",
                "localhost",
                "::1",
            ]:
                raise HTTPException(422, "安全测试 HTTP 目标必须为本机隔离测试服务")
    public_models = {}
    secrets = {"agent": app.state.vault.decrypt(av.secret), "models": {}}
    for name, purpose in [
        ("judge", "judge"),
        ("rag", "rag"),
        ("embedding", "embedding"),
        ("demo", "demo"),
    ]:
        model_id = getattr(
            body, ("demo_model_id" if name == "demo" else name + "_model_id")
        )
        try:
            config, key = (
                resolve_embedding(db, app.state.settings, app.state.vault, model_id, user_id=user.id)
                if name == "embedding"
                else resolve_model(
                    db, app.state.settings, app.state.vault, model_id, purpose, user_id=user.id
                )
            )
        except HTTPException:
            if model_id:
                raise
            public_models[name] = {"available": False}
            continue
        public_models[name] = {"available": True, **config}
        secrets["models"][name] = {"config": config, "key": key}
    snapshot = {
        "agent": av.snapshot,
        "suite_revision": revision,
        "cases": cases,
        "models": public_models,
    }
    task = TestTask(
        project_id=agent.project_id,
        agent_id=agent.id,
        suite_id=suite.id,
        owner_id=user.id,
        name=body.name,
        kind=body.kind,
        config=body.model_dump(mode="json"),
        snapshot=snapshot,
        secrets=app.state.vault.encrypt(secrets),
    )
    db.add(task)
    db.flush()
    for case in cases:
        db.add(
            TestResult(
                task_id=task.id,
                case_key=case["id"],
                case_name=case["name"],
                test_type=case["test_type"],
                payload=app.state.vault.encrypt({"case": case}),
            )
        )
    db.flush()
    return task


def event(
    db,
    app,
    task_id,
    result_id,
    kind,
    name,
    data,
    status="ok",
    duration=None,
    parent=None,
):
    item = TraceEvent(
        task_id=task_id,
        result_id=result_id,
        event_type=kind,
        event_name=name[:160],
        status=status,
        duration_ms=duration,
        parent_event_id=parent,
        payload=app.state.vault.encrypt(data),
    )
    db.add(item)
    db.flush()
    return item.id


class TaskManager:
    """并发限于每任务配置；单个进程最多三个活跃任务。重启后任务需人工恢复。"""

    def __init__(self, app):
        self.app, self.running = app, {}

    def schedule(self, task_id: str) -> None:
        if task_id in self.running:
            raise HTTPException(409, "任务仍在处理控制请求，请稍后重试")
        if len(self.running) >= 3:
            raise HTTPException(429, "当前最多同时运行三个任务")
        job = asyncio.create_task(self.run(task_id))
        self.running[task_id] = job
        job.add_done_callback(lambda _: self.running.pop(task_id, None))

    async def shutdown(self) -> None:
        for job in list(self.running.values()):
            job.cancel()
        if self.running:
            await asyncio.gather(*list(self.running.values()), return_exceptions=True)

    async def run(self, task_id: str) -> None:
        app = self.app
        try:
            with app.state.sessions() as db:
                task = db.get(TestTask, task_id)
                config = task.config
                snapshot = task.snapshot
                secret = app.state.vault.decrypt(task.secrets)
            semaphore = asyncio.Semaphore(config["concurrency"])

            async def execute(case):
                async with semaphore:
                    with app.state.sessions() as db:
                        task = db.get(TestTask, task_id)
                        if task.status != "running":
                            return
                        result = db.scalar(
                            select(TestResult).where(
                                TestResult.task_id == task_id,
                                TestResult.case_key == case["id"],
                            )
                        )
                        if result.status != "pending":
                            return
                        result.status = "running"
                        db.commit()
                        result_id = result.id
                    await self.execute_case(
                        task_id, result_id, case, config, snapshot, secret
                    )

            await asyncio.gather(*(execute(c) for c in snapshot["cases"]))
            with app.state.sessions() as db:
                task = db.get(TestTask, task_id)
                if task.status == "cancel_requested":
                    for result in db.scalars(
                        select(TestResult).where(
                            TestResult.task_id == task_id,
                            TestResult.status == "pending",
                        )
                    ):
                        result.status = "cancelled"
                        result.error_code = "task_cancelled"
                    task.status = "cancelled"
                elif task.status == "pause_requested":
                    task.status = "paused"
                elif task.status == "running":
                    task.status = "completed"
                if task.status in ["completed", "cancelled"]:
                    task.finished_at = now()
                db.commit()
        except asyncio.CancelledError:
            with app.state.sessions() as db:
                task = db.get(TestTask, task_id)
                task.status = "interrupted"
                task.error_code = "server_stopped"
                db.commit()
            raise
        except Exception as exc:
            with app.state.sessions() as db:
                db.execute(
                    update(TestResult)
                    .where(
                        TestResult.task_id == task_id, TestResult.status == "running"
                    )
                    .values(status="error", error_code="execution_interrupted")
                )
                task = db.get(TestTask, task_id)
                task.status = "error"
                task.error_code = "runner_" + type(exc).__name__
                db.commit()

    async def execute_case(self, task_id, result_id, case, config, snapshot, secret):
        app = self.app
        started = time.perf_counter()
        response = None
        error = None
        attempts = 0
        details = []
        response_ms = None
        status = "error"
        root = None
        try:
            with app.state.sessions() as db:
                # 中断恢复时清理该条调用的旧事件，保留已完成用例。
                db.execute(delete(TraceEvent).where(TraceEvent.result_id == result_id))
                db.execute(
                    delete(EvaluationDetail).where(
                        EvaluationDetail.result_id == result_id
                    )
                )
                root = event(
                    db,
                    app,
                    task_id,
                    result_id,
                    "input",
                    "用户输入",
                    {"input": case["user_input"], "history": case.get("history", [])},
                )
                db.commit()
            for attempt in range(config["retries"] + 1):
                attempts = attempt + 1
                try:
                    agent = snapshot["agent"]
                    if agent["kind"] == "http":
                        adapter = HttpAgentAdapter(
                            {**agent, "retries": 0}, secret["agent"]
                        )
                    elif agent["adapter_name"] == "enterprise_demo":
                        model = secret["models"].get("demo")
                        if not model:
                            raise AdapterError("model_not_configured")
                        adapter = EnterpriseAdapter(
                            model["config"], model["key"], config["demo_defect"],
                            make_retriever(app, config['knowledge_base_id']) if config.get('knowledge_base_id') else None
                        )
                    else:
                        adapter = local_adapter(agent["adapter_name"])
                    response = await asyncio.wait_for(
                        adapter.invoke(case["user_input"], case.get("history", [])),
                        config["timeout_seconds"],
                    )
                    break
                except (AdapterError, TimeoutError) as exc:
                    error = (
                        exc.code if isinstance(exc, AdapterError) else "case_timeout"
                    )
                    with app.state.sessions() as db:
                        event(
                            db,
                            app,
                            task_id,
                            result_id,
                            "retry" if attempt < config["retries"] else "exception",
                            error,
                            {"attempt": attempt + 1, "error_code": error},
                            "error",
                            parent=root,
                        )
                        db.commit()
                    if attempt == config["retries"]:
                        raise AdapterError(error)
                    await asyncio.sleep(0.1)
            duration = (time.perf_counter() - started) * 1000
            response_ms = duration
            response.attempts = attempts
            models = {
                name: (m["config"], m["key"]) for name, m in secret["models"].items()
            }
            details = await asyncio.wait_for(
                evaluate(case, response, duration, models), 180
            )
            status = aggregate(details)
            error = None
        except asyncio.CancelledError:
            status, error = "error", "execution_interrupted"
            raise
        except Exception as exc:
            status = "error"
            error = (
                exc.code
                if isinstance(exc, AdapterError)
                else "execution_" + type(exc).__name__
            )
        finally:
            duration = round((time.perf_counter() - started) * 1000, 2)
            with app.state.sessions() as db:
                result = db.get(TestResult, result_id)
                (
                    result.status,
                    result.duration_ms,
                    result.attempts,
                    result.error_code,
                ) = (
                    status,
                    response_ms if response_ms is not None else duration,
                    attempts,
                    error,
                )
                payload = {"case": case}
                if response:
                    payload.update(
                        {
                            "output": response.output,
                            "status_code": response.status_code,
                            "events_observable": response.events_observable,
                            "contexts": response.contexts,
                            "tool_call_count": sum(
                                e.get("type") == "tool_call"
                                for e in response.observable_events
                            )
                            if any(
                                e.get("type") == "tool_call"
                                for e in response.observable_events
                            )
                            else sum(
                                e.get("type") == "tool_result"
                                for e in response.observable_events
                            )
                            if response.events_observable
                            else None,
                        }
                    )
                    result.usage = response.usage
                    for raw in response.observable_events:
                        kind = str(raw.get("type", "target_event"))
                        event(
                            db,
                            app,
                            task_id,
                            result_id,
                            kind,
                            str(raw.get("name", kind)),
                            raw,
                            "error" if raw.get("success") is False else "ok",
                            raw.get("duration_ms"),
                            root,
                        )
                    event(
                        db,
                        app,
                        task_id,
                        result_id,
                        "output",
                        "最终回答",
                        {
                            "output": response.output,
                            "tool_events": "observable"
                            if response.events_observable
                            else "不可观测",
                        },
                        parent=root,
                    )
                result.payload = app.state.vault.encrypt(payload)
                for d in details:
                    db.add(EvaluationDetail(result_id=result_id, **d))
                if case["test_type"] == "security":
                    verdicts = [
                        d["detail"].get("verdict")
                        for d in details
                        if d["detail"].get("verdict")
                    ]
                    verdict = verdicts[0] if verdicts else None
                    db.add(
                        SecurityFinding(
                            task_id=task_id,
                            result_id=result_id,
                            category=next(
                                (
                                    t
                                    for t in case.get("tags", [])
                                    if t in SECURITY_CATEGORIES
                                ),
                                "unspecified",
                            ),
                            risk=verdict["risk"] if verdict else "unknown",
                            violated=("no" if verdict["passed"] else "yes")
                            if verdict
                            else "unknown",
                            detail={
                                "reason": verdict["reason"]
                                if verdict
                                else "证据或评估不可用，未作安全结论",
                                "recommendation": verdict["recommendation"]
                                if verdict
                                else "补齐配置和可观测证据后复测",
                            },
                        )
                    )
                event(
                    db,
                    app,
                    task_id,
                    result_id,
                    "evaluation",
                    "评估结束",
                    {"status": status, "error_code": error},
                    status,
                    duration,
                    root,
                )
                db.commit()


SECURITY_CATEGORIES = [
    "prompt_injection",
    "jailbreak",
    "role_manipulation",
    "sensitive_data_leakage",
    "tool_misuse",
    "excessive_agency",
    "rag_poisoning",
    "multi_turn_attack",
]
