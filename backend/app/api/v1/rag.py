"""知识库 API；外部向量调用前取得库级操作锁，失败不丢失来源与证据。"""

import asyncio
import hashlib
from uuid import uuid4
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from sqlalchemy import select, delete, func
from app.api.v1.routes import database, current_user
from app.api.v1.cases import audit
from app.schemas.platform import (
    KnowledgeInput,
    DocumentInput,
    QualityInput,
    RagEvaluationInput,
    RetrieveInput,
    DatasetInput,
    GenerateQuestions,
)
from app.models.platform import (
    KnowledgeBase,
    RagDocument,
    RagChunk,
    RagIssue,
    RagEvaluation,
    RagDataset,
)
from app.services.catalog import project_for_user, paginate
from app.services.models import resolve_embedding, resolve_model
from app.services.rag import (
    kb_for_user,
    kb_operation,
    parse_document,
    chunks_from_pages,
    index_document,
    retrieve,
    quality_issues,
    judge_conflict,
    semantic_pairs,
)
from app.services.rag_evaluation import run_evaluation, generate_questions
from app.integrations.milvus import MilvusService

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


def kb_public(kb):
    return {
        k: getattr(kb, k)
        for k in [
            "id",
            "project_id",
            "name",
            "description",
            "config",
            "status",
            "created_at",
        ]
    }


def apply_kb(kb, body, request, db, user):
    config = body.model_dump(exclude={"project_id", "name", "description"})
    secret = {}
    try:
        model, key = resolve_embedding(
            db,
            request.app.state.settings,
            request.app.state.vault,
            body.embedding_model_id,
            user_id=user.id,
        )
        secret["embedding"] = {"config": model, "key": key}
        config["embedding"] = model
    except HTTPException:
        if body.embedding_model_id:
            raise
        config["embedding"] = {"available": False}
    kb.name, kb.description, kb.config, kb.secrets = (
        body.name,
        body.description,
        config,
        request.app.state.vault.encrypt(secret),
    )


