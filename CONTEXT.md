# CONTEXT.md — aifriend 领域词汇表

本文档定义 aifriend 项目的领域语言。Agent 在讨论设计、编写代码、审查 PR 时，必须使用本文档中的术语。

---

## 一、核心概念

**角色卡（Character Card）**：定义一个 AI 角色的完整配置文件，包含身份信息、性格设定、语音风格、规则约束等。角色卡是系统的核心数据单元，一个用户可拥有多个角色卡。

**card_type（角色卡类型）**：决定角色卡的玩法模式。只有两个合法值：
- `intimate` — 对话陪伴模式：侧重情感连接，追踪好感度，使用人生档案
- `scenario` — 剧情沙盒模式：侧重剧情推进，追踪沉浸度，使用剧情类型

**玩法（Play Mode）**：由 card_type 决定的两套独立的交互范式。"两种玩法隔离"是项目最高级别的架构约束。

---

## 二、intimate 玩法专属概念

**好感度（Affection）**：量化用户与 AI 角色之间亲密度和情感连接的数值指标。由 `character_affection.py` 服务管理，根据对话内容、互动频率、事件触发等因素动态调整。

**好感度等级**：基于好感度数值划分的阶段，不同等级解锁不同的对话行为和内容。

**人生档案（life_profile_json）**：intimate 角色卡的背景设定字段（JSONB），描述角色的成长经历、性格形成、重要人际关系等。只在 card_type=intimate 时使用。

**长期记忆（Long-term Memory）**：由 `memory_service.py` 管理，存储用户与 intimate 角色之间的重要互动片段，形成持久的情感纽带。

---

## 三、scenario 玩法专属概念

**沉浸度（Immersion）**：量化用户与剧情场景之间投入程度的数值指标。由 `story_event_service.py` 管理，根据剧情推进、选择后果、事件触发等因素计算。

**剧情类型（scenario_type）**：scenario 卡的子分类。当前支持：
- `adventure` — 冒险剧情
- `romance` — 恋爱剧情

**剧情阶段（Story Phase）**：由 `constants/story_phase.py` 定义，标记剧情沙盒中故事的进展阶段，含 scenario 卡专用语义。

**心情（Mood）**：由 `constants/mood.py` 定义的枚举，表示角色当前的情绪状态，含中英文标签映射。

---

## 四、技术架构概念

**分层架构**：`routers/ → services/ → repositories/ → core/ + constants/`。依赖方向严格单向：上层可依赖下层，下层不能依赖上层。core/ 通过回调注入访问 services/。

**回调注入（Callback Injection）**：core/ 层需要 services/ 功能时使用的解耦机制。在 `main.py` 的 lifespan 中注册回调函数，core/ 层通过回调接口调用，而非直接 import。

**ThreadedConnectionPool**：项目使用的数据库连接池实现（`core/database.py`），支持多线程并发访问 PostgreSQL。

**prompt_assembler（提示词组装器）**：核心服务之一，根据 card_type 选择不同的 prompt 构建逻辑。intimate 和 scenario 走完全不同的 prompt 模板。

**runtime_bundle（运行时数据包）**：在对话过程中动态组装的数据结构，包含角色设定、对话历史、好感度/沉浸度状态、token 预算等信息，传递给 AI 模型。

**token_budget（Token 预算）**：管理每次 AI 调用中 token 消耗的服务，确保 prompt + 回复不超过模型上下文窗口限制。

**stream（流式响应）**：AI 回复的逐字推送机制，由 `services/chat_stream/` 子包实现，通过 SSE（Server-Sent Events）推送到前端。

---

## 五、测试概念

**FakeSequenceConn**：测试专用的数据库连接模拟类。通过预定义的 `FakeQueryResult` 序列来模拟 SQL 查询的返回结果，而非使用真实数据库。修改路由/服务 SQL 后，必须同步更新对应测试的 FakeQueryResult。

**FakeQueryResult**：与 FakeSequenceConn 配合使用，定义模拟查询的返回数据和 fetchone/fetchall 行为。

**测试分层**：
- `tests/unit/` — 单元测试（29 文件），无需数据库
- `tests/services/` — 服务层测试（8 文件）
- `tests/routers/` — 路由层测试（7 文件）
- `tests/contracts/` — 契约测试（5 文件）
- `tests/integration/` — 集成测试（4 文件），需真实数据库
- `tests/regression/` — 回归测试（1 文件）
- `tests/load/` — 压力测试（1 文件）

---

## 六、高风险模块

以下 8 个区域修改时必须单独开分支，不能与其他修改混在一起：

1. `routers/admin/` — 管理后台路由
2. `routers/billing.py` — 付费路由
3. `services/chat_stream/` — 流式聊天服务（子包）
4. `services/chat_send.py` — 聊天发送服务
5. `core/auth/` — 认证模块（子包）
6. `core/database.py` — 数据库连接管理
7. `repositories/` — 数据访问层（全部 6 个模块）
8. `alembic/versions/` — 数据库迁移脚本

---

## 七、数据库约定

- **int 列**：用 `1`/`0`，禁止 `True`/`False`
- **jsonb 列**：直接传 Python dict
- **历史遗留 text JSON 列**：用 `json.dumps()`/`json.loads()` 序列化
- **游标生命周期**：`fetchone()` 必须在 `conn.commit()` 之前调用 — commit 会关闭所有游标
- **连接获取**：路由层通过 `get_db_dep()` 获取连接，禁止使用 `with get_db()`

---

## 八、代码质量约定

- **单文件上限 1000 行**：超出必须拆分；确实无法拆分时在文件顶部注明原因
- **工具函数按功能分文件**：禁止大杂烩式的 util 文件
- **设计模式一致**：新增模块必须与现有模块采用同一设计模式
- **错误处理**：禁止 `assert` 做运行时校验，改用 `if + raise HTTPException`；用户侧错误返回 4xx，服务端错误用 `logger.exception()` + 500
- **代码质量三要素**：可维护性（maintainability）、边界条件（boundary conditions）、回归风险（regression risk）
