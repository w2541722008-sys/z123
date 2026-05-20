---
scope: agent-behavior
severity: critical
---

# 禁止修改已应用的 Alembic Migration

## 规则

Agent **绝对禁止**修改 `backend/alembic/versions/` 中已经应用到任何环境（开发/测试/生产）的 migration 文件。

## 原因

- Alembic 通过 migration 文件的 hash 追踪数据库状态
- 修改已应用的 migration 会导致 hash 不匹配，破坏整个 migration 链
- 修复的唯一方式是手动操作数据库的 `alembic_version` 表 — 高风险且容易出错

## 正确做法

- 如果上一个 migration 有问题：**创建新的 migration 来修正**，不要改旧的
- 如果 migration 还未应用（仅在本地分支、未合并、未执行 `alembic upgrade head`）：可以修改
- 不确定是否已应用时：**假设已应用**，创建新的 migration

## 检测方法

如果必须确认一个 migration 是否已应用：
```bash
cd backend && python3 -m alembic current   # 查看当前版本
cd backend && python3 -m alembic history   # 查看完整历史
```
