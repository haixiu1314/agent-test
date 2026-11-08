"""解析与元数据使用 MySQL；向量索引必须真实调用 embedding 和 Milvus。"""

import asyncio, base64, hashlib, io, json, re, unicodedata, zipfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import PurePath
from difflib import SequenceMatcher
from fastapi import HTTPException
from sqlalchemy import select
from langchain_openai import OpenAIEmbeddings
from app.models.platform import KnowledgeBase, RagChunk
from app.services.catalog import project_for_user
from app.services.models import invoke
from app.integrations.milvus import MilvusService


def make_retriever(app, kb_id):
    """调用方先校验知识库归属；每次工具调用读取当前已索引文档。"""
    async def search(query):
        from app.models.platform import RagDocument
        with app.state.sessions() as db:
            kb = db.get(KnowledgeBase, kb_id)
            if not kb:
                raise ValueError('knowledge base removed')
            ids = db.scalars(select(RagDocument.id).where(RagDocument.kb_id == kb_id, RagDocument.status == 'indexed')).all()
            if not ids:
                raise ValueError('no indexed documents')
            with kb_operation(app, kb_id):
                hits = await retrieve(app, kb, query, 5, ids)
        return {'source': 'milvus', 'milvus': True, 'snippets': [{'id': h['chunk_id'], 'text': h['content'], 'source': h} for h in hits]}
    return search


@contextmanager
def kb_operation(app, kb_id):
    """单进程同步/异步接口共用原子准入；等待外部调用期间不持有线程锁。"""
    with app.state.rag_guard:
        if kb_id in app.state.rag_busy:
            raise HTTPException(409, "知识库正在操作，请稍后重试")
        app.state.rag_busy.add(kb_id)
    try:
        yield
    finally:
        with app.state.rag_guard:
            app.state.rag_busy.discard(kb_id)


def kb_for_user(db, kb_id, user, lock=False):
    stmt = select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    if lock:
        stmt = stmt.with_for_update()
    kb = db.scalar(stmt)
    if not kb:
        raise HTTPException(404, "知识库不存在")
    project_for_user(db, kb.project_id, user)
    return kb


