# 角色创建指南

> **文档用途**：本文件是新增角色的完整操作指南。
>
> **最后更新**：2026-05-06 v2.1
> **状态**：正式版

---

## 核心原则

1. **手动填写**：角色信息通过管理后台或 SQL 手动填写，不依赖任何自动导入工具
2. **精品路线**：数据库里只放经过整理确认的角色
3. **`runtime_cache_json` 是核心**：这是运行时 Prompt 的唯一来源，其他字段主要用于展示

---

## 目录

1. [数据库字段说明](#一、数据库字段说明)
2. [运行时分层（runtime_cache_json）详解](#二、运行时分层详解)
3. [卡类型三分法](#三、卡类型三分法)
4. [创建角色的操作步骤](#四、创建角色的操作步骤)
5. [AI 辅助创作提示词模板](#五、AI-辅助创作提示词模板)
6. [审查清单](#六、审查清单)
7. [常见错误与处理方法](#七、常见错误与处理方法)

---

## 一、数据库字段说明

### characters 表核心字段

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `id` | TEXT (PK) | ✅ | 唯一 ID，建议 `角色英文名_v1` 格式，如 `chen_xu_v1` |
| `name` | TEXT | ✅ | 显示名称，如 `陈序` |
| `abbr` | TEXT | ✅ | 缩写/代号，供系统内部引用，如 `陈序` 或 `CX` |
| `subtitle` | TEXT | ✅ | 角色广场卡片副标题（30-60字最佳），展示给用户的一句话简介 |
| `avatar_url` | TEXT | — | 头像文件路径 |
| `cover_url` | TEXT | — | 封面图路径，留空则自动用 avatar_url |
| `description` | TEXT | ✅ | 角色简介（对外展示），200字以内 |
| `tags` | TEXT | ✅ | JSON 数组，如 `["腹黑", "霸道总裁", "现代都市"]` |
| `opening_message` | TEXT | ✅ | 默认开场白（第一条剧情线的开场），完整展示，不截断 |
| `system_prompt` | TEXT | ✅ | 主系统提示（一句话定性，如"你是陈序，..."） |
| `sort_order` | INTEGER | — | 排序序号，数字越小越靠前，默认 0 |
| `asset_type` | TEXT | ✅ | 资产类型：`character`/`hybrid`/`scenario`/`system` |
| `card_type` | TEXT | ✅ | 产品卡类型（见第三章）：`intimate`/`scenario` |
| `runtime_cache_json` | JSONB（经 002 迁移） | ✅ | **核心字段**：运行时分层数据（见第二章，最重要的字段） |
| `is_visible` | INTEGER | ✅ | 是否对外可见：`1`=可见，`0`=隐藏（测试用） |
| `affection_enabled` | INTEGER | — | 是否在前端展示好感度/关系状态条：`1`=展示（默认），`0`=隐藏；关闭计算请用 `affection_rules_json.enabled=false` |
| `home_priority` | INTEGER | — | 前台广场排序优先级，1最高，999默认（不在前台） |

### 仅管理后台使用的字段（可选，保留历史数据兼容）

| 字段名 | 说明 | 默认值 |
|--------|------|--------|
| `structured_asset_json` | 中间结构化数据（管理后台编辑角色时读取） | `'{}'` |
| `source_kind` | 来源类型：`manual`（手动）/`seed` | `'manual'` |
| `import_locked` | 展示字段是否已锁定 | `0` |

> 💡 **最关键的字段**：`runtime_cache_json`。这是运行时 Prompt 的唯一来源，
> 其他字段主要用于展示，这个字段决定 AI 的实际表现。

---

## 二、运行时分层详解

`runtime_cache_json` 是一个 JSON 对象，包含以下层位：

```json
{
  "asset_type": "hybrid",
  "primary_system_prompt": "（主系统提示，100-500字，定性角色基调和交互规则）",
  "base_profile": "（角色基础档案，姓名/外貌/背景/关系，可达 6000-8000 字）",
  "personality": "（性格特征、说话方式、口头禅、反应模式，1000-3000 字）",
  "scenario": "（当前剧情背景或世界观背景，可随剧情线切换，500-3000 字）",
  "world_rules": "（世界规则、行为约束、不可逾越的底线，可选，200-2000 字）",
  "examples": "（示例对话，展示理想的互动范例，可选，500-3000 字）",
  "post_history_rules": "（放在历史消息之后的提醒，如'请保持角色特征'，100字以内）",
  "alternate_greetings": [
    "（第2条开场白，对应第2条剧情线）",
    "（第3条开场白，对应第3条剧情线）"
  ],
  "opening_message": "（默认开场白，与 DB 里的 opening_message 保持一致）",
  "first_message": "（同 opening_message，兼容字段）",
  "extension_hints": {
    "depth_prompt": {
      "prompt": "（插入在历史消息中某个深度位置的提示，可选）",
      "depth": 4,
      "role": "user"
    }
  },
  "world_info_before": "（World Info 常驻词条，注入在角色设定前，世界观/背景）",
  "world_info_after": "（World Info 常驻词条，注入在角色设定后，规则补充）",
  "conditional_entries": [
    {
      "keys": ["关键词1", "关键词2"],
      "content": "（当对话中出现上述关键词时，动态注入的内容）",
      "position": "before_char",
      "insertion_order": 10
    }
  ]
}
```

### 各层注入顺序（最终 system prompt 结构）

```
[system 消息 = 以下内容合并为一条]
  1. world_info_before        ← 世界观/背景（最高优先级）
  2. primary_system_prompt    ← 角色基调定性
  3. base_profile             ← 角色档案
  4. personality              ← 性格设定
  5. scenario                 ← 当前场景
  6. world_rules              ← 世界规则
  7. examples                 ← 示例对话
  8. world_info_after         ← 补充规则/随机事件
  [conditional_entries 按关键词动态追加]

[assistant 消息 = 长期记忆摘要]

[历史消息 user/assistant 交替]
  depth_prompt 插入在 depth=N 处

[user 消息 = post_history_rules 提醒]

[最新用户消息]
```

### 字段填写原则

| 层位 | 填什么 | 长度建议 | 重要性 |
|------|--------|----------|--------|
| `primary_system_prompt` | 角色定性，"你是XX，请扮演..." + 核心规则 | 200-500字 | ⭐⭐⭐⭐⭐ |
| `base_profile` | 人物卡：姓名/年龄/外貌/经历/与用户关系 | 2000-8000字 | ⭐⭐⭐⭐⭐ |
| `personality` | 说话方式/口癖/情绪模式/禁忌话题 | 500-3000字 | ⭐⭐⭐⭐ |
| `scenario` | 相遇背景/当前时间线/空间设定 | 200-2000字 | ⭐⭐⭐⭐ |
| `world_rules` | 世界观约束/剧情不可触碰的底线 | 可选，200-2000字 | ⭐⭐⭐ |
| `examples` | 3-5 组对话示例，展示理想效果 | 500-3000字 | ⭐⭐⭐ |
| `alternate_greetings` | 多剧情线时的备用开场白列表 | 每条 100-500字 | ⭐⭐⭐ |
| `post_history_rules` | 对话末尾的小提醒（不要超出太多） | <100字 | ⭐⭐ |
| `world_info_*` + `conditional_entries` | World Info 词条（复杂卡才需要） | 按需 | 可选 |

---

## 三、卡类型三分法

每张卡必须归属三种类型之一，这决定了前台展示和 Prompt 构建逻辑。

### `intimate` — 亲密对话卡

**定位**：角色扮演聊天，主打情感陪伴。用户与单一角色深度互动。

**特征**：
- 有完整的人物档案（base_profile 是核心）
- **支持人生档案（life_profile_json）**：童年、家庭、工作等完整背景，每轮对话都会注入
- 重视长期记忆和好感度变化
- 好感度系统：追踪用户关系进展（stranger → acquaintance → friend → lover）

**Prompt 构建**：走 `character_builder` / `hybrid_builder`

**管理后台配置**：
- 显示"人生档案"编辑器（7个维度：基本信息、童年、家庭、工作、性格、习惯、重要经历）
- 不显示剧情沙盒专属字段（scenario、alternate_greetings）

---

### `scenario` — 剧情沙盒卡

**定位**：剧情驱动，有明确故事线和推进逻辑。AI 更像故事叙述者 + 角色扮演。

**特征**：
- `scenario` 字段丰富，有多个章节/阶段
- `world_rules` 有明确的剧情推进规则
- `alternate_greetings` 支持多条剧情线开场白
- 可以有多个 NPC（通过 conditional_entries 实现）
- **支持剧情类型（scenario_type）**：`adventure`（冒险）或 `romance`（恋爱），使用不同的 System Prompt
- 沉浸度系统：追踪剧情进展（explore、discover、challenge_won、obstacle_cleared 等事件）

**Prompt 构建**：走 `scenario_builder`（根据 scenario_type 动态选择 System Prompt）

**管理后台配置**：
- 显示"剧情类型"选择（adventure/romance）
- 显示剧情沙盒专属字段（scenario、alternate_greetings）
- 不显示"人生档案"（避免污染剧情 prompt）
- 沉浸度事件名：challenge_won、obstacle_cleared、problem_resolved、setback、unexpected_danger 等

---

## 四、创建角色的操作步骤

### 方式一：通过管理后台创建（推荐）

1. 访问 `/admin.html` → 角色管理 → 新增角色
2. 填写基础信息：名称、副标题、标签、卡类型等
3. 在高级配置中填写 `runtime_cache_json` 的各层内容
4. 设置 `home_priority`（1-4 = 精选展示，999 = 不在前台）
5. 设置 `is_visible` = 1 对外可见
6. 保存后重启后端生效

### 方式二：通过 SQL 直接插入

```sql
INSERT INTO characters (
    id, name, abbr, subtitle, tags, opening_message,
    system_prompt, asset_type, card_type,
    runtime_cache_json,
    is_visible, home_priority
) VALUES (
    'char_id_v1',
    '角色名',
    '角色名',
    '30-60字的一句话简介',
    '["标签1", "标签2", "标签3"]',
    '开场白内容',
    '你是XXX，请全程保持角色扮演。',
    'character',
    'intimate',
    '{
        "asset_type": "character",
        "primary_system_prompt": "角色定性...",
        "base_profile": "人物档案...",
        "personality": "性格描述...",
        "scenario": "",
        "world_rules": "",
        "examples": "",
        "post_history_rules": "请始终保持角色特征。",
        "alternate_greetings": [],
        "opening_message": "开场白...",
        "first_message": "开场白...",
        "world_info_before": "",
        "world_info_after": "",
        "conditional_entries": []
    }'::jsonb,
    1,  -- is_visible: 1=可见, 0=隐藏
    999
);
```

### 方式三：通过 Python 脚本插入

```python
import json
from core.database import get_db_dep

# 使用 FastAPI 依赖注入获取数据库连接
# 或直接使用连接池：
from core.database import get_conn

with get_conn() as conn:
    conn.execute("""
        INSERT INTO characters (
            id, name, abbr, subtitle, tags, opening_message,
            system_prompt, sort_order,
            asset_type, card_type,
            runtime_cache_json,
            is_visible, home_priority
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s,
            %s, %s,
            %s,
            %s, %s
        )
    """, (
        "char_id_v1",
        "角色名",
        "角色名",
        "30-60字的一句话简介",
        json.dumps(["标签1", "标签2", "标签3"], ensure_ascii=False),
        "开场白内容",
        "你是XXX，请全程保持角色扮演。",
        0,
        "character",
        "intimate",
        json.dumps({
            "asset_type": "character",
            "primary_system_prompt": "...",
            "base_profile": "...",
            "personality": "...",
            "scenario": "",
            "world_rules": "",
            "examples": "",
            "post_history_rules": "请始终保持角色特征。",
            "alternate_greetings": [],
            "opening_message": "...",
            "first_message": "...",
            "world_info_before": "",
            "world_info_after": "",
            "conditional_entries": []
        }, ensure_ascii=False),
        True,  # is_visible: 1=可见, 0=隐藏（PostgreSQL 自动转换）
        999,
    ))
    conn.commit()  # 注意：get_conn() 默认 auto_commit=False，需手动提交
print("写入完成")
```

---

## 五、AI 辅助创作提示词模板

### 5.1 从文本素材创建角色

```
你是一个角色创作助手。我将给你一份角色描述（或文本素材），请按照以下模板格式，整理并创作角色信息：

模板字段说明：
1. primary_system_prompt（100-500字）：角色定性，"你是XXX，请扮演..." + 与用户互动的核心规则
2. base_profile（2000-8000字）：人物档案，包括姓名/年龄/外貌/性格概述/背景故事/与用户的关系
3. personality（500-3000字）：详细性格描述，说话方式/口头禅/情绪反应模式/禁忌话题/行为边界
4. scenario（200-2002字）：当前相遇背景，用户是谁/发生了什么/当前时间地点
5. world_rules（可选，200-2000字）：世界观约束/剧情底线，只有存在明确限制时才填
6. examples（可选，500-3000字）：3-5 组示例对话，展示角色的理想互动风格
7. opening_message（100-500字）：第一条开场白，角色主动开口的台词，有代入感
8. alternate_greetings（可选，列表）：如果有多条剧情线，列出其余开场白
9. card_type：从 intimate/scenario 两种中选一种
10. subtitle（30-60字）：展示给用户的一句话简介
11. tags（JSON 数组）：3-6个标签，如 ["腹黑", "现代都市", "霸道总裁"]

要求：
- 输出 JSON 格式
- 保持人物一致性，确保各字段描写的是同一个角色
- 输出中文

以下是素材：
[粘贴素材]
```

### 5.2 质量审查

```
你是一个 AI 角色卡质量审查员。请审查以下角色信息，检查以下问题：

1. 人设一致性：各字段描述的角色是否统一
2. 开场白质量：opening_message 是否有代入感，是否符合角色性格
3. 示例对话：examples 里的角色回复是否真实还原了角色性格
4. 字段完整性：有无明显缺失的关键字段
5. 卡类型匹配：card_type 选择是否合理

对每个问题给出评分（1-5分）和具体改进建议。

[粘贴角色 JSON]
```

---

## 六、审查清单

在角色正式上线前，逐项检查：

### 基础信息
- [ ] `id` 唯一，不与现有角色冲突
- [ ] `name` 和 `subtitle` 展示效果良好
- [ ] `tags` 准确，用户能通过标签找到这个角色
- [ ] `avatar_url` 指向的图片文件存在，头像正常显示

### 运行时质量（最重要）
- [ ] `primary_system_prompt` 清晰定性了角色身份和交互规则
- [ ] `base_profile` 内容丰富，不空洞
- [ ] `personality` 描述具体，有辨识度
- [ ] `opening_message` 有代入感，符合角色性格
- [ ] `examples` 里的角色回答真实还原了人设

### 实测对话
- [ ] 基本对话：问了3个普通问题，角色回复风格一致
- [ ] 边界测试：问了角色"你是AI吗"或离题话题，处理方式符合预期
- [ ] 开场白：进入角色后，开场白正常展示，不截断
- [ ] 多剧情线（如有）：切换剧情线后，开场白和场景正确变化

### 系统配置
- [ ] `card_type` 设置正确（intimate/scenario）
- [ ] `home_priority` 设置正确（1-4 = 精选展示，999 = 不在前台）
- [ ] `is_visible` = 1

---

## 七、常见错误与处理方法

| 现象 | 可能原因 | 处理方法 |
|------|----------|----------|
| 角色回复没有人设感，像通用 AI | `base_profile` 和 `personality` 太空洞 | 加入具体细节，参考优质卡的写法 |
| 开场白只显示一部分 | `opening_message` 字段数据被截断 | 检查数据库里的实际值，确认无截断 |
| 角色广场不显示新角色 | `home_priority` 是 999 或 `is_visible` 是 0 | 检查这两个字段；确保 `home_priority` 设为 1-4 |
| AI 不按剧情线走 | `alternate_greetings` 空或 `scenario` 字段空 | 补充对应剧情线的 scenario 内容 |
| World Info 关键词不触发 | `conditional_entries` 的 `keys` 没匹配到对话内容 | 检查关键词是否准确 |
| `card_type` 不对 | 创建时选错类型 | 在管理后台或 SQL 中修改 `card_type` 字段 |
| 多开场白弹窗不出现 | `alternate_greetings` 数组为空 | 在 `runtime_cache_json` 里填写 alternate_greetings |

---

## 附录：精品卡参考标准

| 角色 | card_type | 亮点 | 适合参考的字段 |
|------|-----------|------|---------------|
| 陈序 | intimate | 多开场白，剧情线丰富 | alternate_greetings 写法 |
| 路少晖 | scenario | 多条剧情线，世界书完整 | scenario + conditional_entries |
| 阮绿瓷 | intimate | HTML 状态面板，变量系统 | extension_hints 用法 |
| 姜梨 | intimate | 变量初始化系统，好感度追踪 | custom_vars 设计思路 |
