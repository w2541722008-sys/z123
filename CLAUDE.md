# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Run dev server
cd backend && python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Run tests (unit/routers/services, excludes integration)
cd backend && python3 -m pytest ../tests/ -q --ignore=../tests/integration

# Run a single test file
cd backend && python3 -m pytest ../tests/unit/test_prompt_assembler_service.py -q

# Frontend tests
node tests/test_frontend_utils.js
node tests/check_admin_actions.js --strict --allow-list=tests/admin_action_allowlist.json

# DB migrations
cd backend && python3 -m alembic upgrade head

# Deploy
bash deploy.sh   # rsync → migrate → restart → health check
bash rollback.sh
```

## Architecture

```
routers/ → services/ → repositories/ → core/ + constants/
```

- `backend/main.py` — FastAPI 应用入口，注册所有路由到 `/api`，托管前端静态文件
- `backend/core/` — 基础设施层：`auth.py`（JWT + 缓存回调注入）、`database.py`（ThreadedConnectionPool）、`config.py`、`schemas.py`（Pydantic 模型）、`model_adapter.py`（AI 模型适配）、`plan_constants.py`（会员档位常量）
- `backend/services/` — 业务逻辑层（28 个模块）。核心服务：`chat_send.py`、`chat_stream_service.py`、`chat_stream_infra.py`、`chat_stream_persist.py`、`prompt_assembler.py`（已从 core 迁移）、`prompt_builder.py`、`runtime_bundle.py`、`memory_core.py`、`memory_summary.py`、`memory_background.py`、`token_budget.py`、`character_state.py`、`story_event_service.py`、`memory_service.py`、`plan_service.py`、`billing_order_service.py`、`cache_service.py`、`rate_limit.py`、`usage_guard.py`、`health_service.py`、`email.py`、`db_monitor.py`、`jobs_facade.py` 等
- `backend/routers/` — 路由层：`auth.py`、`billing.py`、`characters.py`、`chat/`（包式路由，含 `_route_builders.py`）、`media.py`、`admin/`（按域拆分：`_router.py` + `_shared.py` + `characters_core/insights/memory/rules_events/story` + `users` + `orders` + `dashboard`）
- `backend/repositories/` — 纯 SQL 层（6 个模块）：`character_repository.py`、`character_memory_repository.py`、`chat_repository.py`、`user_repository.py`、`billing_repository.py`、`auth_repository.py`
- `backend/constants/` — 枚举常量：`mood.py`（Mood 枚举 + 中英文标签映射）、`story_phase.py`（StoryPhase 枚举 + 标签映射，含 scenario 卡专用语义）
- `backend/utils/` — 通用工具：`card_text.py`、`json_utils.py`、`stream_filter.py`
- `frontend/modules/` — 原生 JS IIFE 模块（用户端聊天 UI，14 个模块）
- `frontend/admin/js/` — 管理后台 JS 模块（17 个模块）
- `tests/` — `unit/`（25 文件）、`services/`（6 文件）、`routers/`（7 文件）、`contracts/`（6 文件）、`integration/`（需真实 DB，2 文件）、`regression/`（1 文件）

## 协作规则（必须严格遵守）

- **全程使用中文**：所有回复、代码注释、说明文档一律中文
- **解释要接地气**：用比喻或举例说明，避免堆砌专业术语
- **多方案时**：一句话说清区别，直接给出推荐，不让用户自己选
- **文件结构**：按功能分文件夹，目录名让零基础用户也能看懂用途
- **单文件上限 1000 行**：超出必须拆分；确实无法拆分时需在文件顶部注明原因

## 关键规则

**游标生命周期**：`fetchone()` 必须在 `conn.commit()` 之前调用——commit 会关闭所有游标。

**数据库类型**：int 列用 `1`/`0`，禁止 `True`/`False`。`jsonb` 列直接传 dict。历史遗留 `text` JSON 列用 `json.dumps()`/`json.loads()`。

**连接管理**：路由层通过 `get_db_dep()` 获取连接，禁止在路由层使用 `with get_db()`。

**错误处理**：禁止 `assert` 做运行时校验——改用 `if + raise HTTPException`。用户侧错误：`4xx`，不暴露内部细节。服务端错误：`logger.exception()` + 500。

**测试 Mock**：`FakeSequenceConn` 模拟 DB。修改路由/服务 SQL 后，必须同步更新对应测试的 `FakeQueryResult`。

**高风险模块**（需单独开分支）：`routers/admin/`、`routers/billing.py`、`services/chat_stream_service.py`、`services/chat_send.py`、`core/auth.py`、`core/database.py`、`repositories/`、`alembic/versions/`

**分层依赖**：`core/` 不能导入 `services/`——通过回调注入解耦（见 `main.py` lifespan 中的 `register_cache_callbacks`）。