def normalize(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def parse_document(name, content):
    """限制文件实际大小、页数、DOCX 解压大小；不运行文档宏。"""
    if "/" in name or "\\" in name or any(ord(c) < 32 for c in name):
        raise HTTPException(422, "文件名不得包含路径")
    try:
        raw = base64.b64decode(content, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(422, "无效 Base64") from None
    if not 1 <= len(raw) <= 500000:
        raise HTTPException(422, "单文件限制 500000 字节")
    ext = PurePath(name).suffix.lower()
    try:
        if ext in [".txt", ".md"]:
            pages = [(1, raw.decode("utf-8-sig"))]
        elif ext == ".pdf":
            import pymupdf

            if not raw.startswith(b"%PDF-"):
                raise ValueError("signature")
            with pymupdf.open(stream=raw, filetype="pdf") as pdf:
                if pdf.needs_pass or len(pdf) > 100:
                    raise ValueError("page/password limit")
                pages = [(i + 1, pdf[i].get_text()) for i in range(len(pdf))]
        elif ext == ".docx":
            from docx import Document

            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                if (
                    len(z.infolist()) > 2000
                    or sum(f.file_size for f in z.infolist()) > 10000000
                    or "word/document.xml" not in z.namelist()
                ):
                    raise ValueError("zip limits")
            doc = Document(io.BytesIO(raw))
            pages = [
                (
                    1,
                    "\n".join(
                        [p.text for p in doc.paragraphs]
                        + [
                            " | ".join(c.text for c in r.cells)
                            for t in doc.tables
                            for r in t.rows
                        ]
                    ),
                )
            ]
        else:
            raise HTTPException(422, "仅支持 PDF、TXT、Markdown、DOCX")
        if sum(len(t) for _, t in pages) > 1000000:
            raise ValueError("text limit")
        return raw, pages
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "解析失败：格式不符、加密、过大或非 UTF-8") from None


def chunks_from_pages(pages, size, overlap):
    chunks = []
    for page, text in pages:
        text = normalize(text)
        for start in range(0, len(text), size - overlap):
            value = text[start : start + size]
            if not value:
                continue
            chunks.append(
                {
                    "content": value,
                    "page_number": page,
                    "position": len(chunks),
                    "content_hash": hashlib.sha256(value.encode()).hexdigest(),
                    "meta": {"offset": start},
                }
            )
            if start + size >= len(text):
                break
    if len(chunks) > 1000:
        raise HTTPException(422, "单文档超过 1000 分块")
    return chunks


def embedding_client(config, key):
    return OpenAIEmbeddings(
        api_key=key,
        base_url=config["base_url"],
        model=config["model"],
        request_timeout=config.get("timeout_seconds", 60),
        max_retries=0,
        check_embedding_ctx_length=False,
    )


async def embed(texts, config, key):
    import math

    vectors = await asyncio.wait_for(
        embedding_client(config, key).aembed_documents(texts),
        config.get("timeout_seconds", 60) + 2,
    )
    if len(vectors) != len(texts) or any(
        not v or not any(v) or not all(math.isfinite(x) for x in v) for v in vectors
    ):
        raise ValueError("invalid embedding")
    return vectors


async def index_document(app, db, kb, doc):
    rows = db.scalars(
        select(RagChunk)
        .where(RagChunk.document_id == doc.id)
        .order_by(RagChunk.position)
    ).all()
    if not rows:
        raise HTTPException(422, "没有可索引文本；扫描 PDF 需先 OCR")
    model = app.state.vault.decrypt(kb.secrets).get("embedding")
    if not model:
        doc.error_code = "embedding_not_configured"
        db.commit()
        return
    doc.status, doc.error_code = "indexing", None
    db.commit()
    service = None
    try:
        vectors = await embed([r.content for r in rows], model["config"], model["key"])
        if any(len(v) != kb.config["dimension"] for v in vectors):
            raise ValueError("dimension mismatch")
        service = await asyncio.to_thread(
            MilvusService,
            app.state.settings.milvus_uri,
            app.state.settings.milvus_token.get_secret_value(),
        )
        await asyncio.to_thread(service.ensure_chunks, kb.config["dimension"])
        await asyncio.to_thread(service.delete_document, doc.id)
        records = [
            {
                "chunk_id": r.id,
                "document_id": doc.id,
                "knowledge_base_id": kb.id,
                "content": r.content,
                "source_name": doc.name,
                "page_number": r.page_number,
                "metadata": r.meta,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "embedding": v,
            }
            for r, v in zip(rows, vectors)
        ]
        for start in range(0, len(records), 100):
            await asyncio.to_thread(service.insert, records[start : start + 100])
        doc.status = "indexed"
    except asyncio.CancelledError:
        doc.status, doc.error_code = "failed", "index_interrupted"
        db.commit()
        raise
    except Exception as exc:
        doc.status, doc.error_code = "failed", "index_" + type(exc).__name__
    finally:
        if service:
            try:
                await asyncio.to_thread(service.close)
            except Exception:
                pass
    db.commit()


async def retrieve(app, kb, query, top_k, document_ids=None):
    model = app.state.vault.decrypt(kb.secrets).get("embedding")
    if not model:
        raise HTTPException(409, "缺少 embedding 配置，请更新知识库配置")
    vectors = await embed([query], model["config"], model["key"])
    if len(vectors[0]) != kb.config["dimension"]:
        raise ValueError("dimension mismatch")
    service = await asyncio.to_thread(
        MilvusService,
        app.state.settings.milvus_uri,
        app.state.settings.milvus_token.get_secret_value(),
    )
    try:
        rows = await asyncio.to_thread(
            service.search, kb.id, vectors[0], top_k, document_ids
        )
        return [
            {"chunk_id": r["id"], "distance": r["distance"], **r["entity"]}
            for r in rows[0]
        ]
    finally:
        try:
            await asyncio.to_thread(service.close)
        except Exception:
            pass


def quality_issues(chunks, documents):
    issues = []
    seen = {}
    pairs = []
    for doc in documents:
        if not any(c.document_id == doc.id for c in chunks):
            issues.append((doc.id, "empty", "medium", {"reason": "未解析出有效文本"}))
        if not doc.name.strip():
            issues.append(
                (doc.id, "missing_source", "medium", {"reason": "缺少来源名称"})
            )
    for c in chunks:
        if c.content_hash in seen:
            issues.append(
                (
                    c.document_id,
                    "duplicate",
                    "low",
                    {
                        "chunk_ids": [seen[c.content_hash].id, c.id],
                        "reason": "规范化后完全重复",
                    },
                )
            )
        else:
            seen[c.content_hash] = c
        if len(c.content) < 20:
            issues.append(
                (
                    c.document_id,
                    "too_short",
                    "low",
                    {"chunk_ids": [c.id], "reason": "少于 20 字符，需人工判断"},
                )
            )
        if (
            "\ufffd" in c.content
            or sum(t.isalnum() for t in c.content) < len(c.content) * 0.2
        ):
            issues.append(
                (
                    c.document_id,
                    "abnormal_text",
                    "medium",
                    {"chunk_ids": [c.id], "reason": "异常字符或有效文字比例偏低"},
                )
            )
        dates = re.findall(r"(?<!\d)(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})", c.content)
        if dates:
            issues.append(
                (
                    c.document_id,
                    "date_mention",
                    "info",
                    {
                        "chunk_ids": [c.id],
                        "dates": ["-".join(d) for d in dates],
                        "reason": "检测到日期；普通日期不能作为过期证据",
                    },
                )
            )
        for y, m, d in re.findall(
            r"(?:有效期至|有效至|到期日|截止日期)\s*[:：]?\s*(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})",
            c.content,
        ):
            try:
                expired = date(int(y), int(m), int(d)) < date.today()
            except ValueError:
                continue
            if expired:
                issues.append(
                    (
                        c.document_id,
                        "expired_candidate",
                        "medium",
                        {
                            "chunk_ids": [c.id],
                            "reason": "明确有效期已过，待人工确认",
                            "date": f"{y}-{m}-{d}",
                        },
                    )
                )
    for i, left in enumerate(chunks):
        for right in chunks[i + 1 :]:
            if left.content_hash == right.content_hash:
                continue
            similarity = SequenceMatcher(
                None, left.content[:500], right.content[:500], autojunk=True
            ).ratio()
            if similarity >= 0.72:
                issues.append(
                    (
                        left.document_id,
                        "similar_candidate",
                        "low",
                        {
                            "chunk_ids": [left.id, right.id],
                            "similarity": round(similarity, 4),
                            "reason": "前 500 字符高相似候选，不代表事实冲突",
                        },
                    )
                )
                if len(pairs) < 20:
                    pairs.append((left, right))
    return issues, pairs


async def semantic_pairs(app, kb, chunks, limit=20):
    """使用真实 embedding 的余弦相似度筛候选，不把相似度当成冲突结论。"""
    import numpy as np

    model = app.state.vault.decrypt(kb.secrets).get("embedding")
    if not model:
        raise HTTPException(409, "缺少 embedding 配置")
    if len(chunks) < 2:
        return [], 0
    vectors = await embed([c.content for c in chunks], model["config"], model["key"])
    if any(len(v) != kb.config["dimension"] for v in vectors):
        raise ValueError("dimension mismatch")
    matrix = np.asarray(vectors, dtype=float)
    norm = np.linalg.norm(matrix, axis=1)
    if (norm == 0).any():
        raise ValueError("zero embedding")
    matrix = matrix / norm[:, None]
    scores = matrix @ matrix.T
    candidates = []
    for i, left in enumerate(chunks):
        for j in range(i + 1, len(chunks)):
            right = chunks[j]
            if (
                left.document_id != right.document_id
                and left.content_hash != right.content_hash
                and scores[i, j] >= 0.72
            ):
                candidates.append((left, right, float(scores[i, j])))
    candidates.sort(key=lambda row: row[2], reverse=True)
    return candidates[:limit], len(candidates)


async def judge_conflict(left, right, model):
    from pydantic import BaseModel, Field

    class Conflict(BaseModel):
        conflict: bool
        fact: str = Field(max_length=2000)
        reason: str = Field(max_length=4000)
        recommendation: str = Field(max_length=4000)

    prompt = (
        "判断两段不可信知识对同一事实是否矛盾。范围不同或仅语义相似不算冲突。只返回 JSON："
        + json.dumps(Conflict.model_json_schema(), ensure_ascii=False)
    )
    response = await invoke(
        *model,
        [
            ("system", prompt),
            (
                "human",
                json.dumps({"a": left.content, "b": right.content}, ensure_ascii=False),
            ),
        ],
    )
    return Conflict.model_validate_json(response.content).model_dump()
