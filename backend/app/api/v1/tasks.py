import asyncio
import json
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from app.api.v1.routes import database, current_user
from app.api.v1.cases import audit
from app.schemas.platform import TaskInput
from app.models.platform import TestTask, TestResult, EvaluationDetail, TraceEvent
from app.services.catalog import project_for_user, paginate
from app.services.tasks import create_task, task_for_user, task_public, now

router = APIRouter(prefix="/api/v1", tags=["tasks-traces"])


@router.post("/test-tasks", status_code=201)
def create(
    body: TaskInput, request: Request, user=Depends(current_user), db=Depends(database)
):
    task = create_task(db, body, user, request.app)
    audit(db, user, request, "task.create", task.id)
    return task_public(db, task)


@router.get("/test-tasks")
def listing(
    project_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(current_user),
    db=Depends(database),
):
    project_for_user(db, project_id, user)
    rows, total = paginate(
        db,
        select(TestTask)
        .where(TestTask.project_id == project_id)
        .order_by(TestTask.created_at.desc()),
        page,
        page_size,
    )
    return {"items": [task_public(db, r) for r in rows], "total": total}


@router.get("/test-tasks/{task_id}")
@router.get("/test-tasks/{task_id}/progress")
def get_task(task_id: str, user=Depends(current_user), db=Depends(database)):
    return task_public(db, task_for_user(db, task_id, user))


