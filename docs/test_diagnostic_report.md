# AIFriend 测试功能诊断报告

> 诊断时间：2026-05-03 | 基线：371 passed / 覆盖率阈值 49%

---

## 一、执行摘要

当前测试体系存在 **5 类结构性缺陷**，导致严重错误被遗漏。核心问题是：**测试全部基于 FakeConn Mock，从不执行真实 SQL**，这意味着 SQL 语法错误、参数对齐错误、类型不匹配、事务边界问题等生产环境最常出现的 Bug，测试完全无法捕获。

| 缺陷类别 | 严重度 | 影响范围 |
|----------|--------|---------|
| 1. 零集成测试 — 无真实 SQL 执行 | 🔴 致命 | 全部 DB 交互模块 |
| 2. 49% 覆盖率阈值过低 | 🔴 致命 | 51% 代码无任何测试保护 |
| 3. repositories 层零测试 | 🔴 致命 | SQL 集中管理但无验证 |
| 4. 服务层大面积测试空白 | 🟠 严重 | 13/21 个 service 文件无测试 |
| 5. 边界条件与异常路径覆盖不足 | 🟡 重要 | 已有测试以 happy path 为主 |

---

## 二、与业界标准的差距

### 2.1 覆盖率阈值对比

| 项目 | 覆盖率要求 | 本项目 |
|------|-----------|--------|
| Google 内部项目 | ≥ 80%（关键路径 90%+） | 49% |
| Meta (Python) | ≥ 80% | 49% |
| 典型开源项目 (FastAPI/Django) | ≥ 90% | 49% |
| 业界最低及格线 | ≥ 70% | 49% |

### 2.2 测试分层对比

| 测试类型 | 业业标准 | 本项目 |
|----------|---------|--------|
| 单元测试 | ✅ 覆盖所有纯函数 | ⚠️ 部分覆盖（card_text_utils 仅 3/12 函数） |
| 集成测试 | ✅ 真实 DB + 事务边界验证 | ❌ 完全缺失 |
| Repository 测试 | ✅ SQL 正确性 + 参数对齐 | ❌ 完全缺失 |
| 契约测试 | ✅ API 输入/输出 schema | ⚠️ 部分覆盖 |
| 端到端测试 | ✅ 关键用户流程 | ❌ 完全缺失 |
| 性能/压力测试 | ✅ 关键路径延迟/吞吐 | ❌ 完全缺失 |
| 安全测试 | ✅ OWASP Top 10 | ⚠️ 仅基础覆盖 |
| 回归测试 | ✅ Bug fix → 新增用例 | ❌ 无制度化流程 |
| 变异测试 | ✅ 验证测试质量 | ❌ 完全缺失 |

### 2.3 CI/CD 测试门禁对比

| 门禁 | 业界标准 | 本项目 |
|------|---------|--------|
| 覆盖率阈值 | 80%+ | 49% |
| 覆盖率趋势 | 逐步提升（CI 阻断下降） | 无趋势追踪 |
| 测试分类执行 | unit → integration → e2e 分阶段 | 单一 pytest 全跑 |
| 测试超时 | 按类型分级（unit 5s/integration 30s） | 全局 60s |
| 并行执行 | 分片并行加速 | 单线程串行 |
| 测试失败通知 | PR 阻断 + 通知 | PR 阻断（已配置） |

---

## 三、当前测试文件逐一诊断

### 3.1 单元测试 (`tests/unit/`)

| 文件 | 测试数 | Mock 类型 | 异常路径 | 边界条件 | 缺陷 |
|------|--------|----------|---------|---------|------|
| test_auth.py | 30 | make_fake_conn + MagicMock | ✅ 部分 | ✅ 部分 | Cookie 认证路径未测；SHA-256 APP_SECRET=None 未测 |
| test_cache_service.py | 20 | 无 | ❌ 无 | ⚠️ 部分 | 并发测试仅验证"不崩溃"；max_size=0/1 未测；None vs 缺失键无 sentinel 区分 |
| test_card_text_utils.py | 9 | 无 | ❌ 无 | ⚠️ 部分 | **仅覆盖 3/12 函数**；缺失 remove_html_tags/shorten_text 等 9 个函数 |
| test_conn_wrapper.py | 5 | 自定义 MockPsycopg2Conn | ✅ 部分 | ⚠️ 部分 | 风格不统一（未用 FakeSequenceConn）；rollback 异常期间未测；fetchall commit 后未测 |
| test_json_utils.py | 19 | 无 | ✅ 部分 | ✅ 良好 | 较完善 |
| test_model_adapter.py | 16 | patch + MagicMock | ✅ 良好 | ⚠️ 部分 | 未测 connect timeout 场景 |
| test_prompt_assembler.py | 24 | 无 | ❌ 无 | ⚠️ 部分 | 纯模板组装测试，缺少异常输入（None character 等） |
| test_rate_limit.py | 15 | FakeCursorConn | ✅ 部分 | ✅ 部分 | 并发场景未测 |
| test_usage_guard.py | 17 | FakeSequenceConn | ✅ 部分 | ⚠️ 部分 | VIP 过期瞬间行为未测 |

