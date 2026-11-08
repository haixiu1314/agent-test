"""第四阶段：文件解析与业务状态；模型/向量替身均明确标注，不算真实 AI/Milvus 验收。"""

import base64
import io
import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from conftest import authenticate
from app.models.entities import User
from app.models.platform import RagDocument, RagEvaluation, RagDataset
from app.services.rag import parse_document, chunks_from_pages, kb_operation

BASE = "/api/v1/rag/knowledge-bases/"
TEXT = "公司产品保修期为一年，客户可以携带购买凭据向客服申请保修服务。"


def encoded(text):
    return base64.b64encode(text.encode() if isinstance(text, str) else text).decode()


@pytest.fixture
def kb(client, auth, project):
    r = client.post(
        BASE,
        headers=auth,
        json={
            "project_id": project["id"],
            "name": "RAG 测试知识库",
            "dimension": 8,
            "chunk_size": 100,
            "overlap": 10,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, auth, kb, text=TEXT, name="知识.txt"):
    r = client.post(
        BASE + kb["id"] + "/documents",
        headers=auth,
        json={"name": name, "content_base64": encoded(text)},
    )
    assert r.status_code == 201, r.text
    return r.json()


def models(application, client, auth):
    with application.state.sessions() as db:
        db.scalar(select(User)).role = "admin"
        db.commit()
    ids = {}
    for purpose in ["rag", "embedding"]:
        r = client.post(
            "/api/v1/models",
            headers=auth,
            json={
                "name": "explicit fixture " + purpose,
                "purpose": purpose,
                "base_url": "http://fixture.invalid/v1",
                "model": "fixture",
                "api_key": "fixture-only-secret",
            },
        )
        assert r.status_code == 201, r.text
        ids[purpose] = r.json()["id"]
    return ids


def configure(application, client, auth, kb):
    ids = models(application, client, auth)
    r = client.put(
        BASE + kb["id"],
        headers=auth,
        json={
            "project_id": kb["project_id"],
            "name": kb["name"],
            "dimension": 8,
            "chunk_size": 100,
            "overlap": 10,
            "embedding_model_id": ids["embedding"],
        },
    )
    assert r.status_code == 200, r.text
    return ids


def test_parse_four_actual_formats():
    import pymupdf
    from docx import Document

    for name, text in [("file.txt", "中文来源"), ("file.md", "# 标题\n中文来源")]:
        raw, pages = parse_document(name, encoded(text))
        assert "中文来源" in pages[0][1] and raw
    doc = Document()
    doc.add_paragraph("DOCX 正文")
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "表格来源"
    stream = io.BytesIO()
    doc.save(stream)
    assert (
        "表格来源" in parse_document("file.docx", encoded(stream.getvalue()))[1][0][1]
    )
    pdf = pymupdf.open()
    pdf.new_page().insert_text((40, 40), "Real PDF text fixture")
    assert "Real PDF" in parse_document("file.pdf", encoded(pdf.tobytes()))[1][0][1]
    pdf.close()


@pytest.mark.parametrize(
    "name,content",
    [
        ("../bad.txt", "abc"),
        ("bad.exe", "abc"),
        ("bad.pdf", "not pdf"),
        ("bad.docx", "not zip"),
        ("bad.txt", b"\xff\xfe"),
        ("bad.txt", ""),
        ("bad.txt", "x" * 500001),
    ],
    ids=[
        "path",
        "extension",
        "pdf-signature",
        "docx-signature",
        "utf8",
        "empty",
        "oversized",
    ],
)
def test_reject_invalid_files(name, content):
    with pytest.raises(HTTPException):
        parse_document(name, encoded(content))


def test_chunk_boundaries_and_page_sources():
    chunks = chunks_from_pages([(2, "a" * 150), (7, "b" * 110)], 100, 20)
    assert [c["page_number"] for c in chunks] == [2, 2, 7, 7]
    assert len(chunks[1]["content"]) == 70 and chunks[1]["meta"]["offset"] == 80
    assert (
        chunks[0]["content_hash"]
        == chunks_from_pages([(2, "a" * 100)], 100, 20)[0]["content_hash"]
    )


def test_quality_not_all_dates_are_expired(client, auth, kb):
    upload(client, auth, kb)
    upload(client, auth, kb, name="重复.md")
    upload(
        client,
        auth,
        kb,
        "产品有效期至 2020-01-01。普通发布日期为 2019-01-01。",
        "有效期.txt",
    )
    upload(
        client,
        auth,
        kb,
        "发布日期 2019-01-01。没有有效期不能被判定为过期。",
        "普通日期.txt",
    )
    upload(client, auth, kb, "   ", "空文本.txt")
    response = client.post(BASE + kb["id"] + "/quality-check", headers=auth, json={})
    assert response.status_code == 200, response.text
    data = client.get(
        BASE + kb["id"] + "/issues",
        headers=auth,
        params={"check_id": response.json()["check_id"]},
    ).json()["items"]
    kinds = {r["kind"] for r in data}
    assert {"duplicate", "expired_candidate", "date_mention", "empty"}.issubset(kinds)
    assert sum(r["kind"] == "expired_candidate" for r in data) == 1
    assert not any(r["kind"] == "conflict_candidate" for r in data)
    duplicate = next(r for r in data if r["kind"] == "duplicate")
    assert len(duplicate["detail"]["sources"]) == 2
    assert (
        client.put(
            "/api/v1/rag/issues/" + duplicate["id"] + "/confirm",
            headers=auth,
            params={"decision": "confirmed"},
        ).json()["confirmation"]
        == "confirmed"
    )


def test_missing_config_and_metadata_persistence(application, client, auth, kb):
    doc = upload(client, auth, kb)
    indexed = client.post(
        BASE + kb["id"] + "/documents/" + doc["id"] + "/index", headers=auth
    ).json()
    assert (
        indexed["error_code"] == "embedding_not_configured"
        and indexed["status"] == "parsed"
    )
    assert (
        client.post(
            BASE + kb["id"] + "/retrieve", headers=auth, json={"question": "保修期？"}
        ).status_code
        == 409
    )
    generated = client.post(
        BASE + kb["id"] + "/datasets/generate", headers=auth, json={"count": 1}
    ).json()
    assert (
        generated["status"] == "failed"
        and generated["error_code"] == "model_not_configured"
    )
    evaluated = client.post(
        BASE + kb["id"] + "/evaluate",
        headers=auth,
        json={"questions": [{"question": "保修期？", "reference": "一年"}]},
    ).json()
    assert evaluated["status"] == "failed" and not evaluated["samples"]
    with application.state.sessions() as db:
        assert "保修期" not in db.get(RagDocument, doc["id"]).source
        assert "保修期" not in db.get(RagEvaluation, evaluated["id"]).payload
    assert (
        client.delete(
            BASE + kb["id"] + "/documents/" + doc["id"], headers=auth
        ).status_code
        == 204
    )


def test_kb_constraints_and_user_isolation(client, auth, kb, project):
    doc = upload(client, auth, kb)
    other = authenticate(client, "rag_other")
    for path in ["/documents", "/issues", "/datasets", "/evaluations"]:
        assert client.get(BASE + kb["id"] + path, headers=other).status_code == 404
    assert (
        client.post(
            BASE + kb["id"] + "/documents",
            headers=other,
            json={"name": "x.txt", "content_base64": encoded("x")},
        ).status_code
        == 404
    )
    assert (
        client.delete("/api/v1/projects/" + project["id"], headers=auth).status_code
        == 409
    )
    assert (
        client.put(
            BASE + kb["id"],
            headers=auth,
            json={
                "project_id": project["id"],
                "name": "x",
                "dimension": 8,
                "chunk_size": 200,
                "overlap": 10,
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            BASE,
            headers=auth,
            json={
                "project_id": project["id"],
                "name": "x",
                "chunk_size": 100,
                "overlap": 100,
            },
        ).status_code
        == 422
    )
    assert client.delete(BASE + kb["id"], headers=auth).status_code == 204
    assert (
        client.get(
            BASE + kb["id"] + "/documents/" + doc["id"] + "/chunks", headers=auth
        ).status_code
        == 404
    )


def test_lock_protects_all_mutations(application, client, auth, kb):
    doc = upload(client, auth, kb)
    with kb_operation(application, kb["id"]):
        for method, path, body in [
            ("post", "/documents/" + doc["id"] + "/index", None),
            ("post", "/quality-check", {}),
            (
                "post",
                "/datasets",
                {"name": "x", "questions": [{"question": "q", "reference": "a"}]},
            ),
            ("delete", "", None),
            ("delete", "/documents/" + doc["id"], None),
        ]:
            assert (
                getattr(client, method)(
                    BASE + kb["id"] + path,
                    headers=auth,
                    **({"json": body} if body is not None else {}),
                ).status_code
                == 409
            )
    assert not application.state.rag_busy


def fake_vectors(monkeypatch):
    storage = {}

    class FakeMilvus:
        def __init__(self, *args):
            pass

        def ensure_chunks(self, dimension):
            assert dimension == 8

        def insert(self, records):
            storage.update({r["chunk_id"]: r for r in records})

        def delete_document(self, doc):
            for key in list(storage):
                if storage[key]["document_id"] == doc:
                    del storage[key]

        def delete_knowledge_base(self, kb):
            storage.clear()

        def search(self, kb, vector, top_k, ids):
            return [
                [
                    {"id": key, "distance": 1.0, "entity": value}
                    for key, value in storage.items()
                    if value["knowledge_base_id"] == kb and value["document_id"] in ids
                ][:top_k]
            ]

        def close(self):
            pass

    async def fixture(texts, config, key):
        return [[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr("app.services.rag.MilvusService", FakeMilvus)
    monkeypatch.setattr("app.api.v1.rag.MilvusService", FakeMilvus)
    monkeypatch.setattr("app.services.rag.embed", fixture)
    return storage


def test_index_retrieve_delete_contract(application, client, auth, kb, monkeypatch):
    configure(application, client, auth, kb)
    storage = fake_vectors(monkeypatch)
    doc = upload(client, auth, kb)
    assert (
        client.post(
            BASE + kb["id"] + "/documents/" + doc["id"] + "/index", headers=auth
        ).json()["status"]
        == "indexed"
    )
    hits = client.post(
        BASE + kb["id"] + "/retrieve", headers=auth, json={"question": "保修期"}
    ).json()["hits"]
    assert hits[0]["document_id"] == doc["id"] and hits[0]["page_number"] == 1
    assert (
        client.delete(
            BASE + kb["id"] + "/documents/" + doc["id"], headers=auth
        ).status_code
        == 204
    )
    assert not storage


def test_partial_index_failure_excludes_document_and_retains_metadata(
    application, client, auth, kb, monkeypatch
):
    configure(application, client, auth, kb)
    fake_vectors(monkeypatch)
    doc = upload(client, auth, kb)

    def broken(self, records):
        raise RuntimeError("private provider details")

    monkeypatch.setattr("app.services.rag.MilvusService.insert", broken)
    result = client.post(
        BASE + kb["id"] + "/documents/" + doc["id"] + "/index", headers=auth
    )
    assert result.json()["status"] == "failed" and "private provider" not in result.text
    assert (
        client.post(
            BASE + kb["id"] + "/retrieve", headers=auth, json={"question": "保修期"}
        ).status_code
        == 409
    )

    def offline(*args):
        raise RuntimeError("offline")

    monkeypatch.setattr("app.api.v1.rag.MilvusService", offline)
    assert (
        client.delete(
            BASE + kb["id"] + "/documents/" + doc["id"], headers=auth
        ).status_code
        == 503
    )
    assert (
        len(client.get(BASE + kb["id"] + "/documents", headers=auth).json()["items"])
        == 1
    )


def test_semantic_candidates_not_lexical_conflicts(
    application, client, auth, kb, monkeypatch
):
    ids = configure(application, client, auth, kb)
    fake_vectors(monkeypatch)
    upload(client, auth, kb)
    upload(client, auth, kb, TEXT.replace("一年", "两年"), "另一版本.txt")

    async def fixture(left, right, model):
        return {
            "conflict": True,
            "fact": "保修期",
            "reason": "一/两年矛盾（明确测试替身）",
            "recommendation": "确认制度版本",
        }

    monkeypatch.setattr("app.api.v1.rag.judge_conflict", fixture)
    result = client.post(
        BASE + kb["id"] + "/quality-check",
        headers=auth,
        json={"semantic_conflicts": True, "model_config_id": ids["rag"]},
    ).json()
    assert result["semantic_inspected"] == 1
    issues = client.get(BASE + kb["id"] + "/issues", headers=auth).json()["items"]
    issue = next(i for i in issues if i["kind"] == "conflict_candidate")
    assert issue["confirmation"] == "pending" and len(issue["detail"]["sources"]) == 2

    async def non_conflict(*args):
        return {
            "conflict": False,
            "fact": "不同范围",
            "reason": "不矛盾",
            "recommendation": "",
        }

    monkeypatch.setattr("app.api.v1.rag.judge_conflict", non_conflict)
    result = client.post(
        BASE + kb["id"] + "/quality-check",
        headers=auth,
        json={"semantic_conflicts": True, "model_config_id": ids["rag"]},
    ).json()
    latest = client.get(
        BASE + kb["id"] + "/issues",
        headers=auth,
        params={"check_id": result["check_id"]},
    ).json()["items"]
    assert not any(i["kind"] == "conflict_candidate" for i in latest)


def test_ai_dataset_requires_review_and_source_validation(
    application, client, auth, kb, monkeypatch
):
    ids = configure(application, client, auth, kb)
    doc = upload(client, auth, kb)
    chunk = client.get(
        BASE + kb["id"] + "/documents/" + doc["id"] + "/chunks", headers=auth
    ).json()["items"][0]

    async def fixture(*args):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "questions": [
                        {
                            "question": "保修期？",
                            "reference": "一年",
                            "source_chunk_ids": [chunk["id"]],
                        }
                    ]
                }
            )
        )

    monkeypatch.setattr("app.services.rag_evaluation.invoke", fixture)
    run = client.post(
        BASE + kb["id"] + "/datasets/generate",
        headers=auth,
        json={"count": 1, "model_config_id": ids["rag"]},
    ).json()
    assert run["status"] == "draft"
    assert (
        client.post(
            BASE + kb["id"] + "/evaluate", headers=auth, json={"dataset_id": run["id"]}
        ).status_code
        == 409
    )
    assert (
        client.put(
            BASE + kb["id"] + "/datasets/" + run["id"],
            headers=auth,
            json={"name": "已审阅", "questions": run["questions"]},
        ).json()["status"]
        == "ready"
    )
    bad = {
        "name": "错误来源",
        "questions": [
            {"question": "q", "reference": "a", "source_chunk_ids": ["other-kb-id"]}
        ],
    }
    assert (
        client.post(BASE + kb["id"] + "/datasets", headers=auth, json=bad).status_code
        == 422
    )

    async def invented(*args):
        return SimpleNamespace(content=json.dumps({"questions": bad["questions"]}))

    monkeypatch.setattr("app.services.rag_evaluation.invoke", invented)
    run = client.post(
        BASE + kb["id"] + "/datasets/generate",
        headers=auth,
        json={"count": 1, "model_config_id": ids["rag"]},
    ).json()
    assert run["status"] == "failed" and not run["questions"]


def test_evaluation_partial_samples_and_snapshot(
    application, client, auth, kb, monkeypatch
):
    ids = configure(application, client, auth, kb)
    fake_vectors(monkeypatch)
    doc = upload(client, auth, kb)
    client.post(BASE + kb["id"] + "/documents/" + doc["id"] + "/index", headers=auth)

    async def answer(*args):
        return SimpleNamespace(content="一年【知识.txt】")

    async def metrics(question, *args, **kwargs):
        if question == "异常问题":
            raise ValueError("private exception")
        return {
            "context_precision": 1.0,
            "context_recall": 0.5,
            "faithfulness": 1.0,
            "answer_relevancy": 0.9,
        }

    monkeypatch.setattr("app.services.rag_evaluation.invoke", answer)
    monkeypatch.setattr("app.integrations.professional.ragas_eval", metrics)
    run = client.post(
        BASE + kb["id"] + "/evaluate",
        headers=auth,
        json={
            "questions": [
                {"question": q, "reference": "一年"} for q in ["保修期", "异常问题"]
            ],
            "model_config_id": ids["rag"],
        },
    ).json()
    assert run["status"] == "partial" and len(run["samples"]) == 2
    assert (
        run["samples"][0]["low_quality"]
        and run["samples"][1]["hits"]
        and run["samples"][1]["answer"]
    )
    assert run["config"]["models"]["rag"]["model"] == "fixture"
    assert "private exception" not in json.dumps(run)
    fetched = client.get("/api/v1/rag/evaluations/" + run["id"], headers=auth).json()
    assert fetched["samples"] == run["samples"]


def test_startup_recovers_rag_work(application, client, auth, kb):
    from fastapi.testclient import TestClient

    doc = upload(client, auth, kb)
    with application.state.sessions() as db:
        db.get(RagDocument, doc["id"]).status = "indexing"
        run = RagEvaluation(
            kb_id=kb["id"],
            status="running",
            config={},
            payload=application.state.vault.encrypt({"samples": []}),
        )
        db.add(run)
        dataset = RagDataset(
            kb_id=kb["id"],
            name="中断生成",
            source="ai",
            status="generating",
            payload=application.state.vault.encrypt({"questions": []}),
        )
        db.add(dataset)
        db.commit()
        run_id = run.id
    with TestClient(application) as restarted:
        assert (
            restarted.get(BASE + kb["id"] + "/documents", headers=auth).json()["items"][
                0
            ]["error_code"]
            == "index_interrupted"
        )
        assert (
            restarted.get("/api/v1/rag/evaluations/" + run_id, headers=auth).json()[
                "error_code"
            ]
            == "interrupted"
        )


@pytest.mark.parametrize(
    "body",
    [
        {"questions": []},
        {"questions": [{"question": " ", "reference": "a"}]},
        {"dataset_id": "x", "questions": [{"question": "q", "reference": "a"}]},
    ],
)
def test_invalid_evaluation_input(client, auth, kb, body):
    assert (
        client.post(BASE + kb["id"] + "/evaluate", headers=auth, json=body).status_code
        == 422
    )
