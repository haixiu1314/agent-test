"""管理操作均要求管理员，默认参数有明确契约，不接收任意秘密配置。"""

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from sqlalchemy import select
from app.schemas.inputs import Input
from app.schemas.platform import ProfileInput, ReportInput
from app.api.v1.routes import database, current_user, admin
from app.api.v1.cases import audit
from app.models.entities import OperationLog
from app.models.platform import SystemParameter, TestTask
from app.services.catalog import paginate
from app.core.security import verify_password, hash_password
from app.services.tasks import task_public

router = APIRouter(prefix="/api/v1", tags=["management"])


@router.put("/auth/password")
def password(
    body: ProfileInput,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(403, "当前密码错误")
    user.password_hash = hash_password(body.new_password)
    audit(db, user, request, "auth.password", user.id)
    return {
        "status": "updated",
        "note": "请重新登录；现有 JWT 最长至原两小时有效期结束",
    }


class ParameterInput(Input):
    value: dict


@router.get("/admin/parameters")
def parameters(user=Depends(admin), db=Depends(database)):
    return {
        "items": [
            {"key": p.key, "value": p.value}
            for p in db.scalars(select(SystemParameter))
        ],
        "supported": ["evaluation_weights", "security_policy"],
    }


@router.put("/admin/parameters/{key}")
def parameter(
    key: str,
    body: ParameterInput,
    request: Request,
    user=Depends(admin),
    db=Depends(database),
):
    if key == "evaluation_weights":
        try:
            ReportInput(task_id="validation", weights=body.value)
        except ValueError:
            raise HTTPException(422, "评分权重格式无效") from None
    elif key == "security_policy":
        tools = body.value.get("forbidden_tools")
        if (
            set(body.value) != {"forbidden_tools"}
            or not isinstance(tools, list)
            or len(tools) > 30
            or any(not isinstance(t, str) or not 1 <= len(t) <= 100 for t in tools)
        ):
            raise HTTPException(422, "安全策略需包含 forbidden_tools 字符串数组")
    else:
        raise HTTPException(422, "不支持此参数")
    row = db.scalar(
        select(SystemParameter).where(SystemParameter.key == key).with_for_update()
    )
    if row:
        row.value = body.value
    else:
        row = SystemParameter(key=key, value=body.value)
        db.add(row)
    db.flush()
    audit(db, user, request, "parameter.update", row.id)
    return {"key": key, "value": row.value}


@router.get("/admin/tasks")
def tasks(page: int = Query(1, ge=1), user=Depends(admin), db=Depends(database)):
    rows, total = paginate(
        db, select(TestTask).order_by(TestTask.created_at.desc()), page, 50
    )
    return {"items": [task_public(db, t) for t in rows], "total": total}


@router.get("/operation-logs")
def logs(page: int = Query(1, ge=1), user=Depends(current_user), db=Depends(database)):
    stmt = select(OperationLog).order_by(
        OperationLog.created_at.desc(), OperationLog.id
    )
    # 个人中心始终只显示本人的日志，包括旧账号。
    stmt = stmt.where(OperationLog.user_id == user.id)
    rows, total = paginate(db, stmt, page, 50)
    return {
        "items": [
            {
                k: getattr(r, k)
                for k in [
                    "id",
                    "user_id",
                    "action",
                    "resource_id",
                    "request_id",
                    "created_at",
                ]
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/admin/storage")
def storage(request: Request, user=Depends(admin)):
    url = request.app.state.engine.url
    return {
        "mysql": {"host": url.host, "port": url.port, "database": url.database},
        "milvus": {
            "database": "default",
            "collection": "rag_document_chunks",
            "creation": "首次成功索引时创建；此接口不代表实际连通或已建集合",
            "evaluation_collection": "未创建 rag_evaluation_vectors，评估不需要持久化额外向量",
        },
    }