### 3.2 服务层测试 (`tests/services/`)

| 文件 | 测试数 | 缺陷 |
|------|--------|------|
| test_character_state.py | 8 | 仅覆盖 character_state.py 部分；story_event_service.py 完全未测 |
| test_memory_service.py | 20 | 覆盖尚可，但未测并发读写同一 character 的记忆 |

### 3.3 路由层测试 (`tests/routers/`)

| 文件 | 测试数 | 缺陷 |
|------|--------|------|
| test_admin_crud_smoke.py | 20 | 仅冒烟测试，未测非法输入/权限边界 |
| test_admin_router.py | 22 | 覆盖较好但 admin/ 12 个文件仅 2 个测试文件覆盖 |
| test_auth_router.py | 12 | 注册/登录/登出基本覆盖，缺少密码强度/频率限制测试 |
| test_billing.py | 18 | 支付回调验签未测；并发支付同一订单未测 |
| test_chat_clear.py | 5 | 太薄，仅基本成功路径 |
| test_chat_router.py | 10 | 流式响应未测；消息长度限制未测 |
| test_cursor_lifecycle.py | 9 | 连接生命周期测试较好 |

### 3.4 契约测试 (`tests/contracts/`)

| 文件 | 测试数 | 缺陷 |
|------|--------|------|
| test_api_errors.py | 15 | 4xx 覆盖较好，5xx 场景几乎无覆盖 |
| test_app_lifecycle.py | 5 | 启动/关闭基本覆盖 |
| test_chat_meta.py | 3 | 太薄 |
| test_performance.py | 5 | 仅检查响应时间 ≤ 2s，无并发测试 |
| test_schemas.py | 10 | 输入校验覆盖较好 |
| test_security.py | 2 | **极度不足** — 仅测路径遍历和鉴权，SQL 注入/XSS/CSRF/IDOR 未覆盖 |

---

## 四、核心漏洞详解

### 漏洞 1：零集成测试 — 最致命的缺陷

**现状**：所有测试使用 `FakeSequenceConn`/`FakeCursorConn`/`FakeDummyConn` 模拟数据库连接，**从不执行真实 SQL**。

**后果**：以下类型的 Bug 测试完全无法捕获：

| Bug 类型 | 示例 | 当前能否检测 |
|----------|------|-------------|
| SQL 语法错误 | `SELECT * FORM users` (FORM→FROM) | ❌ |
| 参数占位符错位 | `INSERT INTO t (a,b) VALUES (%s)` 漏写 %s | ❌ |
| 列名拼写错误 | `SELECT usr_id FROM users` (usr→user) | ❌ |
| 类型不匹配 | int 列传 True/False 而非 1/0 | ❌ |
| jsonb vs text 序列化 | 忘记 json.loads() 或多此一举 json.dumps() | ❌ |
| 事务边界错误 | commit 后 fetchone() → InterfaceError | ❌ FakeConn 不模拟此行为 |
| RETURNING 子句 | INSERT ... RETURNING id 返回 None | ❌ FakeConn 总返回预设值 |
| 约束违反 | UNIQUE/FOREIGN KEY/NOT NULL 冲突 | ❌ |
| 死锁/超时 | 两个事务互相等待 | ❌ |

**这正是 dev_rules 第 2 节中"游标生命周期"规则存在的原因** — 因为 FakeConn 不会在 commit 后关闭游标，这类 Bug 在测试中永远不会被发现。

### 漏洞 2：repositories 层零测试

项目已将所有 SQL 集中到 `repositories/` 目录（5 个文件，30 个函数），但**没有任何测试文件**：

| Repository 文件 | 函数数 | 测试文件 | 状态 |
|----------------|--------|---------|------|
| auth_repository.py | 5 | ❌ 无 | SQL 无验证 |
| billing_repository.py | 5 | ❌ 无 | SQL 无验证 |
| character_repository.py | 6 | ❌ 无 | SQL 无验证 |
| chat_repository.py | 7 | ❌ 无 | SQL 无验证 |
| user_repository.py | 7 | ❌ 无 | SQL 无验证 |

