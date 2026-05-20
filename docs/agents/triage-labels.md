# Triage 标签映射

本文档定义 aifriend 项目的 GitHub Issue 标签，供 Agent 在执行 triage 分类时使用。

## 标签列表

| 标准角色 | GitHub 标签 | 用途 |
|----------|------------|------|
| `needs-triage` | `needs-triage` | 维护者需要评估此 issue |
| `needs-info` | `needs-info` | 等待报告者补充更多信息 |
| `ready-for-agent` | `ready-for-agent` | 需求明确，Agent 可独立实现 |
| `ready-for-human` | `ready-for-human` | 需要人工实现或审查 |
| `wontfix` | `wontfix` | 不会处理 |
| `needs-db-migration` | `needs-db-migration` | 需要数据库变更，等待 migration 审查 |

## 使用方式

当 triage skill 说"发布到 issue tracker"时，用 `gh issue create`。
当 triage skill 说"获取相关 issue"时，用 `gh issue view <number> --comments`。
当 triage skill 说"标记为 <角色>"时，用 `gh issue edit <number> --add-label "<对应标签>"`。

## 标签维护

- 新增标签时同步更新本文档
- 标签名使用 kebab-case 格式
- 每个 issue 只应有一个状态标签（不含 bug/enhancement 分类标签）
