"""第四阶段真实 API/MySQL 验收，不调用模型，不使用向量替身。"""

import base64
import io
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import httpx
from sqlalchemy import text
from app.core.config import Settings
from app.db.session import make_engine


def main():
    checks = []
    with httpx.Client(
        base_url="http://127.0.0.1:8000/api/v1", timeout=30, trust_env=False
    ) as client:
        credentials = {
            "username": "rag_mysql_" + uuid4().hex[:12],
            "password": uuid4().hex + "Aa1!",
        }
        assert client.post("/auth/register", json=credentials).status_code == 201
        client.headers["Authorization"] = (
            "Bearer "
            + client.post("/auth/login", json=credentials).json()["access_token"]
        )
        project = client.post("/projects", json={"name": "第四阶段 MySQL 验收"}).json()
        body = {
            "project_id": project["id"],
            "name": "真实文档元数据",
            "chunk_size": 700,
            "overlap": 100,
        }
        response = client.post("/rag/knowledge-bases", json=body)
        assert response.status_code == 201
        kb = response.json()
        url = "/rag/knowledge-bases/" + kb["id"]
        checks.append("knowledge_base_insert")
        text_source = "产品保修期为一年，凭购买凭证申请服务。有效期至 2020-01-01。"
        from docx import Document
        import pymupdf

        doc = Document()
        doc.add_paragraph("真实 DOCX 中文正文")
        stream = io.BytesIO()
        doc.save(stream)
        pdf = pymupdf.open()
        pdf.new_page().insert_text((40, 40), "Actual PDF parser fixture")
        pdf_bytes = pdf.tobytes()
        pdf.close()
        files = [
            ("制度.txt", text_source.encode()),
            ("副本.md", text_source.encode()),
            ("文档.docx", stream.getvalue()),
            ("说明.pdf", pdf_bytes),
            ("中文容量.txt", ("中文知识内容" * 2000).encode()),
        ]
        docs = []
        for name, raw in files:
            r = client.post(
                url + "/documents",
                json={"name": name, "content_base64": base64.b64encode(raw).decode()},
            )
            assert r.status_code == 201, r.status_code
            assert r.json()["chunk_count"] > 0
            docs.append(r.json())
        checks += [
            "txt_parse",
            "markdown_parse",
            "docx_parse",
            "pdf_parse",
            "unicode_long_source",
        ]
        assert len(client.get(url + "/documents").json()["items"]) == 5
        chunks = client.get(url + "/documents/" + docs[0]["id"] + "/chunks").json()[
            "items"
        ]
        assert chunks[0]["page_number"] == 1
        checks += ["document_listing", "chunk_source_and_page"]
        r = client.post(url + "/documents/" + docs[0]["id"] + "/index").json()
        assert r["error_code"] == "embedding_not_configured" and r["status"] == "parsed"
        assert (
            client.post(url + "/retrieve", json={"question": "保修期？"}).status_code
            == 409
        )
        checks += ["missing_embedding_not_indexed", "no_fake_retrieval"]
        quality = client.post(url + "/quality-check", json={}).json()
        found = client.get(
            url + "/issues", params={"check_id": quality["check_id"]}
        ).json()["items"]
        duplicate = next(
            i
            for i in found
            if i["kind"] == "duplicate"
            and docs[0]["id"] in [s["document_id"] for s in i["detail"]["sources"]]
        )
        assert any(i["kind"] == "expired_candidate" for i in found)
        assert not any(i["kind"] == "conflict_candidate" for i in found)
        assert (
            client.put(
                "/rag/issues/" + duplicate["id"] + "/confirm",
                params={"decision": "confirmed"},
            ).json()["confirmation"]
            == "confirmed"
        )
        checks += [
            "duplicate_sources",
            "explicit_expiry",
            "similarity_not_conflict",
            "manual_confirmation",
        ]
        dataset = client.post(
            url + "/datasets",
            json={
                "name": "保修标准答案",
                "questions": [
                    {
                        "question": "保修期多久？",
                        "reference": "一年",
                        "source_chunk_ids": [chunks[0]["id"]],
                    }
                ],
            },
        ).json()
        assert dataset["status"] == "ready"
        assert (
            client.post(url + "/datasets/generate", json={"count": 1}).json()[
                "error_code"
            ]
            == "model_not_configured"
        )
        result = client.post(
            url + "/evaluate", json={"dataset_id": dataset["id"]}
        ).json()
        assert result["status"] == "failed" and not result["samples"]
        checks += [
            "manual_dataset",
            "missing_generation_model_audited",
            "missing_evaluation_model_audited",
        ]
        other = {
            "username": "rag_other_" + uuid4().hex[:12],
            "password": uuid4().hex + "Aa1!",
        }
        client.post("/auth/register", json=other)
        token = client.post("/auth/login", json=other).json()["access_token"]
        assert (
            client.get(
                url + "/documents", headers={"Authorization": "Bearer " + token}
            ).status_code
            == 404
        )
        checks.append("cross_user_isolation")
        settings = Settings()
        engine = make_engine(settings.database_url.get_secret_value())
        with engine.connect() as conn:
            assert (
                conn.scalar(text("SELECT version_num FROM alembic_version"))
                == "0007_delivery"
            )
            assert (
                conn.scalar(
                    text("SELECT COUNT(*) FROM rag_documents WHERE kb_id=:id"),
                    {"id": kb["id"]},
                )
                == 5
            )
            raw = conn.scalar(
                text("SELECT source FROM rag_documents WHERE id=:id"),
                {"id": docs[0]["id"]},
            )
            assert "保修期" not in raw
            assert (
                conn.scalar(
                    text("SELECT COUNT(*) FROM rag_datasets WHERE kb_id=:id"),
                    {"id": kb["id"]},
                )
                == 2
            )
        engine.dispose()
        checks += [
            "mysql_migration",
            "mysql_document_persistence",
            "encrypted_source",
            "mysql_generation_history",
        ]
        assert client.delete(url + "/documents/" + docs[0]["id"]).status_code == 204
        assert (
            client.get(url + "/documents/" + docs[0]["id"] + "/chunks").status_code
            == 404
        )
        checks.append("parsed_document_delete")
        output = {
            "status": "passed",
            "count": len(checks),
            "checks": checks,
            "knowledge_base_id": kb["id"],
            "retained_test_username": credentials["username"],
            "real_model_calls": 0,
            "real_milvus_calls": 0,
        }
        (
            Path(__file__).resolve().parents[1] / "docs/evidence/stage4-mysql.json"
        ).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

