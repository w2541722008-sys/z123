# ADR-0004：FakeSequenceConn 测试序列模拟模式

**日期**：2025-05-01（推定，基于代码历史）
**状态**：已接受

## 背景

aifriend 的 57 个测试文件中，大部分单元测试需要隔离数据库。传统的 mock 方式（unittest.mock、pytest-mock）有两个问题：
1. 模拟 `fetchone()` 和 `fetchall()` 的返回值需要大量样板代码
2. Mock 对象的行为与真实连接的差异导致"测试通过但生产炸了"的风险

需要一个既能隔离数据库、又能准确模拟 SQL 查询行为的测试模式。

## 决策

使用 **FakeSequenceConn** — 一个预定义返回序列的伪连接类，配合 **FakeQueryResult** 模拟查询结果。

核心设计：
- 构造时传入一个查询结果序列（列表），按顺序消费
- `fetchone()` 返回序列的下一个 dict
- `fetchall()` 返回序列的下一个 list-of-dicts
- 如果 SQL 查询调用次数与预定义序列不匹配 → 测试失败（序列耗尽或残留）

```python
conn = FakeSequenceConn([
    {"id": 1, "name": "test"},           # 第 1 次 fetchone 返回
    [{"id": 1}, {"id": 2}],              # 第 1 次 fetchall 返回
    {"count": 5},                         # 第 2 次 fetchone 返回
])
```

## 备选方案

- **方案 A：真实测试数据库（test DB）** — 每个测试连接真实的 PostgreSQL 测试库
  - 未选原因：速度太慢（每个测试需要 setup/teardown 数据），不适合 57 个测试的快速反馈。但集成测试（tests/integration/）使用真实数据库

- **方案 B：unittest.mock + MagicMock** — Python 标准 mock 工具
  - 未选原因：配置 mock 的 side_effect 序列很啰嗦，且 Mock 的行为（自动创建属性、不检查调用次数）隐藏了 SQL 调用计数不匹配的 bug

- **方案 C：pytest-pgsql / testcontainers** — Docker 化的真实数据库
  - 未选原因：依赖 Docker 增加了 CI 环境复杂度。对于单元测试来说过于重量级

## 后果

### 正面
- 测试速度快（纯内存操作），57 个单元测试在秒级完成
- 序列耗尽/残留自动检测 SQL 调用次数不匹配，帮助发现隐藏的查询遗漏或冗余查询
- FakeSequenceConn 接口简洁，新测试的编写成本低

### 负面
- 测试质量依赖 FakeQueryResult 的准确性 — 如果结果与真实 SQL 行为不一致，测试会给出虚假的通过
- 复杂查询（JOIN、子查询）的模拟结果构造起来比较繁琐
- 修改 SQL 后必须同步更新测试的 FakeQueryResult（已在 CLAUDE.md 中显式规则化）

## 相关
- CLAUDE.md "测试 Mock"规则："修改路由/服务 SQL 后，必须同步更新对应测试的 FakeQueryResult"
- `tests/factories.py` — FakeSequenceConn 定义
- `tests/unit/` — 主要使用场景
