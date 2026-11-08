from fastapi import APIRouter, Depends, Request, HTTPException, Query
from sqlalchemy import select
from app.api.v1.routes import database, current_user
from app.api.v1.generation import generate
from app.api.v1.tasks import create, get_task
from app.models.platform import SecurityFinding, TestTask, TestResult, TraceEvent
from app.schemas.cases import GenerationInput
from app.schemas.platform import TaskInput
from app.services.catalog import project_for_user, paginate
from app.services.tasks import task_for_user, SECURITY_CATEGORIES

router = APIRouter(prefix="/api/v1/security", tags=["security"])


@router.get("/categories")
def categories(user=Depends(current_user)):
    return {
        "items": SECURITY_CATEGORIES,
        "target_policy": "仅内置受控工具或本机隔离 HTTP 目标",
    }


@router.post("/generate-cases", status_code=201)
async def generate_security(
    body: GenerationInput,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    if not body.security_categories or body.types != ["security"]:
        raise HTTPException(422, "需要安全类别与 security 类型")
    return await generate(body, request, user, db)


@router.post("/tasks", status_code=201)
def create_security(
    body: TaskInput, request: Request, user=Depends(current_user), db=Depends(database)
):
    if body.kind != "security":
        raise HTTPException(422, "任务类型必须为 security")
    return create(body, request, user, db)


@router.get("/tasks/{task_id}")
def security_task(task_id: str, user=Depends(current_user), db=Depends(database)):
    task = task_for_user(db, task_id, user)
    if task.kind != "security":
        raise HTTPException(404, "安全任务不存在")
    return get_task(task_id, user, db)


@router.get("/findings")
def findings(
    project_id: str,
    page: int = Query(1, ge=1),
    user=Depends(current_user),
    db=Depends(database),
):
    project_for_user(db, project_id, user)
    rows, total = paginate(
        db,
        select(SecurityFinding)
        .join(TestTask)
        .where(TestTask.project_id == project_id)
        .order_by(SecurityFinding.created_at.desc()),
        page,
        50,
    )
    return {
        "items": [
            {
                k: getattr(r, k)
                for k in [
                    "id",
                    "task_id",
                    "result_id",
                    "category",
                    "risk",
                    "violated",
                    "detail",
                    "created_at",
                ]
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/findings/{finding_id}")
def finding(
    finding_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    item = db.get(SecurityFinding, finding_id)
    if not item:
        raise HTTPException(404, "风险记录不存在")
    task_for_user(db, item.task_id, user)
    result = db.get(TestResult, item.result_id)
    events = db.scalars(
        select(TraceEvent).where(
            TraceEvent.result_id == result.id, TraceEvent.event_type == "tool_result"
        )
    ).all()
    return (
        {
            k: getattr(item, k)
            for k in [
                "id",
                "task_id",
                "result_id",
                "category",
                "risk",
                "violated",
                "detail",
            ]
        }
        | request.app.state.vault.decrypt(result.payload)
        | {
            "actual_tool_events": [
                request.app.state.vault.decrypt(e.payload) for e in events
            ]
        }
    )
