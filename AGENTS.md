# AGENTS.md

本项目为 Claude Code 提供完整的 [CLAUDE.md](CLAUDE.md)。如果你使用的是 Codex（Codex.ai/code），请以 CLAUDE.md 为权威参考。

## 快速命令

```bash
# 开发启动
cd backend && python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 测试
cd backend && python3 -m pytest ../tests/ -q --ignore=../tests/integration

# 部署
bash deploy.sh
bash rollback.sh
```

## 核心约定（摘要）

- **全程中文**：代码注释、文档、Agent 回复一律中文
- **两种玩法隔离**：`card_type=intimate`（对话陪伴）和 `scenario`（剧情沙盒）
- **分层架构**：`routers/ → services/ → repositories/ → core/`
- **游标生命周期**：`fetchone()` 必须在 `conn.commit()` 之前
- **数据库类型**：int 列用 `1`/`0`，jsonb 列传 dict
- **错误处理**：禁止 `assert` 做运行时校验
- **高风险模块**：`routers/admin/`、`routers/billing.py`、`services/chat_stream/`、`services/chat_send.py`、`core/auth/`、`core/database.py`、`repositories/`、`alembic/versions/`

## 测试账号

管理后台：`773682014@qq.com` / `jie159357`

## 配套文档

- [CLAUDE.md](CLAUDE.md) — 完整项目指导
- [CONTEXT.md](CONTEXT.md) — 领域词汇表
- [docs/](docs/) — 功能文档（部署、API、好感度、角色导入等）
- [.out-of-scope/](.out-of-scope/) — Agent 行为边界
