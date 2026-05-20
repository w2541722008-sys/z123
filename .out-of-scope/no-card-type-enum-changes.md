---
scope: agent-behavior
severity: critical
---

# 禁止修改 card_type 枚举值

## 规则

Agent **绝对禁止**修改、删除或重命名 `card_type` 的枚举值（`intimate` 和 `scenario`）。

## 原因

- `card_type` 是整个系统的核心分叉逻辑，影响：
  - 前端 UI 字段动态显示（管理后台根据 card_type 显示不同配置面板）
  - 后端 prompt 构建路径（`prompt_assembler.py` 根据 card_type 选择不同逻辑）
  - 数据库 character_cards 表的已有数据
  - 好感度/沉浸度两套独立的追踪系统
- 修改枚举值会导致已有角色卡数据不可读、两种玩法逻辑混乱

## 允许的操作

- 在 `card_type` 的现有语义下**增强**功能（如给 intimate 增加新的好感度事件）
- 在**新增字段**中扩展玩法（如给 scenario 增加新的剧情类型子项）
- 修改枚举值的**标签映射**（仅限展示层，如 `constants/mood.py` 中的标签）

## 如需新增玩法类型

如果确实需要第三种玩法：
1. 在 `card_type` 中**新增**枚举值（如 `card_type=sandbox`），不修改已有值
2. 同步更新所有 `if card_type ==` 分支
3. 同步更新前端管理后台的字段显示逻辑
4. 创建对应的新 prompt 路径
5. 创建数据库 migration
