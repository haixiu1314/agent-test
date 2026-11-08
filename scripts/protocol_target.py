"""常驻本机验收目标，明确非 AI，全部危险工具事件仅模拟且没有副作用。"""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size < 100000:
                raise ValueError("size")
            data = json.loads(self.rfile.read(size))
            mode = data.get("mode", "v1")
            if mode == "slow":
                time.sleep(2)
            if mode == "http_error":
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b'{"error":"fixture_unavailable"}')
                return
            bad = mode in ["v2", "unsafe"]
            payload = {
                "output": "故意错误的协议回答：0"
                if bad
                else "协议验收成功：" + str(data.get("input", "")) + "；计算结果：42",
                "events": [
                    {
                        "type": "tool_result",
                        "name": "delete_file" if mode == "unsafe" else "calculator",
                        "arguments": {"expression": "6*7"},
                        "success": True,
                        "result": {
                            "value": 0 if bad else 42,
                            "simulated": True,
                            "notice": "仅模拟事件，没有删除、转账或发送消息",
                        },
                    }
                ],
                "usage": {},
                "contexts": [],
                "fixture": True,
            }
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (ValueError, KeyError, TypeError):
            self.send_response(400)
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8001), Handler)
    print(
        "AgentTestLab NON-AI protocol fixture: http://127.0.0.1:8001 ; Ctrl+C to stop",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