**这意味着**：任何 SQL 修改（增删字段、改 WHERE 条件、调整 JOIN）都不会被测试拦截。这正是"先 fetchone 再 commit"规则频繁违反的根源 — FakeConn 模拟下根本不存在"游标已关闭"的问题。

### 漏洞 3：服务层大面积测试空白

21 个 service 文件中，仅 6 个有对应测试：

| Service 文件 | 有测试 | 关键性 |
|-------------|--------|--------|
| auth 相关 | ✅ test_auth.py | 🔴 高 |
| cache_service.py | ✅ test_cache_service.py | 🟡 中 |
| character_state.py | ✅ test_character_state.py | 🟠 高 |
| memory_service.py | ✅ test_memory_service.py | 🟠 高 |
| prompt_assembler.py | ✅ test_prompt_assembler.py | 🟠 高 |
| rate_limit.py | ✅ test_rate_limit.py | 🟠 高 |
| usage_guard.py | ✅ test_usage_guard.py | 🟠 高 |
| **billing_order_service.py** | ❌ | 🔴 极高（支付） |
| **chat_send.py** | ❌ | 🔴 极高（核心路径） |
| **chat_stream_service.py** | ❌ | 🔴 极高（核心路径） |
| **stream_filter.py** | ❌ | 🟠 高（内容安全） |
| **token_budget.py** | ❌ | 🟠 高（计费） |
| **plan_service.py** | ❌ | 🟠 高（权益） |
| **chat_query.py** | ❌ | 🟡 中 |
| **chat_retry.py** | ❌ | 🟡 中 |
| **character_session_service.py** | ❌ | 🟡 中 |
| **story_event_service.py** | ❌ | 🟡 中 |
| **character_memory_repository.py** | ❌ | 🟡 中 |
| **runtime_bundle.py** | ❌ | 🟡 中 |
| **db_monitor.py** | ❌ | 🟢 低 |
| **email.py** | ❌ | 🟢 低 |
| **health_service.py** | ❌ | 🟢 低 |
| **jobs_facade.py** | ❌ | 🟢 低 |

### 漏洞 4：边界条件与异常路径覆盖不足

**已识别的具体缺失**（按严重度排序）：

| # | 缺失场景 | 模块 | 严重度 |
|---|---------|------|--------|
| 1 | 支付回调验签失败 | billing | 🔴 |
| 2 | 并发支付同一订单 | billing | 🔴 |
| 3 | chat_stream 中途断连恢复 | chat_stream | 🔴 |
| 4 | token_budget 边界（刚好用尽/超额 1） | token_budget | 🟠 |
| 5 | VIP 过期瞬间请求（23:59:59→00:00:00） | plan_service | 🟠 |
| 6 | stream_filter 绕过测试 | stream_filter | 🟠 |
| 7 | 大量消息历史（1000+ 条）查询性能 | chat_query | 🟠 |
| 8 | 角色配置中 None/空值字段 | prompt_assembler | 🟡 |
| 9 | 缓存与 DB 不一致窗口 | cache_service | 🟡 |
| 10 | FakeSequenceConn SQL 序列与实际不一致 | 全局 mock 设计 | 🟡 |

### 漏洞 5：测试基础设施不足

| 问题 | 现状 | 影响 |
|------|------|------|
| 无覆盖率配置文件 | 仅 CI 命令行 `--cov-fail-under=49` | 无法排除无关文件、无法配置分支覆盖 |
| 无测试标记 | 无 pytest marker | 无法按类型运行（unit/integration/e2e） |
| 无变异测试 | 无 | 测试可能只覆盖代码行但不验证行为 |
| 无测试数据管理 | 各文件自行构造 | 重复且不一致 |
| 无回归测试流程 | Bug 修复后无强制新增用例 | 同一 Bug 可重复出现 |
| FakeConn 不模拟 psycopg2 真实行为 | commit 后不关游标、不抛异常 | 给出虚假安全感 |

---

## 五、测试策略缺失的具体清单

### 5.1 缺失的测试类型

