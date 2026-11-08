# Navicat 建库、数据迁移与单终端启动

更新：2026-11-06。源码目录：`E:\Project-xhb\ai-test`。

## 当前进展

已提供 `deploy/agenttest-Navicat-MySQL8.sql`，在 MySQL 8 的空库中实际执行验证通过：25 张业务表 + `alembic_version` 共 26 张表，版本 `0007_delivery`。SQL 不包含密码、账号修改、DROP 或业务数据。

3306 服务可连接，但本次使用你给出的 root 凭据返回 **1045（认证失败）**，因此尚未在 3306 创建业务库，也没有切换 `.env`。当前运行仍使用 `127.0.0.1:3307/agenttestlab`，旧数据保留。不要把下面的目标地址误认为已完成迁移。

目标为 **`localhost:3306/agenttest`**。请使用 Navicat 中实际能登录的账号，或在本地终端输入正确密码，不需要把密码发到聊天里。

## 1. 选择一种数据库方式

| 方式 | 适合什么情况 | 结果 |
| --- | --- | --- |
| A：迁移旧数据 | 想继续使用已有账号、项目、用例、任务与报告 | 复制旧库，按表核对内容后切换配置；旧库保留 |
| B：SQL 全新建库 | 想在 Navicat 直接创建结构、从头使用平台 | 建立空库，需要重新注册和创建业务数据 |

两种方式只选一种。**方式 A 之前不要执行方式 B 的 SQL**，因为迁移脚本拒绝向已有表的目标库复制数据。两种方式都不会覆盖已有目标表。

### 方式 A：保留旧数据迁移

1. 在运行平台的终端按 `Ctrl+C`，停止本项目的前后端，暂停或结束活动任务。保持旧 3307 MySQL 可连接。
2. 在项目根目录执行：

```powershell
cd E:\Project-xhb\ai-test
npm run db:migrate
```

3. 用户名回车采用 `root`；密码在本机终端隐藏输入。确保该密码能连接本机 3306。
4. 脚本只接受空的 `agenttest`，创建数据库并用 Alembic 建立结构，然后在一致性快照中复制 25 张业务表，逐表核对行数与完整内容摘要，最后更新 `.env`。加密密钥和 JWT 配置保留。

预期：输出 `status=passed`、`target=localhost:3306/agenttest`、`configuration_switched=true`；生成 `docs/evidence/localhost-migration.json`。只有出现成功结果，才算迁移完成。旧库保留，原 `.env` 私密备份在 `.local/env-before-3306-*.backup`。

错误处理：1045 是账号密码或连接授权问题；目标已有表会拒绝；活动任务会拒绝。若复制中途失败，目标可能留下结构，但事务中的业务行会回滚，配置在核对通过前不会切换。不要反复强制执行或删除旧库，先核对目标状态、备份后处理。

### 方式 B：Navicat 执行 SQL，全新开始

1. Navicat 打开 MySQL 连接：主机 `localhost`、端口 `3306`、用户名 `root`，密码使用本地有效密码。先“测试连接”。1045 时应先修正连接，SQL 本身不能解决认证失败。
2. 确认连接为 MySQL 8。`agenttest` 应不存在或是空库；有业务表时不要继续执行。
3. 在连接上右键“运行 SQL 文件”，选择：

```text
E:\Project-xhb\ai-test\deploy\agenttest-Navicat-MySQL8.sql
```

4. 编码选 UTF-8，运行完成后刷新连接并展开 `agenttest → 表`。
5. 在查询窗口执行：

```sql
USE agenttest;
SELECT DATABASE() AS current_database;
SELECT COUNT(*) AS table_count
FROM information_schema.tables
WHERE table_schema = 'agenttest' AND table_type = 'BASE TABLE';
SELECT version_num FROM alembic_version;
```

预期依次为 `agenttest`、`26`、`0007_delivery`。可看到 users、projects、agents、test_cases、test_tasks、reports 等业务表。SQL 不复制旧项目和账号，也不创建登录用户。

