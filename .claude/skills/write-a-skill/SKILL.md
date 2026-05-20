---
name: write-a-skill
description: 创建新的 Claude Code skill — 按标准结构生成 SKILL.md，支持渐进披露（REFERENCE.md、EXAMPLES.md）和内置脚本（scripts/）。适用场景：为重复性的工作流创建自定义技能、封装项目特有的最佳实践、将 CLAUDE.md 中的规则转化为可触发的技能。
---

# 创建技能（Write a Skill）

## 技能结构

每个技能是一个独立目录，放在 `.claude/skills/<skill-name>/` 下：

```
.claude/skills/<skill-name>/
├── SKILL.md        # 必需：主指令文件（<100 行）
├── REFERENCE.md    # 可选：详细参考（超过 500 行时拆分）
├── EXAMPLES.md     # 可选：使用示例
└── scripts/        # 可选：确定性操作的脚本
```

## SKILL.md 文件格式

```yaml
---
name: skill-name  # 英文 kebab-case
description: 一句话描述。Agent 只看到这个来决定是否加载此技能。必须包含具体触发关键词，不要写模糊的"帮助做某事"。最多 1024 字符。结尾写"适用场景：... 不适用：..."
---

# 技能标题

## 核心原则
[1-2 句话说明核心思路]

## 流程/步骤
[具体的操作步骤，用中文写]

## 与项目规则的关系
[引用 CLAUDE.md 的规则、CONTEXT.md 的术语]
```

## 关键规则

### description 是唯一入口
Agent 在决策加载哪个 skill 时，**只看到 description 字段**。必须：
- 包含具体的触发关键词（如"诊断""拆分""TDD""护栏"）
- 描述技能做什么，而不是"帮助做 X"
- 包含适用和不适用的场景
- 用第三人称

### 主体保持在 100 行以内
- 超过 100 行的内容拆分到 `REFERENCE.md`
- 超过 500 行的 `REFERENCE.md` 继续拆分
- 技能目录可以包含多个引用文件

### scripts/ 用于确定性操作
- 格式校验、数据转换、代码生成等确定性操作用脚本
- 非确定性操作（需判断、需对话）放在 SKILL.md 的主体中

## 创建流程

1. **收集需求**：问用户这个技能要解决什么问题？什么情况下触发？
2. **起草 SKILL.md**：写 description（最关键的 1 句话）、核心原则、流程
3. **与用户审查**：description 是否准确？流程是否完整？边界是否清楚？
4. **创建文件**：写到 `.claude/skills/<name>/SKILL.md`
5. **更新 CLAUDE.md**：在 `## Agent skills` 区块添加一行注册
