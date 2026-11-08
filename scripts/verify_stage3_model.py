"""真实语义与 DeepEval 验收。配置补齐后主动运行，会消耗模型额度。"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import Settings
from app.services.models import invoke
from app.services.evaluation import evaluate, aggregate
from app.adapters.base import AgentResponse


async def main():
    settings = Settings()
    if not all(
        [
            settings.llm_base_url,
            settings.llm_model,
            settings.llm_api_key.get_secret_value(),
        ]
    ):
        blocked={"status":"blocked","reason":"LLM configuration missing","real_model_calls":0}
        (Path(__file__).resolve().parents[1]/'docs/evidence/stage3-real-model.json').write_text(json.dumps(blocked,indent=2),encoding='utf-8')
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "LLM configuration missing",
                    "real_model_calls": 0,
                }
            )
        )
        return 2
    config = {
        "base_url": settings.llm_base_url,
        "model": settings.llm_model,
        "temperature": 0,
        "timeout_seconds": settings.llm_timeout_seconds,
        "max_tokens": 4000,
    }
    key = settings.llm_api_key.get_secret_value()
    actual = await invoke(config, key, [("human", "请用一句中文回答：2+2等于几？")])
    case = {
        "user_input": "2+2等于几？",
        "expected_behavior": "回答算术问题",
        "expected_result": "4",
        "history": [],
        "rules": {
            "evaluators": ["llm_judge", "deepeval"],
            "rubric": "必须正确且相关地回答 2+2=4",
        },
    }
    details = await asyncio.wait_for(
        evaluate(
            case,
            AgentResponse(actual.content, None, 1, []),
            0,
            {"judge": (config, key)},
        ),
        180,
    )
    status = aggregate(details)
    result = {
        "status": status,
        "evaluations": details,
        "note": "真实调用结果，仅说明当前样本，不代表整体质量",
    }
    (
        Path(__file__).resolve().parents[1] / "docs/evidence/stage3-real-model.json"
    ).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": status,
                "evaluators": [
                    {"name": d["evaluator"], "status": d["status"]} for d in details
                ],
            }
        )
    )
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
