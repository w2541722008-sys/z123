# AIFriend 测试功能诊断报告

> 更新时间：2026-05-04 | 当前：878 passed / 覆盖率 51%

---

## 一、执行摘要

| 指标 | 当前 | 目标 |
|------|------|------|
| 测试总数 | 878 | — |
| 覆盖率 | 51% | 70%+ |
| 集成测试 | 2 文件（character/user repository） | 5 repository 全覆盖 |
| 压测 | 有 locustfile.py | 线上基准数据 |

### 已改善的问题

| # | 问题 | 状态 |
|---|------|------|
| 1 | `FakeSequenceConn` commit 后不关游标 | ✅ 已修复：commit 后 fetchone 抛 RuntimeError |
| 2 | 用户缓存失效测试缺失 | ✅ 已补 3 个测试 |
| 3 | 集成测试完全缺失 | ⚠️ 部分补全（2/5 repository） |
| 4 | 覆盖率阈值 49% | ✅ 已提升 |
| 5 | 无压测脚本 | ✅ 已新增 locustfile.py |
| 6 | 无回归测试流程 | ✅ 已新增 `regression/` 目录 + test_cursor_commit_regression |

### 仍需改进

| 优先级 | 问题 | 预估工作量 |
|--------|------|-----------|
| P1 | 补全 repository 集成测试（3/5 缺失） | 1-2 天 |
| P1 | 核心服务层测试（chat_send/chat_stream/billing_order） | 3-5 天 |
| P2 | 安全测试扩展（SQL 注入/XSS/CSRF） | 1-2 天 |
| P2 | 管理后台路由测试覆盖（目前 2/7 子模块） | 2 天 |
| P3 | E2E 测试 | 3-5 天 |

---

## 二、测试文件现状

### 单元测试 (`tests/unit/`, 27 文件)

核心模块已覆盖：auth、cache_service、card_text_utils、conn_wrapper、json_utils、model_adapter、prompt_assembler、rate_limit、usage_guard、auth_repository、billing_repository、character_repository、chat_repository、user_repository、plan_constants、stream_filter、token_budget、chat_retry、chat_send、chat_stream_service 等。

### 服务层测试 (`tests/services/`, 6 文件)

- test_billing_order_service.py
- test_character_session_service.py
- test_character_state.py
- test_chat_retry_service.py
- test_chat_send.py
- test_memory_service.py
- test_plan_service.py

### 路由层测试 (`tests/routers/`, 7 文件)

- test_admin_crud_smoke.py
- test_admin_router.py
- test_auth_router.py
- test_billing.py（含缓存失效验证）
- test_chat_clear.py
- test_chat_router.py
- test_cursor_lifecycle.py

### 契约测试 (`tests/contracts/`, 6 文件)

- test_api_errors.py
- test_app_lifecycle.py
- test_chat_meta.py
- test_performance.py
- test_schemas.py
- test_security.py

### 集成测试 (`tests/integration/`, 需真实 DB)

- test_character_repository.py
- test_user_repository.py

运行：`pytest -m integration` 或 `pytest tests/integration/`

### 回归测试 (`tests/regression/`)

- test_cursor_commit_regression.py

### 压测 (`tests/locustfile.py`)

3 个用户类：登录用户、游客、健康检查

---

## 三、FakeConn 体系现状

`FakeSequenceConn` 已模拟 commit 后游标关闭行为：

```python
def commit(self):
    self.committed = True
    self._committed = True  # 标记，后续 fetchone 将抛异常
```

| 行为 | psycopg2 真实 | FakeConn 当前 |
|------|--------------|--------------|
| commit() 后 fetchone | InterfaceError | RuntimeError ✅ |
| SQL 语法验证 | ProgrammingError | 不验证（设计取舍） |
| 参数类型 | int 列拒 bool | 不验证（设计取舍） |

---

## 四、覆盖率提升路线

| 阶段 | 阈值 | 新增内容 | 预估时间 |
|------|------|---------|---------|
| 当前 | 51% | — | — |
| 第一阶段 | 60% | 补全 repository 集成测试 | 1 周 |
| 第二阶段 | 70% | 核心服务层 + admin 路由 | 2 周 |
| 目标 | 80%+ | 全服务层 + 安全 + E2E | 持续 |
