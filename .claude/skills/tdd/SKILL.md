---
name: tdd
description: 测试驱动开发 — red-green-refactor 循环，每次一个垂直切片。功能或 bug 修复的每个行为先写失败测试，再写最小实现，最后重构。适用场景：新功能开发、bug 修复、重构前补充测试安全网。不适用：纯探索性原型、一次性脚本、配置文件修改。
---

# 测试驱动开发（TDD）

## 核心原则

**先写测试，再写代码，一次只测一个行为。** 这不是仪式，而是为了让你在写实现之前先想清楚"什么算正确"。

---

## 四阶段流程

### 阶段 1：规划

在开始写任何代码之前，与用户确认：

1. **接口长什么样？** — API 的请求/响应格式、函数签名、UI 行为
2. **测哪些行为？** — 列出要测的行为清单，按优先级排序。你不可能测试一切，聚焦关键路径和复杂逻辑
3. **哪些是高风险模块？** — 对照 aifriend 的高风险模块清单（admin/、billing、chat_stream、chat_send、core/auth、core/database、repositories/、alembic/versions/）
4. **获得用户批准后进入阶段 2**

### 阶段 2：Tracer Bullet（穿甲弹）

写**一个**测试，验证系统的一个基本行为。目标不是测所有东西，而是证明端到端路径通了。

```
RED：写第一个行为的测试 → 运行 → 失败（期望的失败）
GREEN：写最小代码让测试通过 → 运行 → 通过
```

这一步验证了测试基础设施可用（FakeSequenceConn 配置正确、pytest 能运行、导入路径正确）。

#### aifriend 项目的测试基础设施

```bash
# 运行单个测试
cd backend && python3 -m pytest ../tests/unit/test_xxx.py::test_xxx -q -v

# 运行全部单元测试（排除集成测试）
cd backend && python3 -m pytest ../tests/ -q --ignore=../tests/integration
```

**测试目录映射**：
- 路由层测试 → `tests/routers/`
- 服务层测试 → `tests/services/` 或 `tests/unit/`
- 数据层测试 → `tests/unit/`（使用 FakeSequenceConn）
- 集成测试 → `tests/integration/`（需要真实数据库）

**FakeSequenceConn 模式**（数据库隔离的核心机制）：
```python
# 在 conftest.py 或测试文件中
from tests.factories import FakeSequenceConn

def test_my_service():
    conn = FakeSequenceConn([
        # fetchone 返回序列
        {"id": 1, "name": "test"},
        # fetchall 返回序列
        [{"id": 1}, {"id": 2}],
    ])
    result = my_service.do_something(conn)
    assert result == expected
```

### 阶段 3：增量循环

对清单中的每个剩余行为，重复 red-green 循环：

```
RED：写该行为的测试 → 运行 → 失败
GREEN：写最小代码让测试通过 → 运行 → 通过
```

**关键规则**：
- **只写足够让当前测试通过的代码**。不要预测未来的测试需求
- **一次只加一个测试**。加多个测试同时失败 = 你不知道哪个行为的实现是对的
- **测试聚焦可观察行为**，不绑定实现细节
- **不要跳过 RED 阶段**。如果测试第一次就绿了，说明你在测已经实现的东西或者测试写错了

### 阶段 4：重构

所有测试通过后，问自己：

1. 有没有可以提取的重复代码？
2. 新代码有没有揭示现有模块的不足？（对照 `improve-codebase-architecture` skill 的删除测试）
3. 设计模式与现有模块一致吗？（CLAUDE.md 规则：**新代码保持设计模式一致**）
4. 单文件有没有超过 1000 行？（CLAUDE.md 规则：**单文件上限 1000 行**）
5. 有没有违反分层依赖？（CLAUDE.md 规则：**core/ 不能导入 services/**）

**每次重构后立即运行全部测试。** 永远不要在 RED 状态下重构。

---

## 高风险模块的强制 TDD

以下 8 个区域修改时，**必须**走 TDD 流程，不允许先写实现再补测试：

1. `routers/admin/`
2. `routers/billing.py`
3. `services/chat_stream_service.py`
4. `services/chat_send.py`
5. `core/auth.py`
6. `core/database.py`
7. `repositories/`
8. `alembic/versions/`（migration 本身不可测，但触发的代码变更必须测）

---

## 常见反模式

### ❌ 水平切片
先写所有测试，再写所有实现。这产出的测试绑定数据结构和函数签名，而不是行为。

### ❌ 测实现而非行为
```python
# ❌ 坏：测内部实现
def test_calculate_affection_calls_helper():
    mock_helper = Mock()
    calculate_affection(events, helper=mock_helper)
    assert mock_helper.called  # 绑定了实现细节
```

### ❌ 一次测太多
一个测试函数验证 5 个行为 → 失败时你不知道哪个行为坏了。

### ❌ 跳过 tracer bullet
一上来就写复杂测试 → 如果基础设施有问题，所有测试一起挂，浪费时间排查。

---

## 与项目规则的关系

- 遵循 **新增功能同步测试**规则：功能代码和测试代码在同一垂直切片中完成
- 遵循 **测试 Mock**规则：修改 SQL 后同步更新 FakeQueryResult
- 遵循 **错误处理**规则：测试中验证 4xx 而非 500
- 遵循 **代码质量三要素**：每个测试覆盖正常路径 + 边界条件
