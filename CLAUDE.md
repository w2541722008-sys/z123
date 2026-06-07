# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp backend/.env.example backend/.env   # 然后编辑 .env 配置 DATABASE_URL、AIFRIEND_API_KEY 等

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
- `backend/core/` — 基础设施层：`auth/`（JWT + 缓存回调注入，6 文件子包）、`schemas/`（Pydantic 模型，8 文件子包）、`database.py`（ThreadedConnectionPool）、`config.py`、`exceptions.py`（领域异常）、`character_state_snapshot.py`、`model_adapter.py`（AI 模型适配）、`plan_constants.py`（会员档位常量）
- `backend/services/` — 业务逻辑层（27 个模块）。核心服务：`chat_send.py`、`chat_stream/`（流式子包，3 文件）、`chat_stream_service.py`（向后兼容 shim）、`chat_query.py`、`chat_retry.py`、`prompt_assembler.py`、`prompt_builder.py`、`runtime_bundle.py`、`token_budget.py`、`character_state.py`、`character_affection.py`、`character_insights_service.py`、`character_session_service.py`、`story_event_service.py`、`memory_service.py`、`state_snapshot.py`、`world_info_service.py`、`password_reset_service.py`、`plan_service.py`、`billing_order_service.py`、`cache_service.py`、`rate_limit.py`、`usage_guard.py`、`circuit_breaker.py`、`health_service.py`、`email.py`、`db_monitor.py`
- `backend/routers/` — 路由层：`auth.py`、`billing.py`、`characters.py`、`chat/`（包式路由，含 `_route_builders.py`）、`media.py`、`admin/`（按域拆分：`_router.py` + `_helpers.py` + `characters_core.py`、`characters_insights.py`、`characters_memory.py`、`characters_rules_events.py`、`characters_story.py` + `users.py` + `orders.py` + `dashboard.py`）
- `backend/repositories/` — 纯 SQL 层（14 个模块）：`auth_repository.py`、`billing_repository.py`、`character_repository.py`、`character_admin_memory_repository.py`、`character_admin_story_repository.py`、`character_memory_repository.py`、`character_state_repository.py`、`chat_repository.py`、`story_repository.py`、`user_repository.py`、`admin_audit_repository.py`、`admin_dashboard_repository.py`、`usage_repository.py`、`__init__.py`
- `backend/constants/` — 枚举常量：`mood.py`（Mood 枚举 + 中英文标签映射）、`story_phase.py`（StoryPhase 枚举 + 标签映射，含 scenario 卡专用语义）、`prompt_templates.py`（AI 提示模板）
- `backend/utils/` — 通用工具：`card_text.py`、`json_utils.py`、`stream_filter.py`
- `frontend/modules/` — 原生 JS IIFE 模块（用户端聊天 UI，18 个模块）
- `frontend/admin/js/` — 管理后台 JS 模块（18 个模块）
- `tests/` — `unit/`（30 文件）、`services/`（12 文件）、`routers/`（8 文件）、`contracts/`（5 文件）、`integration/`（需真实 DB，4 文件）、`regression/`（1 文件）、`load/`（1 文件）

## 协作规则（必须严格遵守）

- **全程使用中文**：所有回复、代码注释、说明文档一律中文
- **解释要接地气**：用比喻或举例说明，避免堆砌专业术语
- **多方案时**：一句话说清区别，直接给出推荐，不让用户自己选
- **文件结构**：按功能分文件夹，目录名让零基础用户也能看懂用途
- **单文件上限 1000 行**：超出必须拆分；确实无法拆分时需在文件顶部注明原因
- **工具函数分类存放**：按功能分文件，禁止大杂烩式的 util 文件
- **新代码保持设计模式一致**：必须与现有模块采用同一设计模式，不引入新的架构风格
- **新增功能同步配置**：增加了项目功能后，要同步判断是否需要在后台管理界面加入相关配置
- **新增功能同步测试**：增加了项目功能后，要同步判断是否需要增加测试以及数据库变更
- **代码质量三要素**：写代码时从三个维度审视——可维护性（maintainability）、边界条件（boundary conditions）、回归风险（regression risk）。代码质量决定系统能否上线，以资深架构师的专业水准完成每一项任务

## 测试账号

- 管理后台测试账号：`773682014@qq.com` / `jie159357`（管理员白名单邮箱，用于 API 测试和角色卡导入）

## 关键规则

**两种玩法隔离**：
- 对话陪伴（`card_type=intimate`）：使用人生档案（`life_profile_json`），追踪好感度，重视长期记忆
- 剧情沙盒（`card_type=scenario`）：使用剧情类型（`scenario_type`：adventure/romance），追踪沉浸度，不使用人生档案
- 管理后台根据 `card_type` 动态显示字段，避免配置混乱
- 后端 `prompt_assembler.py` 根据 `card_type` 选择不同的 prompt 构建逻辑