```
tests/
├── unit/              ✅ 已有（但覆盖不全）
├── services/          ⚠️ 仅 2 个文件
├── routers/           ⚠️ 仅 7 个文件
├── contracts/         ⚠️ 部分覆盖
│
├── integration/       ❌ 完全缺失 — 需新建
│   ├── test_repositories.py       ← SQL 正确性验证
│   ├── test_transaction_boundary.py ← 事务边界验证
│   ├── test_db_constraints.py     ← 唯一/外键/非空约束
│   └── test_concurrent_access.py  ← 并发竞态条件
│
├── e2e/               ❌ 完全缺失 — 需新建
│   ├── test_user_journey.py       ← 注册→登录→聊天→支付
│   └── test_admin_workflow.py     ← 管理后台完整流程
│
├── regression/        ❌ 完全缺失 — 需新建
│   └── (按 Bug ID 命名)
│
└── performance/       ❌ 完全缺失 — 需新建
    └── test_chat_throughput.py
```

### 5.2 缺失的测试配置

| 配置项 | 需新增 | 文件 |
|--------|--------|------|
| 覆盖率排除规则 | `.coveragerc` 或 `pyproject.toml [tool.coverage]` | 排除 migrations/、tests/、__pycache__ |
| 分支覆盖 | `branch = True` | 当前仅行覆盖 |
| 测试标记 | `pytest.ini` 或 `pyproject.toml [tool.pytest]` | unit/integration/e2e/slow |
| 测试超时分级 | `pytest-timeout` 按 marker 配置 | unit: 5s, integration: 30s |
| 集成测试数据库 | `tests/integration/conftest.py` | 真实 PG 实例 + 事务回滚 |

### 5.3 FakeConn 体系的关键设计缺陷

`FakeSequenceConn` 和 `FakeCursorConn` 是当前测试的核心 Mock，但它们的行为与真实 psycopg2 存在 **致命差异**：

| 行为 | psycopg2 真实行为 | FakeConn 行为 | 后果 |
|------|------------------|--------------|------|
| commit() 后游标 | 游标关闭，fetchone() 抛 InterfaceError | 游标不关闭，继续返回预设值 | **无法检测 commit 后 fetchone 的 Bug** |
| 参数类型 | int 列不接受 Python bool | 接受任何类型 | **无法检测 True/False 传 int 列的 Bug** |
| SQL 语法 | 错误 SQL 抛 ProgrammingError | 不验证 SQL | **无法检测 SQL 拼写错误** |
| 约束 | UNIQUE/NOT NULL 抛 IntegrityError | 无约束 | **无法检测数据完整性 Bug** |
| 事务隔离 | 依赖 isolation level | 无隔离 | **无法检测脏读/不可重复读** |

---

## 六、改进方案

### 6.1 优先级排序

| 优先级 | 改进项 | 预估工作量 | 预期效果 |
|--------|--------|-----------|---------|
| P0 | 新增集成测试：repositories 层 SQL 验证 | 2-3 天 | 捕获当前遗漏最多的 SQL 类 Bug |
| P0 | 修复 FakeConn：commit 后关闭游标 | 0.5 天 | 立即暴露 commit 后 fetchone 的 Bug |
| P0 | 提升覆盖率阈值至 70% | 持续 | 逐步淘汰无测试代码 |
| P1 | 补全 service 层测试（billing/chat_send/chat_stream） | 3-5 天 | 覆盖核心业务路径 |
| P1 | 新增 `.coveragerc` + 分支覆盖 | 0.5 天 | 更真实的覆盖率数据 |
| P1 | 新增 pytest markers | 0.5 天 | 分类执行测试 |
| P2 | 补全 card_text_utils 测试 | 0.5 天 | 覆盖缺失的 9 个函数 |
| P2 | 新增安全测试 | 1-2 天 | SQL 注入/XSS/IDOR |
| P2 | 新增回归测试流程 | 0.5 天 | 防止 Bug 复现 |
| P3 | 新增 E2E 测试 | 3-5 天 | 关键用户流程保护 |
| P3 | 引入变异测试 | 2-3 天 | 验证测试质量 |

### 6.2 集成测试实施方案

**核心思路**：在真实 PostgreSQL 实例上运行 SQL，每个测试在事务中执行，测试完回滚，保持数据库干净。

```
tests/integration/
├── conftest.py                    ← 真实 PG 连接 + 事务回滚 fixture
├── test_auth_repository.py        ← 5 个函数的 SQL 验证
├── test_billing_repository.py     ← 5 个函数的 SQL 验证
├── test_character_repository.py   ← 6 个函数的 SQL 验证
├── test_chat_repository.py        ← 7 个函数的 SQL 验证
├── test_user_repository.py        ← 7 个函数的 SQL 验证
├── test_transaction_boundary.py   ← commit/fetchone 顺序、rollback 安全性
├── test_db_constraints.py         ← UNIQUE/NOT NULL/FK 约束触发
└── test_concurrent_access.py      ← 同一用户并发操作的竞态条件
```

