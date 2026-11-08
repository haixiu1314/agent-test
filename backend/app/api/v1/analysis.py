"""安全事件轨迹、报告、回归与项目统计的持久化 API。"""

from typing import Literal
from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from app.api.v1.routes import database, current_user
from app.api.v1.cases import audit
from app.models.platform import (
    TestTask,
    TestResult,
    Report,
    RegressionRecord,
    SystemParameter,
)
from app.schemas.platform import ReportInput, RegressionInput
from app.services.catalog import project_for_user, paginate
from app.services.tasks import task_for_user
from app.services.analysis import build_report, results_for, compare_tasks, mean
from app.services.exports import export_report

router = APIRouter(prefix="/api/v1", tags=["analysis-reports-regression"])


@router.get("/report-options")
def report_options(user=Depends(current_user), db=Depends(database)):
    param = db.scalar(
        select(SystemParameter).where(SystemParameter.key == "evaluation_weights")
    )
    return {
        "weights": param.value if param else ReportInput(task_id="defaults").weights
    }


@router.get("/trace-analysis/{result_id}")
def trace(
    result_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    row = db.get(TestResult, result_id)
    if not row:
        raise HTTPException(404, "执行结果不存在")
    task = task_for_user(db, row.task_id, user)
    result = next(r for r in results_for(db, request.app, task) if r["id"] == result_id)
    return {
        "task_id": task.id,
        "result_id": result_id,
        "case": result["case"],
        "events_observable": result.get("events_observable", False),
        "events": result["events"],
        "note": "仅展示真实采集事件，不展示或推断模型内部思维链",
    }


@router.get("/dashboard")
def dashboard(
    project_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    project_for_user(db, project_id, user)
    tasks = db.scalars(
        select(TestTask)
        .where(TestTask.project_id == project_id)
        .order_by(TestTask.created_at.desc())
    ).all()
    rows = db.scalars(
        select(TestResult).join(TestTask).where(TestTask.project_id == project_id)
    ).all()
    from collections import Counter

    counts = dict(Counter(r.status for r in rows))
    times = [r.duration_ms for r in rows if r.duration_ms is not None]
    return {
        "task_count": len(tasks),
        "result_count": len(rows),
        "counts": counts,
        "pass_rate": sum(r.status == "passed" for r in rows) / len(rows)
        if rows
        else None,
        "average_ms": mean(times),
        "trend": [
            {
                "id": t.id,
                "name": t.name,
                "date": t.created_at.isoformat(),
                "status": t.status,
            }
            for t in tasks[:30]
        ][::-1],
    }


@router.post("/reports", status_code=201)
def create_report(
    body: ReportInput,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    task = task_for_user(db, body.task_id, user)
    param = db.scalar(
        select(SystemParameter).where(SystemParameter.key == "evaluation_weights")
    )
    weights = (
        param.value
        if "weights" not in body.model_fields_set and param
        else body.weights
    )
    data = build_report(db, request.app, task, weights)
    row = Report(
        task_id=task.id,
        name=task.name[:150] + " 测试报告",
        data={"encrypted": request.app.state.vault.encrypt(data)},
    )
    db.add(row)
    db.flush()
    audit(db, user, request, "report.create", row.id)
    return {"id": row.id, "task_id": task.id, "name": row.name, **data}


def owned_report(db, request, user, report_id):
    row = db.get(Report, report_id)
    if not row:
        raise HTTPException(404, "报告不存在")
    task_for_user(db, row.task_id, user)
    return row, request.app.state.vault.decrypt(row.data["encrypted"])


@router.get("/reports/{report_id}/chart")
def chart(
    report_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    from app.services.charts import report_chart

    _, data = owned_report(db, request, user, report_id)
    return Response(report_chart(data), media_type="image/png")


@router.get("/reports")
def reports(
    project_id: str,
    page: int = Query(1, ge=1),
    user=Depends(current_user),
    db=Depends(database),
):
    project_for_user(db, project_id, user)
    rows, total = paginate(
        db,
        select(Report)
        .join(TestTask)
        .where(TestTask.project_id == project_id)
        .order_by(Report.created_at.desc()),
        page,
        50,
    )
    return {
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "task_id": r.task_id,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/reports/{report_id}")
def get_report(
    report_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    row, data = owned_report(db, request, user, report_id)
    return {"id": row.id, "name": row.name, "task_id": row.task_id, **data}


@router.get("/reports/{report_id}/export")
def export(
    report_id: str,
    request: Request,
    format: Literal["html", "pdf", "json", "csv"] = "html",
    user=Depends(current_user),
    db=Depends(database),
):
    row, data = owned_report(db, request, user, report_id)
    raw, mime = export_report(data, format)
    return Response(
        raw,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="agenttestlab-{row.id}.{format}"',
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    )


@router.post("/regressions", status_code=201)
def regression(
    body: RegressionInput,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    a = task_for_user(db, body.baseline_id, user)
    b = task_for_user(db, body.candidate_id, user)
    data = compare_tasks(db, request.app, a, b)
    row = RegressionRecord(
        project_id=a.project_id,
        baseline_id=a.id,
        candidate_id=b.id,
        data={"encrypted": request.app.state.vault.encrypt(data)},
    )
    db.add(row)
    db.flush()
    audit(db, user, request, "regression.create", row.id)
    return {"id": row.id, **data}


@router.get("/regressions")
def regressions(
    project_id: str,
    page: int = Query(1, ge=1),
    user=Depends(current_user),
    db=Depends(database),
):
    project_for_user(db, project_id, user)
    rows, total = paginate(
        db,
        select(RegressionRecord)
        .where(RegressionRecord.project_id == project_id)
        .order_by(RegressionRecord.created_at.desc()),
        page,
        50,
    )
    return {
        "items": [
            {
                "id": r.id,
                "baseline_id": r.baseline_id,
                "candidate_id": r.candidate_id,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/regressions/{record_id}")
def get_regression(
    record_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    row = db.get(RegressionRecord, record_id)
    if not row:
        raise HTTPException(404, "对比不存在")
    project_for_user(db, row.project_id, user)
    return {"id": row.id, **request.app.state.vault.decrypt(row.data["encrypted"])}