6. 将项目连接切到新库，在根目录执行：

```powershell
npm run db:configure
```

输入本地有效用户名和隐藏密码。脚本验证能连接、26 张表齐全、迁移版本正确后，才备份并更新 `.env` 的 `DATABASE_URL`。其他配置保留。预期提示 `Database configured: localhost:3306/agenttest`。失败时不切换连接。

## 2. 日常只启动一个终端

```powershell
cd E:\Project-xhb\ai-test
npm run dev
```

无需分别运行前后端脚本，也无需在根目录执行 npm install；现有 Python 和前端依赖继续复用。MySQL 3306 的 Windows 服务需要正常运行，启动器不会修改系统服务账号或安装服务。若还未切库且仍使用原 3307 配置，启动器会在必要时调用原项目数据库启动脚本。

启动器依次检查端口、验证数据库、执行 Alembic 升级、启动后端、检查后端健康、启动 Vite 并打开默认浏览器。终端最终显示：

```text
AgentTestLab ready
  Web:      http://127.0.0.1:5173
  API docs: http://127.0.0.1:8000/docs
  Health:   http://127.0.0.1:8000/health/ready
  Stop frontend/backend together: Ctrl+C
```

预期：网页能登录；健康接口返回 `database=ok`。终端 `Database:` 行应显示你当前实际连接的库，切换成功后为 `localhost:3306/agenttest`。只看到旧库说明尚未切换，不要把启动成功当迁移成功。

`Ctrl+C` 同时停止本次启动的前后端，MySQL 服务继续运行。端口被其他进程占用时明确退出，不自动结束已有进程。不想自动打开浏览器时用 `npm run dev -- --no-open`。

## 3. 按全功能手册验收

完整手工验收还需要本机非 AI 协议目标。停止普通启动后，改用：

```powershell
npm run dev:verify
```

一个终端启动后端、前端和 8001 协议服务，显示全部地址。8001 仅支持 POST，直接在地址栏访问出现方法错误是正常情况。它只验证平台协议、规则、风险证据和回归流程，不代表真实 AI。

需要输入其他验证命令时，再开一个临时终端即可，不必为每个服务单独开窗口。继续按 [全功能操作与验收手册](全功能操作与验收手册.md) 第 3 节开始操作，每项均有预期结果。

## 4. 常见问题

| 现象 | 处理 |
| --- | --- |
| `npm` 不是命令 | 重开终端使 Node PATH 生效，用 `node --version`、`npm --version` 检查；本机已存在 Node 与 npm |
| PowerShell 提示 npm.ps1 禁止运行 | 同一终端用 `npm.cmd run dev`，不需要修改全局执行策略 |
| 找不到 package.json | 先切换到 `E:\Project-xhb\ai-test`，不要在 backend 目录启动 |
| 端口 8000 / 5173 / 8001 被占用 | 找到自己的旧启动终端按 Ctrl+C，或关闭冲突的应用；不要乱杀进程 |
| MySQL 1045 | 使用能实际登录的密码，确认连接端口与用户授权；不将密码写进 SQL 或聊天 |
| 数据库不存在或缺表 | 选择 A 迁移，或 B 完整导入 SQL 后执行 db:configure；不要把两种初始化方式叠加 |
| 新库登录不了旧账号 | 方式 B 是空库，需要新注册；保留旧数据应使用方式 A |
| 模型或 Milvus 不可用 | 不影响普通平台启动，但真实模型/向量功能仍需单独配置与验收 |

当前新增验证：3 项启动检查通过，SQL 在 3307 的临时库真实执行通过并已清理。**3306 的业务建库、数据迁移和连接切换尚未验收通过**，原因是本次凭据认证失败。历史 124 后端、6 浏览器、93 MySQL/API 结果仍属于此前环境，不冒充 3306 的验收结果。