**conftest.py 关键设计**：

```python
@pytest.fixture(scope="session")
def real_db():
    """会话级真实 PG 连接，创建测试 schema。"""
    # 使用 DATABASE_URL 环境变量
    # 创建测试专用 schema (test_schema)
    # yield
    # 清理 test_schema

@pytest.fixture
def db_conn(real_db):
    """每个测试在事务中运行，测试完回滚。"""
    conn = real_db.connect()
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()
```

### 6.3 FakeConn 修复方案

在 `FakeSequenceConn.commit()` 和 `FakeCursorConn.commit()` 中关闭游标，使 fetchone() 抛出异常：

```python
class FakeSequenceConn:
    def commit(self):
        self.committed = True
        self._committed = True  # 标记已 commit

    def execute(self, sql, params=None):
        if getattr(self, '_committed', False):
            raise RuntimeError("Cannot execute after commit — cursor is closed (psycopg2 behavior)")
        ...
```

**影响**：此修改会导致现有测试中"先 commit 再 fetchone"的写法失败 — 这正是要检测的 Bug。需要逐一修复受影响的测试，确保它们遵循正确的"先 fetchone 再 commit"顺序。

### 6.4 测试分层规范

```
tests/
├── conftest.py                      # 全局 fixtures + FakeConn 体系
├── unit/                            # 纯函数，零 mock，快速
│   ├── test_auth.py
│   ├── test_cache_service.py
│   ├── test_card_text_utils.py
│   ├── test_conn_wrapper.py
│   ├── test_json_utils.py
│   ├── test_model_adapter.py
│   ├── test_prompt_assembler.py
│   ├── test_rate_limit.py
│   └── test_usage_guard.py
├── services/                        # 服务逻辑，轻 mock
│   ├── test_character_state.py
│   ├── test_memory_service.py
│   ├── test_billing_order.py        ← 新增
│   ├── test_chat_send.py            ← 新增
│   ├── test_chat_stream.py          ← 新增
│   ├── test_stream_filter.py        ← 新增
│   ├── test_token_budget.py         ← 新增
│   └── test_plan_service.py         ← 新增
├── routers/                         # API 层，TestClient + mock DB
│   ├── test_admin_crud_smoke.py
│   ├── test_admin_router.py
│   ├── test_auth_router.py
│   ├── test_billing.py
│   ├── test_chat_clear.py
│   ├── test_chat_router.py
│   └── test_cursor_lifecycle.py
├── contracts/                       # API 契约 / 安全
│   ├── test_api_errors.py
│   ├── test_app_lifecycle.py
│   ├── test_chat_meta.py
│   ├── test_performance.py
│   ├── test_schemas.py
│   └── test_security.py
├── integration/                     ← 新增：真实 DB
│   ├── conftest.py
│   ├── test_auth_repository.py
│   ├── test_billing_repository.py
│   ├── test_character_repository.py
│   ├── test_chat_repository.py
│   ├── test_user_repository.py
│   ├── test_transaction_boundary.py
│   └── test_db_constraints.py
└── regression/                      ← 新增：Bug 回归
    └── (按需新增)
```

### 6.5 覆盖率提升路线图

| 阶段 | 阈值 | 新增测试 | 预估时间 |
|------|------|---------|---------|
| 当前 | 49% | — | — |
| 第一阶段 | 60% | repositories 集成测试 + 补全 card_text_utils | 1 周 |
| 第二阶段 | 70% | 核心服务层（billing/chat_send/chat_stream） | 2 周 |
| 第三阶段 | 80% | 全服务层 + 安全测试 | 3 周 |
| 目标 | 85%+ | E2E + 回归 + 变异 | 持续 |

---

## 七、结论

当前测试体系的根本问题是 **"Mock 过度、真实验证不足"**。371 个测试用例看起来数量可观，但它们验证的是"Mock 返回了我们预设的值"，而非"代码在真实环境下行为正确"。

**最需要立即行动的 3 件事**：

1. **新增 repositories 层集成测试**（真实 SQL 执行）— 这是当前遗漏 Bug 最多的区域
2. **修复 FakeConn 使 commit 后游标关闭** — 立即暴露"先 commit 再 fetchone"类 Bug
3. **提升覆盖率阈值至 60%**（先），逐步提升至 80% — 强制补全空白区域

这三项改进实施后，测试的 Bug 检出率预计可提升 3-5 倍，从根本上解决"严重错误被遗漏"的问题。
