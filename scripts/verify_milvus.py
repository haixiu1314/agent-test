"""真实 Milvus 冒烟验证：临时集合 + 明确标注的人工测试向量。"""
import json
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.core.config import Settings
from pymilvus import MilvusClient

def main():
    settings = Settings()
    name = 'atl_smoke_' + uuid4().hex
    client = None
    try:
        client = MilvusClient(uri=settings.milvus_uri, token=settings.milvus_token.get_secret_value(), timeout=10)
        client.create_collection(name, dimension=4, metric_type='COSINE')
        client.insert(name, [{'id': 1, 'vector': [1., 0., 0., 0.]}])
        hits = client.search(name, data=[[1., 0., 0., 0.]], limit=1, consistency_level='Strong')
        assert hits[0][0]['id'] == 1
        client.delete(name, ids=[1])
        assert not client.query(name, filter='id == 1', consistency_level='Strong')
        print(json.dumps({'status': 'passed', 'checks': ['insert', 'search', 'delete'], 'vectors': 'synthetic protocol fixture; not embedding validation'}))
    except Exception as exc:
        # pymilvus 日志可能打印目标地址；不打印可能包含 token 的原始异常。
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}))
        return 1
    finally:
        if client is not None:
            try:
                if client.has_collection(name):
                    client.drop_collection(name)
            finally:
                client.close()
    return 0

if __name__ == '__main__':
    sys.exit(main())
