# Issue Tracker

aifriend 项目使用 **GitHub Issues** 作为 issue 追踪器。

## 仓库信息

- Owner：`w2541722008-sys`
- Repo：`z123`
- URL：https://github.com/w2541722008-sys/z123

## Agent 操作指南

### 创建 Issue
```bash
gh issue create --title "标题" --body "内容" --label "needs-triage"
```

### 查看 Issue
```bash
gh issue view <number> --comments
```

### 列出 Issue
```bash
gh issue list --label "needs-triage" --limit 20
gh issue list --label "ready-for-agent" --limit 20
```

### 添加标签
```bash
gh issue edit <number> --add-label "ready-for-agent"
```

### 添加评论
```bash
gh issue comment <number> --body "评论内容"
```

### 关闭 Issue
```bash
gh issue close <number> --comment "关闭原因"
```

## 约定

- Agent 不直接关闭 issue，由维护者最终关闭
- 标记 `wontfix` 时必须在评论中说明原因
- 标记 `needs-db-migration` 时必须在评论中注明涉及的表/字段