**游标生命周期**：`fetchone()` 必须在 `conn.commit()` 之前调用——commit 会关闭所有游标。

**数据库类型**：int 列用 `1`/`0`，禁止 `True`/`False`。`jsonb` 列直接传 dict。历史遗留 `text` JSON 列用 `json.dumps()`/`json.loads()`。

**连接管理**：路由层通过 `get_db_dep()` 获取连接，禁止在路由层使用 `with get_db()`。

**错误处理**：禁止 `assert` 做运行时校验——改用 `if + raise HTTPException`。用户侧错误：`4xx`，不暴露内部细节。服务端错误：`logger.exception()` + 500。

**测试 Mock**：`FakeSequenceConn` 模拟 DB。修改路由/服务 SQL 后，必须同步更新对应测试的 `FakeQueryResult`。

**高风险模块**（需单独开分支）：`routers/admin/`、`routers/billing.py`、`services/chat_stream/`、`services/chat_send.py`、`core/auth/`、`core/database.py`、`repositories/`、`alembic/versions/`

**分层依赖**：`core/` 不能导入 `services/`——通过回调注入解耦（见 `main.py` lifespan 中的 `register_cache_callbacks`）。

**生产数据库**：绝对禁止对生产数据库执行任何写操作（INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER）。Agent 不知道也不应该知道生产数据库连接信息。仅允许操作本地开发数据库和测试数据库。

## Agent skills

本项目的 Claude Code skills 位于 `.claude/skills/`，在需要对应场景时会自动触发：

- **diagnose** — 结构化诊断循环。遇到复杂 bug 或性能回归时启动，六阶段流程（建立反馈循环→复现→假设→插桩→修复→清理）
- **git-guardrails** — 安全护栏。自动拦截 git push、git reset --hard、DROP TABLE、无 WHERE 的 DELETE 等不可逆操作
- **to-issues** — 需求拆分。将计划/PRD 拆分为垂直切片 issue，每个切片横切所有层级（schema→API→service→repo→前端→管理后台→测试），自动检查后台管理配置和数据库变更需求
- **tdd** — 测试驱动开发。red-green-refactor 循环，高风险模块强制 TDD，使用 FakeSequenceConn 做数据库隔离
- **handoff** — 会话交接。压缩当前会话为交接文档（输出到 `.scratch/`），去重脱敏，标注建议技能
- **triage** — Issue 分类。状态机流程（needs-triage→needs-info→ready-for-agent/ready-for-human/wontfix/needs-db-migration），含高风险模块影响评估
- **grill-with-docs** — 文档化设计审查。将计划与 CONTEXT.md 领域模型对照挑战，更新术语表，为不可逆决策创建 ADR
- **improve-codebase-architecture** — 架构深化审查。用删除测试和 Bouncing 检测发现模块边界问题，与"单文件1000行""设计模式一致"规则互补
- **grill-me** — 深度设计访谈。逐分支遍历设计决策树（仅在用户明确要求时触发，日常不自动激活）
- **zoom-out** — 宏观视角切换。用领域术语输出模块全景图、数据流和关键决策点
- **prototype** — 丢弃式原型。终端交互式（Python）或 UI 多版本切换（原生 JS），得到答案后删除
- **write-a-skill** — 创建新技能。按标准结构生成 SKILL.md，支持渐进披露和内置脚本

配套文档：
- `CONTEXT.md` — 领域词汇表，Agent 讨论设计和代码时使用
- `.out-of-scope/` — Agent 行为边界：禁止操作生产库、禁止修改 card_type 枚举、禁止 core/ 导入 services/
- `docs/agents/` — Agent 运维配置：issue tracker 信息、triage 标签映射
- `docs/adr/` — 架构决策记录（4 篇）：两种玩法隔离、分层依赖解耦、连接池选型、测试模拟模式

## 项目文档

- [docs/README.md](docs/README.md) — 文档总导航
- [docs/API.md](docs/API.md) — API 接口文档
- [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) — 部署指南
- [docs/AFFECTION_SYSTEM.md](docs/AFFECTION_SYSTEM.md) — 好感度系统设计
- [docs/CHARACTER_IMPORT_SOP.md](docs/CHARACTER_IMPORT_SOP.md) — 角色卡导入流程
- [docs/ADMIN_PANEL_GUIDE.md](docs/ADMIN_PANEL_GUIDE.md) — 管理后台使用指南
- [docs/FRONTEND_ARCHITECTURE.md](docs/FRONTEND_ARCHITECTURE.md) — 前端架构说明
