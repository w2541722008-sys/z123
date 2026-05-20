---
name: triage
description: Issue 分类状态机 — 将 GitHub Issue 按分类角色（bug/enhancement）和状态角色（needs-triage/needs-info/ready-for-agent/ready-for-human/wontfix/needs-db-migration）进行归类。扩展了 aifriend 专属检查步骤：高风险模块影响评估、后台管理配置需求、数据库变更需求。适用场景：新 issue 入库时、issue 状态变更时、每周 issue 清理。
---

# Issue 分类（Triage）

## 状态机

每个 issue 必须同时拥有**一个分类角色**和**一个状态角色**。

### 分类角色（这是什么类型的 issue）

| 角色 | 含义 |
|------|------|
| `bug` | 某个功能出了问题 |
| `enhancement` | 新功能或改进 |

### 状态角色（这个 issue 现在在哪里）

| 角色 | 含义 | 谁该行动 |
|------|------|----------|
| `needs-triage` | 等待维护者评估 | 维护者 |
| `needs-info` | 等待报告者补充信息 | 报告者 |
| `ready-for-agent` | 需求明确，Agent 可独立实现 | Agent |
| `ready-for-human` | 需要人工实现 | 开发者 |
| `wontfix` | 不做 | 无人 |
| `needs-db-migration` | 需要数据库变更（aifriend 扩展） | 开发者审查 |

### 状态流转

```
未标记 issue
    ↓
needs-triage ──→ needs-info ──→ needs-triage（报告者回复后重新评估）
    │
    ├──→ ready-for-agent（需求明确、无需人工判断）
    ├──→ ready-for-human（需要人工判断：设计决策、安全审计、高风险模块）
    ├──→ wontfix（不做，记录原因）
    └──→ needs-db-migration（需要数据库变更，block 住等待 migration 审查）
```

---

## 分类流程

### 第一步：读取 issue 内容

```bash
gh issue view <number> --comments
```

确认：
- 标题是否清晰描述了问题/需求？
- 描述是否包含了足够复现的步骤（bug）或用户故事（enhancement）？
- 是否涉及 aifriend 的领域概念？（对照 `CONTEXT.md` 术语表）

### 第二步：aifriend 专属检查

对每个 issue，必须回答以下三个问题：

#### A. 是否涉及高风险模块？
检查 issue 是否触及以下 8 个区域：
- `routers/admin/`、`routers/billing.py`
- `services/chat_stream_service.py`、`services/chat_send.py`
- `core/auth.py`、`core/database.py`
- `repositories/`、`alembic/versions/`

→ 如果涉及 → 标记 `ready-for-human`（高风险模块必须人工审查）
→ 如果是 enhancement 且涉及高风险模块 → 同时标记 `needs-info`，要求补充安全影响评估

#### B. 是否需要后台管理配置？
遵循 CLAUDE.md **新增功能同步配置**规则：
- 新功能是否需要在管理后台加配置项？
- 角色卡相关变更是否需要管理后台的新字段？
- 付费相关变更是否需要订单管理的新面板？

→ 如果是 → 在 issue 评论中提醒："此功能需要在管理后台同步添加配置：[具体建议]"

#### C. 是否需要数据库变更？
遵循 CLAUDE.md **新增功能同步测试**规则：
- 需要新表？新字段？修改约束？
- 影响哪些已有数据？
- 是否需要数据迁移脚本？

→ 如果是 → 标记 `needs-db-migration`，评论中注明涉及的表/字段
→ 在 migration 审查通过前保持 `needs-db-migration` 状态

### 第三步：分配状态角色

根据以上检查结果，分配最终状态：

| 场景 | 分配 |
|------|------|
| enhancement + 需求明确 + 不涉及高风险 + 无 DB 变更 | `ready-for-agent` |
| enhancement + 涉及高风险模块 | `ready-for-human` |
| bug + 复现步骤清晰 + 不涉及高风险 | `ready-for-agent` |
| bug + 涉及高风险模块 | `ready-for-human` |
| 需要数据库变更（无论 bug 或 enhancement） | `needs-db-migration`（附加标签） |
| 信息不足 | `needs-info` |
| 维护者决定不做 | `wontfix`（必须写原因） |

### 第四步：应用标签并评论

1. 通过 `gh issue edit <number> --add-label "<label>"` 应用标签
2. 添加评论，包含分类理由和 aifriend 专属检查结果

---

## 批量分类

每周清理时，批量获取未标记的 issue：

```bash
gh issue list --label "" --limit 50
```

对每个 issue 执行以上分类流程。

---

## 标签映射

| 标准角色 | GitHub 标签 |
|----------|------------|
| `needs-triage` | `needs-triage` |
| `needs-info` | `needs-info` |
| `ready-for-agent` | `ready-for-agent` |
| `ready-for-human` | `ready-for-human` |
| `wontfix` | `wontfix` |
| `needs-db-migration` | `needs-db-migration` |

aifriend 项目的标签映射存储在 `docs/agents/triage-labels.md`（如果尚未创建，在首次分类时创建）。
