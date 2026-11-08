"""真实 RAGAS 算法 + 本地 OpenAI 协议替身；不作为真实模型或 Milvus 验收。"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from app.integrations.professional import ragas_eval


@pytest.fixture
def provider():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(self.path)
            if self.path.endswith("/embeddings"):
                inputs = (
                    data["input"]
                    if isinstance(data["input"], list)
                    else [data["input"]]
                )
                result = {
                    "object": "list",
                    "model": "fixture",
                    "data": [
                        {
                            "object": "embedding",
                            "index": i,
                            "embedding": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                        }
                        for i, _ in enumerate(inputs)
                    ],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                }
            else:
                prompt = " ".join(str(m["content"]) for m in data["messages"])
                if "ContextRecallClassifications" in prompt:
                    content = {
                        "classifications": [
                            {
                                "statement": "保修一年",
                                "reason": "fixture",
                                "attributed": 1,
                            }
                        ]
                    }
                elif "NLIStatementOutput" in prompt:
                    content = {
                        "statements": [
                            {"statement": "保修一年", "reason": "fixture", "verdict": 1}
                        ]
                    }
                elif "StatementGeneratorOutput" in prompt:
                    content = {"statements": ["保修一年"]}
                elif "ResponseRelevanceOutput" in prompt:
                    content = {"question": "保修期是多久？", "noncommittal": 0}
                else:
                    content = {
                        "reason": "fixture context supports answer",
                        "verdict": 1,
                    }
                result = {
                    "id": "explicit-local-fixture",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "fixture",
                    "choices": [
                        {
                            "index": i,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(content),
                            },
                        }
                        for i in range(data.get("n", 1))
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            raw = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield (
        {
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "model": "explicit-fixture",
            "temperature": 0,
            "timeout_seconds": 10,
            "max_tokens": 1000,
        },
        calls,
    )
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,keys",
    [
        ("retrieval", {"context_precision", "context_recall"}),
        ("generation", {"faithfulness", "answer_relevancy"}),
        (
            "combined",
            {"context_precision", "context_recall", "faithfulness", "answer_relevancy"},
        ),
    ],
)
async def test_actual_ragas_metrics_over_local_protocol(provider, mode, keys):
    config, calls = provider
    result = await ragas_eval(
        "保修期是多久？",
        "保修一年",
        "保修一年",
        ["保修一年"],
        (config, "fixture-key"),
        (config, "fixture-key"),
        mode=mode,
    )
    assert set(result) == keys and all(v == pytest.approx(1.0) for v in result.values())
    assert any(path.endswith("/chat/completions") for path in calls)
    if mode != "retrieval":
        assert any(path.endswith("/embeddings") for path in calls)
