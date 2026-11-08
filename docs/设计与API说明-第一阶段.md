# 第一阶段设计与 API 说明

## 范围与架构

应用版本 0.1.0，前后端分离，正常运行使用 MySQL 8。当前不启动异步测试执行引擎，也没有为后续功能创建空接口。

API 层：FastAPI；验证模型：Pydantic 2；数据访问：SQLAlchemy 2；迁移：Alembic；鉴权：HS256 JWT；密码：scrypt；Agent 凭证：Fernet；网络：HTTPX；前端：Vue 3/TypeScript/Vite/Element Plus/Axios。

本机 Python 3.12.7，Node 24.22.1，项目内 npm 10.9.2。后端完整精确版本见 `backend/requirements.lock`，前端见 `frontend/package-lock.json`。LangChain、DeepEval、RAGAS 尚未进入本阶段依赖，后续在同一隔离环境解析兼容组合并更新锁文件。

## 数据表

所有业务表使用 36 字符 UUID 主键、UTC 创建/更新时间（MySQL DATETIME，接口返回无时区值，前端按 UTC 解读）。

| 表 | 核心字段 | 关联 |
| --- | --- | --- |
| users | username 唯一、password_hash、role | 项目所有者 |
| projects | owner_id、name、description、business_type | owner_id → users |
| agents | project_id、name、kind、config JSON、secret 密文、version | project_id → projects |
| agent_versions | agent_id、version、snapshot JSON、secret 密文 | agent_id → agents；agent_id/version 唯一 |
| operation_logs | user_id、action、resource_id、request_id | user_id → users；资源 ID 保留以审计删除 |

外键列及主要关联有索引。Agent 版本与当前配置分表保存；删除 Agent 明确删除版本，删除项目遇到关联 Agent 返回 409。用户删除不属于本阶段功能。

建表 SQL：`deploy/schema-stage1.sql`。升级应用使用 Alembic；SQL 文件作为结构审阅材料，不要在已经迁移的数据库重复执行。

业务账号只获 `agenttestlab.*` 上的 SELECT/INSERT/UPDATE/DELETE/CREATE/ALTER/DROP/INDEX/REFERENCES，不具备全实例管理权限；保留 DDL 权限用于本地开发迁移，未来生产环境应分离迁移账号和运行账号。

## API 契约

完整可机读契约为 `docs/openapi.json`，运行后可访问 `/docs`。前缀 `/api/v1`。

| 方法与路径 | 输入/输出及行为 |
| --- | --- |
| POST /auth/register | Credentials → id/username/role；201；公开注册固定 tester |
| POST /auth/login | Credentials → access_token/token_type/expires_in；200 |
| GET /auth/me | Bearer JWT → 当前公开用户 |
| GET /projects | page/page_size → 项目分页 |
| POST /projects | ProjectInput → ProjectPublic；201 |
| GET /projects/{id} | ProjectPublic，越权或不存在均 404 |
| PUT /projects/{id} | 全量 ProjectInput → 更新项目 |
| DELETE /projects/{id} | 204；有关联 Agent 返回 409 |
| GET /agents | 可选 project_id，page/page_size → Agent 分页 |
| POST /agents | AgentInput → AgentPublic；201，创建首个快照 |
| GET /agents/{id} | 当前公开配置，不返回 header 值、api_key、密文 |
| PUT /agents/{id} | AgentInput + expected_version；更新并追加快照；版本过期返回 409 |
| DELETE /agents/{id} | 204，删除配置与版本，保留审计 |
| GET /agents/{id}/versions | 版本分页与公开快照 |
| POST /agents/{id}/test-connection | input/history → success/error_code/duration_ms/status_code/attempts/output_received/tool_events/request_id |
| GET /system/operation-logs | 仅管理员，分页查询审计日志 |

所有列表默认每页 20，范围 1–100，page 最小 1。项目、Agent 和版本响应包含 items/total/page/page_size。操作日志当前返回 items/total。

探活 `/health/live` 不查数据库；就绪 `/health/ready` 检查迁移表和 users 表；两者不需要认证，不返回连接凭证。

## 错误和边界

错误结构：

```json
{"error":{"code":"validation_error","message":"输入格式不正确，请检查字段","details":[{"field":"body.name","type":"string_too_short"}]},"request_id":"本次请求的 UUID"}
```

401 身份无效；403 权限不足；404 资源不可见；409 重复用户名/版本冲突/关联删除限制；413 请求体超过 1 MiB；422 字段错误；429 认证限流；503 数据库不可用；500 未预期内部错误。

连接测试中，上游失败属于已执行的业务结果，HTTP 200 且 `success=false`，`error_code` 说明原因；权限和输入错误仍用 HTTP 状态码。失败连接当前不回传尝试次数，返回 null。

HTTP Agent 支持 GET/POST、嵌套对象路径、可选历史、每次 0.1–60 秒超时、0–3 次重试、响应最大 1 MiB。不跟随重定向；不读取代理环境配置；仅网络、超时、502/503/504 重试。Python 适配器采用白名单，不执行任意上传代码。

当前后端绑定 loopback。HTTP 接入允许访问本机服务，这是产品接入需求；未来对非受信用户或公网部署时，需要追加目标地址白名单与独立网络执行隔离，不能直接将本开发服务器暴露公网。

## 部署设计

当前独立数据库不注册为 Windows 服务，通过本地脚本启动。3307 端口只绑定 127.0.0.1，禁用 MySQL X 端口，InnoDB 缓冲池 128 MiB。原 3306 实例未改动。

Milvus Standalone 使用 Compose，etcd、MinIO 不暴露宿主端口，19530/9091 只绑定 loopback。固定镜像版本及随机 MinIO 凭证已配置，但尚未运行验收，因此不能称为已验证的部署组合。

前端当前使用 Vite 开发/预览代理转发到 8000。正式部署的静态托管、HTTPS 和反向代理属于后续部署交付，不在本阶段声称完成。
