# 角色导入 SOP — AI男友项目

> **文档用途**：本文件是新增角色的完整操作指南。
> 无论是人工添加还是交给 AI 辅助处理，都以这份文档为唯一标准。
>
> **最后更新**：2026-03-27 v1.2
> **状态**：正式版 v1.2

---

## 核心原则（必读）

> **本系统不与任何角色卡文件目录绑定，启动时不做任何自动导入。**

1. **精品路线**：数据库里只放经过整理确认的角色，不做"导入样本池"的操作。
2. **PNG 是原料，不是配置**：本地 `角色卡/` 目录仅用于调试和参考，不与系统绑定。每次启动服务，数据库内容不会因为目录里的 PNG 而改变。
3. **三步走**：手动指定 PNG → AI 分析填展示字段 → 人工复核上线。缺一不可。
4. **`import_locked` 是唯一保护机制**：字段确认后设为 1，之后无论怎么操作都不会覆盖。

---

## 目录

1. [总体流程（一张图）](#一、总体流程)
2. [数据库字段说明](#二、数据库字段说明)
3. [运行时分层（runtime_cache_json）详解](#三、运行时分层详解)
4. [卡类型三分法](#四、卡类型三分法)
5. [原料来源与解析方法](#五、原料来源与解析方法)
6. [AI 分析提示词模板](#六、AI-分析提示词模板)
7. [写入数据库的操作步骤](#七、写入数据库的操作步骤)
8. [审查清单](#八、审查清单)
9. [常见错误与处理方法](#九、常见错误与处理方法)

---

## 一、总体流程

```
原料来源
  ├── PNG 角色卡（SillyTavern 格式）
  ├── 小说/剧本文本素材
  ├── 自己构思的人物设定
  └── 多源混合

        ↓ 解析阶段（一次性提取原料）
        工具：card_asset_parser 自动解析 PNG → 写入 raw_card_json
        策略：PNG 只是原料来源，导入后就和 PNG 脱钩
              此后重启服务不再更新展示字段（import_locked 机制保护）

        ↓ AI 分析阶段（自动化，一次性）
        工具：python cli/card_analyze.py [--name 角色名]
        产出：subtitle（简介）/ tags（标签）/ opening_message（开场白）
        写入：import_locked=1，之后 PNG 重导入不再覆盖

        ↓ 人工复核阶段（必须）
        审查 AI 填写的字段是否准确、有吸引力
        如需修改：直接改数据库（import_locked 继续保持 1）
        配置 card_type、home_priority、is_visible

        ↓ 审查阶段（上线前）
        对话测试 → 检查人设一致性 → 调整 runtime_cache_json 里的 Prompt 层
```

**核心原则**：PNG 是一次性原料，不和系统持续绑定。
展示字段（subtitle/tags/opening_message）由 AI 分析填写，人工最终拍板，写死在数据库里。

---

## 二、数据库字段说明

### characters 表完整字段

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `id` | TEXT (PK) | ✅ | 唯一 ID，建议 `角色英文名_v1` 格式，如 `chen_xu_v1` |
| `name` | TEXT | ✅ | 显示名称，如 `陈序` |
| `abbr` | TEXT | ✅ | 缩写/代号，供系统内部引用，如 `陈序` 或 `CX` |
| `subtitle` | TEXT | ✅ | 角色广场卡片副标题（30-60字最佳），展示给用户的一句话简介 |
| `avatar_url` | TEXT | — | 头像文件路径，如 `85e1ec18737cb1e8.png`（相对于角色卡目录） |
| `cover_url` | TEXT | — | 封面图路径，留空则自动用 avatar_url |
| `description` | TEXT | ✅ | 角色简介（对外展示），200字以内，可以是开场气氛描写 |
| `tags` | TEXT | ✅ | JSON 数组，如 `["腹黑", "霸道总裁", "现代都市"]` |
| `opening_message` | TEXT | ✅ | 默认开场白（第一条剧情线的开场），完整展示，不截断 |
| `system_prompt` | TEXT | ✅ | 主系统提示（一句话定性，如"你是陈序，..."） |
| `sort_order` | INTEGER | — | 排序序号，数字越小越靠前，默认 0 |
| `mock_reply_style` | TEXT | — | JSON 数组，mock 回复风格关键词，如 `["冷淡", "简洁"]` |
| `asset_type` | TEXT | ✅ | 资产类型：`character`/`hybrid`/`world`/`scenario`/`system` |
| `card_type` | TEXT | ✅ | 产品卡类型（见第四章）：`intimate`/`scenario`/`world` |
| `source_kind` | TEXT | — | 来源类型：`seed`（手动）/`png_card`（PNG导入）/`manual` |
| `source_path` | TEXT | — | 原始文件路径（记录溯源用） |
| `raw_card_json` | TEXT | — | 原始 PNG 卡的 JSON 数据（原样存储，不做二次处理） |
| `structured_asset_json` | TEXT | — | 中间结构化数据（通常由 card_asset_parser 生成） |
| `runtime_cache_json` | TEXT | ✅ | **核心字段**：运行时分层数据（见第三章，最重要的字段） |
| `import_diagnostics` | TEXT | — | 导入诊断信息，JSON 数组，记录解析过程中的警告/提示 |
| `is_visible` | INTEGER | ✅ | 是否对外可见：`1`=可见，`0`=隐藏（测试用） |
| `home_priority` | INTEGER | — | 前台广场排序优先级，1最高，999默认（不在前台） |
| `embedded_format` | TEXT | — | PNG 内嵌数据格式：`json`/`png_tEXt`，通常自动识别 |
| `import_locked` | INTEGER | — | 展示字段是否已锁定：`1`=锁定（AI已分析确认），`0`=未锁定（初次导入状态）。锁定后重启服务不覆盖 subtitle/tags/opening_message |

> 💡 **最关键的字段**：`runtime_cache_json`。这是运行时 Prompt 的唯一来源，
> 其他字段主要用于展示，这个字段决定 AI 的实际表现。

---

## 三、运行时分层详解

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

## 四、卡类型三分法

每张卡必须归属三种类型之一，这决定了前台展示和 Prompt 构建逻辑。

### `intimate` — 亲密对话卡 💞

**定位**：角色扮演聊天，主打情感陪伴。用户与单一角色深度互动。

**特征**：
- 有完整的人物档案（base_profile 是核心）
- 重视长期记忆和好感度变化
- 可以有多条剧情线（alternate_greetings）
- 典型案例：陈序、高凌枫、阮绿瓷、姜梨

**Prompt 构建**：走 `character_builder` / `hybrid_builder`

---

### `scenario` — 剧情沙盒卡 🎭

**定位**：剧情驱动，有明确故事线和推进逻辑。AI 更像故事叙述者 + 角色扮演。

**特征**：
- `scenario` 字段丰富，有多个章节/阶段
- `world_rules` 有明确的剧情推进规则
- 用户选择不同开场白 → 走不同剧情线
- 可以有多个 NPC（通过 conditional_entries 实现）
- 典型案例：路少晖（6条剧情线）

**Prompt 构建**：走 `scenario_builder`

---

### `world` — 世界卡 🌐

**定位**：世界观探索，AI 扮演整个世界的系统/导游/NPC 集合。

**特征**：
- `world_rules` 和 `world_info_before/after` 是核心
- 有丰富的 `conditional_entries`（多 NPC / 多场景触发）
- 用户可以自由探索世界，而不是跟随单一剧情
- 典型案例：淑女学园都市（10+ NPC，日期系统）

**Prompt 构建**：走 `world_builder`（system_builder）

---

## 五、原料来源与解析方法

### 来源 A：PNG 角色卡（SillyTavern 格式）

PNG 卡内嵌了 JSON 数据，可用 `card_asset_parser.py` 自动解析。

**自动解析后得到的关键字段**：
- `spec`: 格式标准（chara_card_v2 / v3）
- `name`, `description`, `personality`, `scenario`, `mes_example`
- `first_mes`, `alternate_greetings`（多开场白）
- `character_book.entries`（World Info 词条）
- `system_prompt`, `post_history_instructions`

**解析后如何加工**：
1. 原始字段通常写法随意，需要重新整理格式
2. `description` 可能包含世界观+角色档案混在一起，需要分离
3. 长度超标时，提炼核心内容，删去冗余
4. 对话示例 `mes_example` 质量参差不齐，选用最有代表性的

---

### 来源 B：小说/剧本文本

把文本素材直接交给 AI，让 AI 提取关键信息填入模板。

**建议提取的维度**：
- 人物外貌、年龄、身份
- 典型台词（用于推断说话风格）
- 关键事件（用于 scenario 背景）
- 人物关系（与用户角色的定位）
- 禁忌/原则（world_rules）

---

### 来源 C：自主创作

直接按模板填写，最灵活。可以参考已有精品卡（陈序、路少晖等）的写法风格。

**创作建议**：
- `base_profile` 可以参考"人物小传"的写法，有血有肉
- `personality` 用第一人称描述更生动（"我说话时习惯..."）
- `examples` 最好包含用户问题 + 角色典型回答，展示真实对话节奏

---

## 六、AI 分析提示词模板

### 6.1 从 PNG 卡原始数据提取 → 我们的模板格式

```
你是一个角色创作助手。我将给你一份 SillyTavern 角色卡的原始 JSON 数据（或文本描述），请按照我们项目的模板格式，提取并整理以下字段：

项目模板字段说明：
1. primary_system_prompt（100-500字）：角色定性，"你是XXX，请扮演..." + 与用户互动的核心规则
2. base_profile（2000-8000字）：人物档案，包括姓名/年龄/外貌/性格概述/背景故事/与用户的关系
3. personality（500-3000字）：详细性格描述，说话方式/口头禅/情绪反应模式/禁忌话题/行为边界
4. scenario（200-2000字）：当前相遇背景，用户是谁/发生了什么/当前时间地点
5. world_rules（可选，200-2000字）：世界观约束/剧情底线，只有存在明确限制时才填
6. examples（可选，500-3000字）：3-5 组示例对话，展示角色的理想互动风格
7. opening_message（100-500字）：第一条开场白，角色主动开口的台词，有代入感
8. alternate_greetings（可选，列表）：如果有多条剧情线，列出其余开场白
9. card_type：从 intimate/scenario/world 三种中选一种
10. subtitle（30-60字）：展示给用户的一句话简介
11. tags（JSON 数组）：3-6个标签，如 ["腹黑", "现代都市", "霸道总裁"]

要求：
- 输出 JSON 格式
- 允许根据原素材进行合理的补充和创作，不必完全照搬
- 如果某字段原素材没有对应信息，用空字符串或空数组填充
- 保持人物一致性，确保各字段描写的是同一个角色
- 输出中文

以下是原始数据：
[粘贴原始数据]
```

---

### 6.2 从小说文本提取角色素材

```
你是一个角色创作助手。我有一段小说/剧本文本，里面有一个角色我想做成 AI 聊天角色卡。

请从文本中提取以下信息，为我提供一份创作素材报告：

1. 角色基本信息（姓名/年龄/外貌/身份/职业）
2. 典型台词摘录（5-10句最有代表性的）
3. 性格关键词（5-10个）
4. 角色的行为模式和价值观
5. 与主角/用户的关系定位
6. 背景故事要点
7. 出现过的典型场景（3-5个）
8. 这个角色适合做成哪种卡（intimate/scenario/world）及理由

然后，请把上述信息整合为一份角色卡草稿，按我们的模板格式输出（字段说明同上）。

[粘贴小说文本]
```

---

### 6.3 审查草稿——质量检查

```
你是一个 AI 角色卡质量审查员。请审查以下角色卡草稿，检查以下问题：

1. 人设一致性：各字段（base_profile/personality/examples）描述的角色是否统一
2. 开场白质量：opening_message 是否有代入感，是否符合角色性格
3. 示例对话：examples 里的角色回复是否真实还原了角色性格
4. 字段完整性：有无明显缺失的关键字段
5. 长度合理性：各字段是否过短（敷衍）或过长（冗余）
6. 卡类型匹配：card_type 选择是否合理
7. 与项目定位的契合度：是否适合女性向 AI 陪伴/剧情类产品

对每个问题给出评分（1-5分）和具体改进建议。最后给出总体评分和最需要改进的2-3个方向。

[粘贴角色卡 JSON 草稿]
```

---

## 七、写入数据库的操作步骤

### 新增角色完整流程

#### 步骤 1：用 cli/card_import.py 手动导入指定 PNG

```bash
cd aifriend/backend
source .venv/bin/activate

# 预览解析结果（不写库）
python cli/card_import.py --dry-run --path /path/to/新角色.png

# 确认没问题后，正式导入
python cli/card_import.py --path /path/to/新角色.png

# 查看当前数据库里有哪些角色
python cli/card_import.py --list
```

> ⚠️ 不要直接把 PNG 扔进 `角色卡/` 目录期望系统自动导入——系统不会自动扫描目录。
> 每次导入都必须手动执行 `cli/card_import.py`，这是有意为之，保证数据库里只有精品。

---

#### 步骤 2：跑 AI 分析工具，自动填展示字段

```bash
cd aifriend/backend
source .venv/bin/activate

# 分析指定角色（模糊匹配名称）
python cli/card_analyze.py --name "新角色名"

# 分析所有未锁定的角色（import_locked=0 的全部跑一遍）
python cli/card_analyze.py

# 先查看哪些卡还没分析
python cli/card_analyze.py --list
```

AI 会自动读取 `raw_card_json`，生成：
- `subtitle`（30-60字，面向用户的简介）
- `tags`（5个，用户友好标签）
- `opening_message`（如原卡开场白有版权声明/CSS 垃圾则重新生成）

分析完成后自动设 `import_locked=1`，之后重启服务不会覆盖这些字段。

---

#### 步骤 3：人工复核 AI 填写的内容

```bash
# 查看 AI 填写结果（通过 psql 查询 Supabase）
psql $DATABASE_URL -c "SELECT name, subtitle, tags, opening_message FROM characters WHERE name LIKE '%角色名%';"
```

如果觉得 AI 写的不好，直接改数据库（import_locked 继续保持 1）：

```sql
-- 在 Supabase SQL Editor 中执行
UPDATE characters SET subtitle = '你改好的 subtitle' WHERE name LIKE '%角色名%';
```

---

#### 步骤 4：前台配置（如需在首页展示）

在 `main.py` 里找到 `FEATURED_HOME_CARD_KEYWORDS`，加入角色：

```python
FEATURED_HOME_CARD_KEYWORDS: list[list[str]] = [
    ["高凌枫"],
    ["阮绿瓷"],
    ["路少晖"],
    ["淑女学园都市"],
    ["新角色名"],   # ← 加在这里
]
```

如果 card_type 不是 intimate（默认），在 `_card_type_overrides` 里加：

```python
_card_type_overrides = [
    ("路少晖", "scenario"),
    ("淑女学园都市", "world"),
    ("新角色名", "scenario"),  # ← 根据实际类型改
]
```

然后重启后端，新角色就会出现在前台对应分区。

---

#### 也可以跳过 PNG，纯手动创建角色

直接写 Python 脚本插入数据库，适合自主创作的角色（无 PNG 来源）：

```python
import json, os
from database import get_db  # 项目自身的数据库连接模块

with get_db() as conn:
    conn.execute("""
        insert into characters (
            id, name, abbr, subtitle, tags, opening_message,
            system_prompt, sort_order, mock_reply_style,
            asset_type, card_type, source_kind, source_path,
            embedded_format, raw_card_json, structured_asset_json,
            runtime_cache_json, import_diagnostics,
            is_visible, home_priority, import_locked
        ) values (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            'manual', '', '',
            %s, '[]',
            %s, %s, 1
        )
    """, (
        "char_id_v1",                              # id
        "角色名",                                   # name
        "角色名",                                   # abbr
        "30-60字的一句话简介",                       # subtitle
        json.dumps(["标签1", "标签2", "标签3"], ensure_ascii=False),  # tags
        "开场白内容",                               # opening_message
        "你是XXX，请全程保持角色扮演。",              # system_prompt
        0,                                          # sort_order
        json.dumps([], ensure_ascii=False),         # mock_reply_style
        "character",                                # asset_type
        "intimate",                                 # card_type (intimate/scenario/world)
        "manual",                                   # source_kind
        "",                                         # source_path
        json.dumps({                               # runtime_cache_json（核心字段）
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
        1,    # is_visible
        999,  # home_priority（加入精选后改小）
    ))
print("写入完成")
```

> `import_locked=1` 直接写 1，跳过 AI 分析步骤。
>
> 注意：运行此脚本前需要先 `cd backend` 并确保 `.env` 中的 `DATABASE_URL` 已配置。

---

## 八、审查清单

在角色正式上线前，逐项检查：

### 基础信息
- [ ] `id` 唯一，不与现有角色冲突
- [ ] `name` 和 `subtitle` 展示效果良好（在前台卡片上截图确认）
- [ ] `tags` 准确，用户能通过标签找到这个角色
- [ ] `avatar_url` 指向的图片文件存在，头像正常显示

### 运行时质量（最重要）
- [ ] `primary_system_prompt` 清晰定性了角色身份和交互规则
- [ ] `base_profile` 内容丰富，不空洞
- [ ] `personality` 描述具体，有辨识度（不是"温柔善良"这种废话）
- [ ] `opening_message` 有代入感，符合角色性格，不像机器人
- [ ] `examples` 里的角色回答真实还原了人设

### 实测对话
- [ ] 基本对话：问了3个普通问题，角色回复风格一致
- [ ] 边界测试：问了角色"你是AI吗"或离题话题，处理方式符合预期
- [ ] 开场白：进入角色后，开场白正常展示，不截断
- [ ] 多剧情线（如有）：切换剧情线后，开场白和场景正确变化

### 系统配置
- [ ] `card_type` 设置正确（intimate/scenario/world），在 `main.py` `_card_type_overrides` 里配置
- [ ] `home_priority` 设置正确（1-4 = 精选展示，999 = 不在前台）
- [ ] `import_locked=1`（已跑 AI 分析或手动确认字段内容）
- [ ] `FEATURED_HOME_CARD_KEYWORDS` 里已加入角色名（如需前台展示）

---

## 九、常见错误与处理方法

| 现象 | 可能原因 | 处理方法 |
|------|----------|----------|
| 角色回复没有人设感，像通用 AI | `base_profile` 和 `personality` 太空洞 | 加入具体细节，参考优质卡的写法 |
| 开场白只显示一部分 | `opening_message` 字段数据被截断 | 检查数据库里的实际值，确认无截断 |
| 角色广场不显示新角色 | `home_priority` 是 999 或 `is_visible` 是 0 | 检查这两个字段；检查名字是否在 `FEATURED_HOME_CARD_KEYWORDS` |
| AI 不按剧情线走 | `alternate_greetings` 空或 `scenario` 字段空 | 补充对应剧情线的 scenario 内容 |
| World Info 关键词不触发 | `conditional_entries` 的 `keys` 没匹配到对话内容 | 检查关键词是否准确；可以临时加几个宽泛的同义词 |
| `card_type` 显示为 intimate 但应该是 scenario | UPSERT 时默认值问题 | 重启后端（`init_db` 的 `card_type_overrides` 会自动修正） |
| 多开场白弹窗不出现 | `alternate_greetings` 数组为空 | 在 `runtime_cache_json` 里填写 alternate_greetings |

---

## 附录：精品卡参考标准

以下是我们项目内已有的精品卡，可作为写法参考：

| 角色 | card_type | 亮点 | 适合参考的字段 |
|------|-----------|------|---------------|
| 陈序 | intimate | 多开场白 29 条，剧情线丰富 | alternate_greetings 写法 |
| 路少晖 | scenario | 6 条剧情线，世界书完整 | scenario + conditional_entries |
| 淑女学园都市 | world | 10+ NPC，日期事件系统 | world_rules + world_info |
| 阮绿瓷 | intimate | HTML 状态面板，变量系统 | extension_hints 用法 |
| 姜梨 | intimate | 变量初始化系统，好感度追踪 | custom_vars 设计思路 |

---

> 文档维护说明：
> 每次架构升级（新增字段、改变 Prompt 结构等），同步更新本文档。
> 版本变化记录在文件头部的"最后更新"字段。
