# AGENTS.md

本项目使用 Claude Code 作为主要开发工具，所有项目约定、架构说明、命令参考请参阅 [CLAUDE.md](CLAUDE.md)。

非 Claude Code 的 AI 编程代理（Codex、Cursor、Copilot 等）同样以 CLAUDE.md 为权威参考，配合 [CONTEXT.md](CONTEXT.md) 获取领域词汇表。

## Agent 行为边界

以下规则对所有 AI 编程代理强制执行（详见 [.out-of-scope/](.out-of-scope/)）：

- **绝对禁止**操作生产数据库（INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER）
- **禁止**修改 `card_type` 枚举值（仅允许 `intimate` / `scenario`）
- **禁止** `core/` 层导入 `services/`（通过 `main.py` lifespan 回调注入解耦）

## 技能系统

Agent 技能定义在 `.agents/skills/`（与 `.claude/skills/` 同步），在对应场景自动触发。技能列表和说明详见 [CLAUDE.md#agent-skills](CLAUDE.md#agent-skills)。

## 测试账号

管理后台：`773682014@qq.com` / `jie159357`