@router.post("/test-tasks/{task_id}/start")
async def start(
    task_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    task = task_for_user(db, task_id, user, True)
    if task.status not in ["pending", "paused", "interrupted"]:
        raise HTTPException(409, "仅待执行、已暂停或已中断任务可以开始")
    if task.status == "interrupted":
        # 已完成结果保留；只重新领取重启时中断的调用。
        for result in db.scalars(
            select(TestResult).where(
                TestResult.task_id == task.id,
                TestResult.error_code == "execution_interrupted",
            )
        ):
            result.status = "pending"
            result.error_code = None
    manager = request.app.state.task_manager
    # schedule 在当前 event loop 同步完成；commit 先于实际后台执行。
    manager.schedule(task.id)
    task.status = "running"
    task.started_at = task.started_at or now()
    task.error_code = None
    try:
        audit(db, user, request, "task.start", task.id)
    except Exception:
        manager.running[task.id].cancel()
        raise
    return task_public(db, task)


@router.post("/test-tasks/{task_id}/pause")
def pause(
    task_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    task = task_for_user(db, task_id, user, True)
    if task.status != "running":
        raise HTTPException(409, "任务不在运行")
    task.status = "pause_requested"
    audit(db, user, request, "task.pause", task.id)
    return {"status": task.status, "note": "当前在途用例完成后暂停，不再领取新用例"}


@router.post("/test-tasks/{task_id}/cancel")
def cancel(
    task_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    task = task_for_user(db, task_id, user, True)
    if task.status not in [
        "pending",
        "paused",
        "interrupted",
        "running",
        "pause_requested",
    ]:
        raise HTTPException(409, "任务不能取消")
    if task.status in ["pending", "paused", "interrupted"]:
        task.status = "cancelled"
        task.finished_at = now()
        for r in db.scalars(
            select(TestResult).where(
                TestResult.task_id == task.id, TestResult.status == "pending"
            )
        ):
            r.status = "cancelled"
    else:
        task.status = "cancel_requested"
    audit(db, user, request, "task.cancel", task.id)
    return {
        "status": task.status,
        "note": "在途调用受超时保护；当前用例完成后终止后续调度",
    }


@router.post("/test-tasks/{task_id}/retry-failed", status_code=201)
def retry_failed(
    task_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    original = task_for_user(db, task_id, user)
    if original.status not in ["completed", "cancelled", "error", "interrupted"]:
        raise HTTPException(409, "请等待任务结束")
    failed = db.scalars(
        select(TestResult).where(
            TestResult.task_id == task_id,
            TestResult.status.in_(
                ["failed", "error", "inconclusive", "cancelled", "pending", "running"]
            ),
        )
    ).all()
    if not failed:
        raise HTTPException(409, "没有需要重跑的用例")
    keys = {r.case_key for r in failed}
    snapshot = {
        **original.snapshot,
        "cases": [c for c in original.snapshot["cases"] if c["id"] in keys],
    }
    task = TestTask(
        project_id=original.project_id,
        agent_id=original.agent_id,
        suite_id=original.suite_id,
        owner_id=user.id,
        name=(original.name + " · 重跑")[:160],
        kind=original.kind,
        config=original.config,
        snapshot=snapshot,
        secrets=original.secrets,
    )
    db.add(task)
    db.flush()
    for case in snapshot["cases"]:
        db.add(
            TestResult(
                task_id=task.id,
                case_key=case["id"],
                case_name=case["name"],
                test_type=case["test_type"],
                payload=request.app.state.vault.encrypt({"case": case}),
            )
        )
    audit(db, user, request, "task.retry", task.id)
    return task_public(db, task)


@router.get("/test-tasks/{task_id}/results")
def results(
    task_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(current_user),
    db=Depends(database),
):
    task_for_user(db, task_id, user)
    rows, total = paginate(
        db,
        select(TestResult)
        .where(TestResult.task_id == task_id)
        .order_by(TestResult.created_at, TestResult.id),
        page,
        page_size,
    )
    items = []
    for r in rows:
        details = db.scalars(
            select(EvaluationDetail).where(EvaluationDetail.result_id == r.id)
        ).all()
        payload = request.app.state.vault.decrypt(r.payload)
        items.append(
            {
                k: getattr(r, k)
                for k in [
                    "id",
                    "case_key",
                    "case_name",
                    "test_type",
                    "status",
                    "duration_ms",
                    "attempts",
                    "usage",
                    "error_code",
                ]
            }
            | payload
            | {
                "evaluations": [
                    {
                        "evaluator": d.evaluator,
                        "status": d.status,
                        "score": d.score,
                        "detail": d.detail,
                    }
                    for d in details
                ]
            }
        )
    return {"items": items, "total": total}


@router.get("/test-tasks/{task_id}/events")
async def progress_events(task_id: str, request: Request, user=Depends(current_user)):
    app = request.app
    with app.state.sessions() as db:
        task_for_user(db, task_id, user)

    async def stream():
        for _ in range(120):
            if await request.is_disconnected():
                return
            with app.state.sessions() as db:
                task = task_for_user(db, task_id, user)
                data = task_public(db, task)
            yield (
                "event: progress\ndata: "
                + json.dumps(data, default=str, ensure_ascii=False)
                + "\n\n"
            )
            if data["status"] not in ["running", "pause_requested", "cancel_requested"]:
                return
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )


@router.get("/traces")
def traces(task_id: str, user=Depends(current_user), db=Depends(database)):
    task_for_user(db, task_id, user)
    rows = db.scalars(
        select(TestResult)
        .where(TestResult.task_id == task_id)
        .order_by(TestResult.created_at)
    ).all()
    return {
        "items": [
            {
                "trace_id": r.id,
                "task_id": task_id,
                "case_id": r.case_key,
                "case_name": r.case_name,
                "status": r.status,
            }
            for r in rows
        ]
    }


@router.get("/traces/{trace_id}")
@router.get("/traces/{trace_id}/events")
def trace(
    trace_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    result = db.get(TestResult, trace_id)
    if not result:
        raise HTTPException(404, "轨迹不存在")
    task_for_user(db, result.task_id, user)
    rows = db.scalars(
        select(TraceEvent)
        .where(TraceEvent.result_id == trace_id)
        .order_by(TraceEvent.created_at, TraceEvent.id)
    ).all()
    return {
        "trace_id": trace_id,
        "task_id": result.task_id,
        "case_id": result.case_key,
        "case": request.app.state.vault.decrypt(result.payload)["case"],
        "items": [
            {
                "event_id": e.id,
                "parent_event_id": e.parent_event_id,
                "event_type": e.event_type,
                "event_name": e.event_name,
                "duration_ms": e.duration_ms,
                "status": e.status,
                "timestamp": e.created_at,
                **request.app.state.vault.decrypt(e.payload),
            }
            for e in rows
        ],
    }


@router.get("/traces/{trace_id}/compare/{other_id}")
def compare_traces(
    trace_id: str,
    other_id: str,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    left = trace(trace_id, request, user, db)
    right = trace(other_id, request, user, db)
    return {"baseline": left, "candidate": right, "observable_only": True}
