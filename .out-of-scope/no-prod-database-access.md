---
scope: agent-behavior
severity: critical
---

# 禁止直接操作生产数据库

## 规则

Agent **绝对禁止**对生产数据库执行任何写操作（INSERT、UPDATE、DELETE、DROP、TRUNCATE、ALTER）。

## 原因

- 生产数据库包含真实用户数据（对话记录、付费订单、角色卡配置）
- 误操作可能导致数据丢失、付费纠纷、用户投诉
- 没有"撤销"按钮 — 即使有备份，恢复也需要停机

## 允许的操作

- 对**本地开发数据库**的读写（通过 `backend/main.py` 启动的 dev server）
- 对**测试数据库**的操作（通过 pytest 运行）
- 通过 alembic 生成的 migration 脚本（需人工审查后手动执行）

## 边界说明

- "生产数据库"指通过环境变量 `DATABASE_URL` 配置的任何非本地实例
- Agent 不知道也**不应该知道**生产数据库的连接信息
- 如果用户要求操作生产数据，Agent 应拒绝并解释风险
