"""Milvus 独立服务层：向量操作不写入 MySQL 元数据。"""

from pymilvus import MilvusClient, DataType


class MilvusService:
    def __init__(self, uri: str, token: str = ""):
        self.client = MilvusClient(uri=uri, token=token, timeout=10)

    def ensure_chunks(self, dimension: int):
        name = "rag_document_chunks"
        if self.client.has_collection(name):
            description = self.client.describe_collection(name)
            field = next(f for f in description["fields"] if f["name"] == "embedding")
            if int(field["params"]["dim"]) != dimension:
                raise ValueError("existing collection dimension differs")
            return
        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=36)
        for field in ["document_id", "knowledge_base_id"]:
            schema.add_field(field, DataType.VARCHAR, max_length=36)
        schema.add_field("content", DataType.VARCHAR, max_length=65535)
        schema.add_field("source_name", DataType.VARCHAR, max_length=512)
        schema.add_field("page_number", DataType.INT64)
        schema.add_field("metadata", DataType.JSON)
        schema.add_field("created_at", DataType.VARCHAR, max_length=40)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)
        index = self.client.prepare_index_params()
        index.add_index("embedding", index_type="AUTOINDEX", metric_type="COSINE")
        self.client.create_collection(
            name, schema=schema, index_params=index, consistency_level="Strong"
        )

    def insert(self, chunks: list[dict]):
        return self.client.insert("rag_document_chunks", data=chunks)

    def search(
        self,
        knowledge_base_id: str,
        embedding: list[float],
        top_k: int = 5,
        document_ids=None,
    ):
        # ID 来自平台 UUID，额外校验后才放入 Milvus filter。
        from uuid import UUID

        key = str(UUID(knowledge_base_id))
        expression = f'knowledge_base_id == "{key}"'
        if document_ids is not None:
            if not document_ids:
                return [[]]
            import json

            expression += " and document_id in " + json.dumps(
                [str(UUID(i)) for i in document_ids]
            )
        return self.client.search(
            "rag_document_chunks",
            data=[embedding],
            anns_field="embedding",
            limit=top_k,
            filter=expression,
            output_fields=[
                "chunk_id",
                "document_id",
                "knowledge_base_id",
                "content",
                "source_name",
                "page_number",
                "metadata",
            ],
            consistency_level="Strong",
        )

    def delete_document(self, document_id: str):
        from uuid import UUID

        key = str(UUID(document_id))
        if not self.client.has_collection("rag_document_chunks"):
            return
        return self.client.delete(
            "rag_document_chunks", filter=f'document_id == "{key}"'
        )

    def close(self):
        self.client.close()

    def delete_knowledge_base(self, kb_id):
        from uuid import UUID

        key = str(UUID(kb_id))
        if not self.client.has_collection("rag_document_chunks"):
            return
        return self.client.delete(
            "rag_document_chunks", filter=f'knowledge_base_id == "{key}"'
        )
