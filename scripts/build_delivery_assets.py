"""生成无数据的 MySQL DDL、最新 OpenAPI、可导入 Postman 目录及样例验收资料。"""

import json
from pathlib import Path
from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.dialects.mysql import dialect
from app.main import create_app
from app.models.entities import Base

root = Path(__file__).resolve().parents[1]
app = create_app()
schema = app.openapi()
(root / "docs/openapi.json").write_text(
    json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
)
ddl = [
    "-- AgentTestLab 0007_delivery / MySQL 8 / schema only; no credentials or data.\n-- Normal upgrades use Alembic. Do not execute against a database containing existing tables."
]
for table in Base.metadata.sorted_tables:
    ddl.append(str(CreateTable(table).compile(dialect=dialect())) + ";")
    ddl.extend(
        str(CreateIndex(index).compile(dialect=dialect())) + ";"
        for index in table.indexes
    )
(root / "deploy/schema.sql").write_text("\n\n".join(ddl), encoding="utf-8")


def example(spec, depth=0):
    if depth > 5:
        return None
    if "$ref" in spec:
        return example(
            schema["components"]["schemas"][spec["$ref"].split("/")[-1]], depth + 1
        )
    if "default" in spec:
        return spec["default"]
    if "enum" in spec:
        return spec["enum"][0]
    if "anyOf" in spec:
        return example(spec["anyOf"][0], depth + 1)
    kind = spec.get("type")
    if kind == "object":
        return {
            k: example(v, depth + 1)
            for k, v in spec.get("properties", {}).items()
            if k in spec.get("required", [])
        }
    if kind == "array":
        return [example(spec["items"], depth + 1)] if spec.get("minItems", 0) else []
    if kind == "integer":
        return max(spec.get("minimum", 1), 1)
    if kind == "number":
        return spec.get("minimum", 1)
    if kind == "boolean":
        return False
    return "填写有效值"


groups = {}
for path, methods in schema["paths"].items():
    for method, operation in methods.items():
        if method not in ["get", "post", "put", "delete", "patch"]:
            continue
        url = "{{base_url}}" + path
        for param in operation.get("parameters", []):
            if param["in"] == "path":
                url = url.replace(
                    "{" + param["name"] + "}", "{{" + param["name"] + "}}"
                )
        query = [
            p["name"] + "={{" + p["name"] + "}}"
            for p in operation.get("parameters", [])
            if p["in"] == "query" and p.get("required")
        ]
        if query:
            url += "?" + "&".join(query)
        request = {
            "method": method.upper(),
            "header": [{"key": "Authorization", "value": "Bearer {{token}}"}],
            "url": url,
            "description": "由当前 OpenAPI 自动生成的接口目录。请求模板需按操作手册填写真实 ID 与字段；不是可无配置顺序运行的测试。",
        }
        body = (
            operation.get("requestBody", {}).get("content", {}).get("application/json")
        )
        if body:
            request["body"] = {
                "mode": "raw",
                "raw": json.dumps(
                    example(body["schema"]), ensure_ascii=False, indent=2
                ),
                "options": {"raw": {"language": "json"}},
            }
            request["header"].append(
                {"key": "Content-Type", "value": "application/json"}
            )
        groups.setdefault(operation.get("tags", ["other"])[0], []).append(
            {"name": method.upper() + " " + path, "request": request}
        )
collection = {
    "info": {
        "name": "AgentTestLab 全接口目录 0007",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "variable": [
        {"key": "base_url", "value": "http://127.0.0.1:8000"},
        {"key": "token", "value": ""},
    ],
    "item": [{"name": key, "item": value} for key, value in groups.items()],
}
(root / "tests/postman").mkdir(parents=True, exist_ok=True)
(root / "tests/postman/AgentTestLab.postman_collection.json").write_text(
    json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    json.dumps(
        {
            "tables": len(Base.metadata.tables),
            "api_operations": sum(len(v) for v in groups.values()),
            "schema_sql": "deploy/schema.sql",
            "postman": "tests/postman/AgentTestLab.postman_collection.json",
        }
    )
)
