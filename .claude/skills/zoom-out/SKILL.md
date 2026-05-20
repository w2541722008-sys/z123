---
name: zoom-out
description: 宏观视角切换 — 当你不熟悉某个代码区域时，让 Agent 跳出一层抽象，用项目的领域词汇（CONTEXT.md）输出相关模块、调用者和数据流向的全景地图。适用场景：初次接触某个模块、理解跨模块影响范围、评估改动影响面。
---

# 宏观视角（Zoom Out）

## 触发条件

当你遇到以下情况时说"zoom out"或"给我一个宏观视角"：
- 第一次接触某个不熟悉的代码区域
- 需要理解一个改动会影响多少模块
- 想看清数据流从请求到响应的完整路径

## 输出格式

Agent 应该从以下角度组织输出：

### 1. 模块全景图
用缩进树形结构展示相关模块及其关系：
```
routers/chat/send.py
  └─→ services/chat_send.py
        ├─→ services/prompt_assembler.py
        │     ├─→ services/runtime_bundle.py
        │     ├─→ services/token_budget.py
        │     └─→ repositories/character_repository.py
        ├─→ services/character_affection.py（仅 intimate）
        ├─→ services/story_event_service.py（仅 scenario）
        └─→ core/model_adapter.py
```

### 2. 数据流
描述数据从入口到出口的转换过程，每一步标注关键变量/结构。

### 3. 关键决策点
标注 if/else 分叉和它们的条件（如 `if card_type == 'intimate'`）。

### 4. 相关的 CONTEXT.md 术语
列出理解这段代码需要知道的领域概念。

## 语言要求

- 用中文描述流程
- 模块路径、函数名、变量名保留英文
- 引用 CLAUDE.md 中的架构图做导航锚点
- 使用 CONTEXT.md 中的领域术语而非通用词
