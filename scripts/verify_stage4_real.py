"""真实 Embedding/Milvus/LLM/RAGAS 联合补验，配置缺失则明确阻塞。会消耗模型额度。"""

import asyncio
import base64
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import Settings
from app.services.rag import embed
from app.integrations.milvus import MilvusService
import httpx


def save(result):
    (Path(__file__).resolve().parents[1] / "docs/evidence/stage4-real.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


async def main():
    settings = Settings()
    if not all(
        [
            settings.llm_base_url,
            settings.llm_model,
            settings.llm_api_key.get_secret_value(),
            settings.embedding_model,
        ]
    ):
        save(
            {
                "status": "blocked",
                "reason": "LLM_* or EMBEDDING_MODEL missing",
                "real_model_calls": 0,
            }
        )
        return 2
    try:
        service = await asyncio.to_thread(
            MilvusService, settings.milvus_uri, settings.milvus_token.get_secret_value()
        )
        await asyncio.to_thread(service.close)
    except Exception as exc:
        save(
            {
                "status": "blocked",
                "reason": "Milvus unavailable",
                "error_type": type(exc).__name__,
                "real_model_calls": 0,
            }
        )
        return 2
    config = {
        "model": settings.embedding_model,
        "base_url": settings.llm_base_url,
        "timeout_seconds": settings.llm_timeout_seconds,
    }
    vectors = await embed(
        ["保修期为一年"], config, settings.llm_api_key.get_secret_value()
    )
    dimension = len(vectors[0])
    checks = ["real_embedding"]
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000/api/v1", timeout=250, trust_env=False
    ) as client:
        credentials = {
            "username": "rag_real_" + uuid4().hex[:12],
            "password": uuid4().hex + "Aa1!",
        }
        assert (
            await client.post("/auth/register", json=credentials)
        ).status_code == 201
        client.headers["Authorization"] = (
            "Bearer "
            + (await client.post("/auth/login", json=credentials)).json()[
                "access_token"
            ]
        )
        project = (
            await client.post("/projects", json={"name": "真实 RAG 联合验收"})
        ).json()
        kb = (
            await client.post(
                "/rag/knowledge-bases",
                json={
                    "project_id": project["id"],
                    "name": "真实模型保修库",
                    "dimension": dimension,
                },
            )
        ).json()
        url = "/rag/knowledge-bases/" + kb["id"]
        for name, text in [
            ("制度A.txt", "产品 A 的保修期为一年，自购买之日起计算。"),
            ("制度B.txt", "产品 A 的保修期为两年，自购买之日起计算。"),
        ]:
            doc = (
                await client.post(
                    url + "/documents",
                    json={
                        "name": name,
                        "content_base64": base64.b64encode(text.encode()).decode(),
                    },
                )
            ).json()
            indexed = (
                await client.post(url + "/documents/" + doc["id"] + "/index")
            ).json()
            assert indexed["status"] == "indexed", indexed.get("error_code")
        checks.append("real_milvus_index")
        hits = (
            await client.post(
                url + "/retrieve", json={"question": "产品 A 保修期多久？"}
            )
        ).json()["hits"]
        assert hits
        checks.append("real_retrieval")
        quality = (
            await client.post(url + "/quality-check", json={"semantic_conflicts": True})
        ).json()
        issues = (
            await client.get(url + "/issues", params={"check_id": quality["check_id"]})
        ).json()["items"]
        assert quality["semantic_status"] == "completed" and any(
            i["kind"] == "conflict_candidate" for i in issues
        )
        checks.append("real_conflict_judge")
        generated = (
            await client.post(url + "/datasets/generate", json={"count": 2})
        ).json()
        assert generated["status"] == "draft"
        checks.append("real_question_generation")
        reviewed = await client.put(
            url + "/datasets/" + generated["id"],
            json={"name": "真实问题协议保存样本（需人工核对）", "questions": generated["questions"]},
        )
        assert reviewed.status_code == 200
        run = (
            await client.post(
                url + "/evaluate",
                json={"dataset_id": generated["id"], "mode": "combined"},
            )
        ).json()
        assert run["status"] == "completed", run.get("error_code")
        assert all(
            set(s["metrics"])
            == {
                "context_precision",
                "context_recall",
                "faithfulness",
                "answer_relevancy",
            }
            for s in run["samples"]
        )
        checks.append("real_ragas_four_metrics")
        save(
            {
                "status": "passed",
                "checks": checks,
                "knowledge_base_id": kb["id"],
                "evaluation_id": run["id"],
                "note": "仅证明本次真实流程与指标返回，不代表知识无冲突或回答质量合格",
            }
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        save(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "reason": "Actual integration failed; partial database evidence retained",
            }
        )
        raise SystemExit(1)