@router.post("/knowledge-bases", status_code=201)
def create_kb(
    body: KnowledgeInput,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    project_for_user(db, body.project_id, user)
    kb = KnowledgeBase(project_id=body.project_id)
    apply_kb(kb, body, request, db, user)
    db.add(kb)
    db.flush()
    audit(db, user, request, "rag.kb.create", kb.id)
    return kb_public(kb)


@router.get("/knowledge-bases")
def bases(project_id: str, user=Depends(current_user), db=Depends(database)):
    project_for_user(db, project_id, user)
    return {
        "items": [
            kb_public(k)
            for k in db.scalars(
                select(KnowledgeBase)
                .where(KnowledgeBase.project_id == project_id)
                .order_by(KnowledgeBase.created_at.desc())
            )
        ]
    }


@router.put("/knowledge-bases/{kb_id}")
def update_kb(
    kb_id: str,
    body: KnowledgeInput,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    kb = kb_for_user(db, kb_id, user)
    with kb_operation(request.app, kb_id):
        if kb.project_id != body.project_id:
            raise HTTPException(422, "不允许移动知识库")
        docs = db.scalars(select(RagDocument).where(RagDocument.kb_id == kb_id)).all()
        # 只允许在所有文档尚未触及向量库时重配模型/维度；分块配置变化需重新解析。
        if any(d.status != "parsed" for d in docs):
            raise HTTPException(409, "请先删除曾尝试索引的文档，避免模型和残留向量混用")
        if docs and (
            body.chunk_size != kb.config["chunk_size"]
            or body.overlap != kb.config["overlap"]
        ):
            raise HTTPException(409, "修改分块大小前请删除文档并重新上传")
        apply_kb(kb, body, request, db, user)
        audit(db, user, request, "rag.kb.update", kb.id)
        return kb_public(kb)


@router.post("/knowledge-bases/{kb_id}/documents", status_code=201)
def upload(
    kb_id: str,
    body: DocumentInput,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    kb = kb_for_user(db, kb_id, user)
    with kb_operation(request.app, kb_id):
        raw, pages = parse_document(body.name, body.content_base64)
        if len(body.name.encode()) > 512:
            raise HTTPException(422, "文件名 UTF-8 长度超过 512 字节")
        chunks = chunks_from_pages(pages, kb.config["chunk_size"], kb.config["overlap"])
        if (
            db.scalar(
                select(func.count())
                .select_from(RagDocument)
                .where(RagDocument.kb_id == kb_id)
            )
            >= 100
        ):
            raise HTTPException(422, "每库最多 100 文档，请拆分知识库")
        doc = RagDocument(
            kb_id=kb_id,
            name=body.name,
            content_hash=hashlib.sha256(raw).hexdigest(),
            source=request.app.state.vault.encrypt(
                {"base64": body.content_base64, "pages": pages}
            ),
        )
        db.add(doc)
        db.flush()
        db.add_all([RagChunk(kb_id=kb_id, document_id=doc.id, **c) for c in chunks])
        audit(db, user, request, "rag.document.upload", doc.id)
        return {
            "id": doc.id,
            "name": doc.name,
            "status": doc.status,
            "chunk_count": len(chunks),
            "indexed": False,
        }


@router.get("/knowledge-bases/{kb_id}/documents")
def documents(kb_id: str, user=Depends(current_user), db=Depends(database)):
    kb_for_user(db, kb_id, user)
    rows = db.execute(
        select(RagDocument, func.count(RagChunk.id))
        .outerjoin(RagChunk, RagChunk.document_id == RagDocument.id)
        .where(RagDocument.kb_id == kb_id)
        .group_by(RagDocument.id)
        .order_by(RagDocument.created_at)
    ).all()
    return {
        "items": [
            {
                k: getattr(d, k)
                for k in ["id", "name", "status", "error_code", "created_at"]
            }
            | {"chunk_count": count}
            for d, count in rows
        ]
    }


def document_for_kb(db, kb_id, doc_id):
    doc = db.get(RagDocument, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(404, "文档不存在")
    return doc


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/chunks")
def chunks(
    kb_id: str,
    doc_id: str,
    page: int = Query(1, ge=1),
    user=Depends(current_user),
    db=Depends(database),
):
    kb_for_user(db, kb_id, user)
    document_for_kb(db, kb_id, doc_id)
    rows, total = paginate(
        db,
        select(RagChunk)
        .where(RagChunk.document_id == doc_id)
        .order_by(RagChunk.position),
        page,
        50,
    )
    return {
        "items": [
            {
                "id": c.id,
                "content": c.content,
                "page_number": c.page_number,
                "position": c.position,
                "metadata": c.meta,
            }
            for c in rows
        ],
        "total": total,
    }


@router.post("/knowledge-bases/{kb_id}/documents/{doc_id}/index")
async def index(
    kb_id: str,
    doc_id: str,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    kb = kb_for_user(db, kb_id, user)
    with kb_operation(request.app, kb_id):
        doc = document_for_kb(db, kb_id, doc_id)
        await index_document(request.app, db, kb, doc)
        audit(db, user, request, "rag.document.index", doc.id)
        return {"status": doc.status, "error_code": doc.error_code}


async def remove_vectors(request, kb_id, doc_id=None):
    service = None
    try:
        service = await asyncio.to_thread(
            MilvusService,
            request.app.state.settings.milvus_uri,
            request.app.state.settings.milvus_token.get_secret_value(),
        )
        await asyncio.to_thread(
            service.delete_document if doc_id else service.delete_knowledge_base,
            doc_id or kb_id,
        )
    except Exception:
        raise HTTPException(
            503, "Milvus 删除未成功，元数据已保留，请修复连接后重试"
        ) from None
    finally:
        if service:
            try:
                await asyncio.to_thread(service.close)
            except Exception:
                pass


@router.delete("/knowledge-bases/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    kb_id: str,
    doc_id: str,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    kb_for_user(db, kb_id, user)
    with kb_operation(request.app, kb_id):
        doc = document_for_kb(db, kb_id, doc_id)
        if doc.status != "parsed":
            await remove_vectors(request, kb_id, doc_id)
        # 问题可能同时引用两个文档。删除涉及任一分块的问题，避免悬空来源。
        chunk_ids = set(
            db.scalars(select(RagChunk.id).where(RagChunk.document_id == doc_id))
        )
        for issue in db.scalars(select(RagIssue).where(RagIssue.kb_id == kb_id)):
            if issue.document_id == doc_id or chunk_ids.intersection(
                issue.detail.get("chunk_ids", [])
            ):
                db.delete(issue)
        db.execute(delete(RagChunk).where(RagChunk.document_id == doc_id))
        db.delete(doc)
        audit(db, user, request, "rag.document.delete", doc_id)


@router.delete("/knowledge-bases/{kb_id}", status_code=204)
async def delete_kb(
    kb_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    kb = kb_for_user(db, kb_id, user)
    with kb_operation(request.app, kb_id):
        if db.scalar(
            select(RagDocument.id)
            .where(RagDocument.kb_id == kb_id, RagDocument.status != "parsed")
            .limit(1)
        ):
            await remove_vectors(request, kb_id)
        for entity in [RagIssue, RagEvaluation, RagDataset, RagChunk, RagDocument]:
            db.execute(delete(entity).where(entity.kb_id == kb_id))
        db.delete(kb)
        audit(db, user, request, "rag.kb.delete", kb_id)


@router.post("/knowledge-bases/{kb_id}/retrieve")
async def retrieve_kb(
    kb_id: str,
    body: RetrieveInput,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    kb = kb_for_user(db, kb_id, user)
    with kb_operation(request.app, kb_id):
        ids = list(
            db.scalars(
                select(RagDocument.id).where(
                    RagDocument.kb_id == kb_id, RagDocument.status == "indexed"
                )
            )
        )
        if not ids:
            raise HTTPException(409, "没有已索引文档，请先完成真实向量入库")
        try:
            hits = await retrieve(request.app, kb, body.question, body.top_k, ids)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                503, "真实向量检索失败，请检查模型、维度和 Milvus"
            ) from None
        return {
            "question": body.question,
            "top_k": body.top_k,
            "hits": hits,
            "similarity_is_quality_score": False,
        }


@router.post("/knowledge-bases/{kb_id}/quality-check")
async def quality(
    kb_id: str,
    body: QualityInput,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    kb = kb_for_user(db, kb_id, user)
    with kb_operation(request.app, kb_id):
        rows = db.scalars(
            select(RagChunk)
            .where(RagChunk.kb_id == kb_id)
            .order_by(RagChunk.id)
            .limit(301)
        ).all()
        if len(rows) > 300:
            raise HTTPException(422, "单次质量检查最多 300 分块，请拆分知识库")
        docs = db.scalars(select(RagDocument).where(RagDocument.kb_id == kb_id)).all()
        issues, _ = await asyncio.to_thread(quality_issues, rows, docs)
        semantic_status = "not_requested"
        inspected = 0
        candidate_count = 0
        for doc in docs:
            pages = request.app.state.vault.decrypt(doc.source).get("pages", [])
            for page, text in pages:
                if len(text) > 20000:
                    issues.append(
                        (
                            doc.id,
                            "too_long",
                            "low",
                            {
                                "page": page,
                                "reason": "原始页超过 20000 字符，检查是否缺少段落边界",
                            },
                        )
                    )
                if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
                    issues.append(
                        (
                            doc.id,
                            "format_anomaly",
                            "medium",
                            {"page": page, "reason": "原文含异常控制字符"},
                        )
                    )
        if body.semantic_conflicts:
            try:
                async with asyncio.timeout(180):
                    model = resolve_model(
                        db,
                        request.app.state.settings,
                        request.app.state.vault,
                        body.model_config_id,
                        "rag",
                        user_id=user.id,
                    )
                    pairs, candidate_count = await semantic_pairs(request.app, kb, rows)
                    for left, right, similarity in pairs:
                        verdict = await judge_conflict(left, right, model)
                        inspected += 1
                        issues.append(
                            (
                                left.document_id,
                                "conflict_candidate"
                                if verdict["conflict"]
                                else "semantic_non_conflict",
                                "high" if verdict["conflict"] else "info",
                                {
                                    "chunk_ids": [left.id, right.id],
                                    "similarity": similarity,
                                    "method": "embedding+llm",
                                    "needs_confirmation": verdict["conflict"],
                                    **verdict,
                                },
                            )
                        )
                    semantic_status = (
                        "completed" if inspected == candidate_count else "partial"
                    )
            except Exception as exc:
                semantic_status = "failed"
                issues.append(
                    (
                        None,
                        "semantic_check_error",
                        "unknown",
                        {
                            "reason": "语义冲突检测不可用，未作冲突结论",
                            "error_type": type(exc).__name__,
                        },
                    )
                )
        run_id = uuid4().hex
        source_map = {
            c.id: {
                "document_id": c.document_id,
                "page": c.page_number,
                "content": c.content,
                "name": next((d.name for d in docs if d.id == c.document_id), ""),
            }
            for c in rows
        }
        for doc, kind, severity, data in issues:
            sources = [
                source_map[i] for i in data.get("chunk_ids", []) if i in source_map
            ]
            db.add(
                RagIssue(
                    kb_id=kb_id,
                    document_id=doc,
                    kind=kind,
                    severity=severity,
                    detail={"check_id": run_id, "sources": sources, **data},
                )
            )
        audit(db, user, request, "rag.quality", kb_id)
        return {
            "check_id": run_id,
            "issues": len(issues),
            "semantic_status": semantic_status,
            "semantic_candidates": candidate_count,
            "semantic_inspected": inspected,
            "similarity_is_conflict": False,
        }


@router.get("/knowledge-bases/{kb_id}/issues")
def issues(
    kb_id: str,
    page: int = Query(1, ge=1),
    check_id: str | None = None,
    user=Depends(current_user),
    db=Depends(database),
):
    kb_for_user(db, kb_id, user)
    stmt = select(RagIssue).where(RagIssue.kb_id == kb_id)
    if check_id:
        stmt = stmt.where(RagIssue.detail["check_id"].as_string() == check_id)
    rows, total = paginate(
        db, stmt.order_by(RagIssue.created_at.desc(), RagIssue.id), page, 50
    )
    return {
        "items": [
            {
                k: getattr(r, k)
                for k in [
                    "id",
                    "document_id",
                    "kind",
                    "severity",
                    "detail",
                    "confirmation",
                    "created_at",
                ]
            }
            for r in rows
        ],
        "total": total,
    }


@router.put("/issues/{issue_id}/confirm")
def confirm(
    issue_id: str,
    request: Request,
    decision: str = Query(pattern="^(confirmed|dismissed)$"),
    user=Depends(current_user),
    db=Depends(database),
):
    issue = db.get(RagIssue, issue_id)
    if not issue:
        raise HTTPException(404, "问题不存在")
    kb_for_user(db, issue.kb_id, user)
    with kb_operation(request.app, issue.kb_id):
        issue.confirmation = decision
        audit(db, user, request, "rag.issue.confirm", issue.id)
        return {"confirmation": decision}


def dataset_for_kb(db, kb_id, dataset_id):
    dataset = db.get(RagDataset, dataset_id)
    if not dataset or dataset.kb_id != kb_id:
        raise HTTPException(404, "问题集不存在")
    return dataset


def dataset_public(app, dataset):
    return {
        k: getattr(dataset, k)
        for k in [
            "id",
            "name",
            "source",
            "status",
            "error_code",
            "config",
            "created_at",
        ]
    } | app.state.vault.decrypt(dataset.payload)


def validate_sources(db, kb_id, questions):
    ids = {i for q in questions for i in q.source_chunk_ids}
    if ids and ids != set(
        db.scalars(
            select(RagChunk.id).where(RagChunk.kb_id == kb_id, RagChunk.id.in_(ids))
        )
    ):
        raise HTTPException(422, "引用分块不属于当前知识库")


@router.post("/knowledge-bases/{kb_id}/datasets", status_code=201)
def create_dataset(
    kb_id: str,
    body: DatasetInput,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    kb_for_user(db, kb_id, user)
    with kb_operation(request.app, kb_id):
        validate_sources(db, kb_id, body.questions)
        dataset = RagDataset(
            kb_id=kb_id,
            name=body.name,
            payload=request.app.state.vault.encrypt(
                {"questions": [q.model_dump() for q in body.questions]}
            ),
        )
        db.add(dataset)
        db.flush()
        audit(db, user, request, "rag.dataset.create", dataset.id)
        return dataset_public(request.app, dataset)


@router.put("/knowledge-bases/{kb_id}/datasets/{dataset_id}")
def update_dataset(
    kb_id: str,
    dataset_id: str,
    body: DatasetInput,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    kb_for_user(db, kb_id, user)
    with kb_operation(request.app, kb_id):
        dataset = dataset_for_kb(db, kb_id, dataset_id)
        validate_sources(db, kb_id, body.questions)
        dataset.name = body.name
        dataset.payload = request.app.state.vault.encrypt(
            {"questions": [q.model_dump() for q in body.questions]}
        )
        dataset.status = "ready"
        dataset.error_code = None
        audit(db, user, request, "rag.dataset.review", dataset.id)
        return dataset_public(request.app, dataset)


@router.get("/knowledge-bases/{kb_id}/datasets")
def datasets(
    kb_id: str, request: Request, user=Depends(current_user), db=Depends(database)
):
    kb_for_user(db, kb_id, user)
    return {
        "items": [
            dataset_public(request.app, d)
            for d in db.scalars(
                select(RagDataset)
                .where(RagDataset.kb_id == kb_id)
                .order_by(RagDataset.created_at.desc())
            )
        ]
    }


@router.post("/knowledge-bases/{kb_id}/datasets/generate", status_code=201)
async def generate_dataset(
    kb_id: str,
    body: GenerateQuestions,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    kb = kb_for_user(db, kb_id, user)
    with kb_operation(request.app, kb_id):
        dataset = await generate_questions(request.app, db, kb, body, user.id)
        audit(db, user, request, "rag.dataset.generate", dataset.id)
        return dataset_public(request.app, dataset)


@router.post("/knowledge-bases/{kb_id}/evaluate")
async def evaluate_kb(
    kb_id: str,
    body: RagEvaluationInput,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    kb = kb_for_user(db, kb_id, user)
    with kb_operation(request.app, kb_id):
        if body.dataset_id:
            dataset = dataset_for_kb(db, kb_id, body.dataset_id)
            if dataset.status != "ready":
                raise HTTPException(409, "请先审阅并保存 AI 问题草稿")
            from app.schemas.platform import RagQuestion

            questions = [
                RagQuestion.model_validate(q)
                for q in request.app.state.vault.decrypt(dataset.payload)["questions"]
            ]
        else:
            questions = body.questions
        validate_sources(db, kb_id, questions)
        run = await run_evaluation(request.app, db, kb, body, questions, user.id)
        audit(db, user, request, "rag.evaluate." + run.status, run.id)
        return evaluation(run.id, request, user, db)


@router.get("/evaluations/{evaluation_id}")
def evaluation(
    evaluation_id: str,
    request: Request,
    user=Depends(current_user),
    db=Depends(database),
):
    run = db.get(RagEvaluation, evaluation_id)
    if not run:
        raise HTTPException(404, "评估不存在")
    kb_for_user(db, run.kb_id, user)
    return {
        "id": run.id,
        "status": run.status,
        "config": run.config,
        "error_code": run.error_code,
        **request.app.state.vault.decrypt(run.payload),
    }


@router.get("/knowledge-bases/{kb_id}/evaluations")
def evaluations(kb_id: str, user=Depends(current_user), db=Depends(database)):
    kb_for_user(db, kb_id, user)
    return {
        "items": [
            {
                "id": r.id,
                "status": r.status,
                "created_at": r.created_at,
                "error_code": r.error_code,
            }
            for r in db.scalars(
                select(RagEvaluation)
                .where(RagEvaluation.kb_id == kb_id)
                .order_by(RagEvaluation.created_at.desc())
                .limit(100)
            )
        ]
    }
