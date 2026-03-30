# 好感度系统设计文档

> 文件路径：`aifriend/backend/AFFECTION_SYSTEM.md`
> 最后更新：2026-03-27
> 维护者：小b

---

## 一、设计目标

1. **防刷分**：用户不能通过连续发同类消息快速刷满好感度
2. **数值稳定**：AI 不自己决定加多少分，只上报"发生了什么事"，服务端查规则表算分
3. **可维护**：全局底座规则 + 角色卡自定义规则分离，修改底座一处生效全局
4. **卡类型差异化**：world 卡不启用好感度，intimate 卡默认启用，scenario 卡可选

---

## 二、整体架构

```
用户发消息
    ↓
AI 生成回复（回复末尾附 [STATE_UPDATE]{...}[/STATE_UPDATE] 标签）
    ↓
parse_state_update_tag() 从回复中提取标签内容
    ↓
apply_state_delta() 处理增量：
    ├── 检查 affection_enabled（world 卡直接跳过）
    ├── 读取当前状态（含三防计数器）
    ├── 惰性日重置（日期变了就清空当日统计）
    ├── 查找事件规则（全局底座 + 角色卡覆盖）
    ├── 计算实际加减分（三防保护）
    ├── 更新好感度 / 自动推进阶段 / 更新心情
    └── 写库（含三防计数器）
    ↓
前端收到 character_state（过滤了内部字段，只含可视数据）
```

---

## 三、AI 上报格式

**新版（推荐）：事件驱动**

AI 只判断"发生了什么事"，不判断"加多少分"：

```json
{"event": "deep_conversation", "mood": "warm"}
{"event": "argument", "mood": "cold", "story_phase": "stranger"}
{"event": "compliment", "mood": "happy"}
```

**旧版（兼容）：直接数字**

仍然支持，但三防机制不生效（只做 clip ±10）：

```json
{"affection": "+5", "mood": "happy"}
{"affection": "-3", "story_phase": "stranger"}
```

---

## 四、全局底座规则（`_AFFECTION_BASE_RULES`）

所有卡通用的加减分底座，位于 `main.py`：

| 事件名 | 分值 | 说明 |
|--------|------|------|
| `deep_conversation` | +4 | 深度聊天（共情/倾诉/深度话题） |
| `light_chat` | +1 | 日常轻聊 |
| `compliment` | +2 | 夸奖/赞美 |
| `gift` | +6 | 送礼物/惊喜 |
| `help` | +3 | 主动帮助对方解决问题 |
| `shared_secret` | +5 | 分享秘密/私事 |
| `first_meeting` | +3 | 第一次打招呼 |
| `comfort` | +3 | 安慰对方情绪 |
| `flirt` | +2 | 调情/撒娇 |
| `date` | +5 | 约会/特别活动 |
| `first_hug` | +7 | 第一次拥抱（关系里程碑） |
| `kiss` | +8 | 亲吻（关系里程碑） |
| `confession` | +10 | 表白（关系里程碑，最大单次） |
| `argument` | -5 | 争吵/冲突 |
| `rude` | -3 | 粗鲁/无礼 |
| `ignore` | -2 | 漠视/敷衍 |
| `lie` | -4 | 说谎被发现 |
| `betray` | -8 | 背叛/背信弃义 |
| `insult` | -6 | 侮辱/人身攻击 |

**修改方式**：直接编辑 `main.py` 中 `_AFFECTION_BASE_RULES` 字典。

---

## 五、三防机制详解

### 5.1 冷却机制（Cooldown）

**原理**：同类事件在冷却期内再次触发，正向加分归零（不计冷却内触发次数）。

**冷却时间配置**（`_AFFECTION_COOLDOWN_SECONDS`）：

| 事件 | 冷却时间 | 设计理由 |
|------|----------|---------|
| `compliment` | 30 分钟 | 最关键，防"夸奖刷分" |
| `light_chat` | 5 分钟 | 允许正常聊天，但不能秒连 |
| `deep_conversation` | 1 小时 | 深聊不能连续触发 |
| `comfort` | 30 分钟 | |
| `flirt` | 20 分钟 | |
| `help` / `shared_secret` | 1-2 小时 | |
| `gift` | 24 小时 | 礼物每天只算一次 |
| `date` | 12 小时 | |
| `first_hug` / `kiss` / `confession` | 7 天 | 里程碑事件极其稀缺 |

**负向事件**：无冷却时间，可连续生效（惩罚要真实）。

### 5.2 单日上限（Daily Cap）

**原理**：每个用户 × 角色，每天正向好感度涨幅上限 **+15**（`_DAILY_AFFECTION_CAP`）。

- 超出上限后，当天剩余时间所有正向事件实际加分归零
- 负向事件（扣分）不受此限制
- 每天 00:00 惰性重置（下次触发时检测日期变化，自动清零）

**修改方式**：修改 `main.py` 中 `_DAILY_AFFECTION_CAP = 15`。

### 5.3 边际递减（Diminishing Returns）

**原理**：今日同类事件多次触发（冷却过后的有效触发），得分按衰减系数折减。

**衰减系数**（`_AFFECTION_DIMINISHING_RETURNS`）：

| 今日第 N 次触发 | 系数 | 示例（base=+4） |
|----------------|------|----------------|
| 第 1 次 | 100% | +4 |
| 第 2 次 | 60% | +2 |
| 第 3 次 | 30% | +1 |
| 第 4 次及以后 | 0% | +0 |

### 5.4 阶段涨幅系数

**原理**：越亲密，好感度涨得越慢（"恋人阶段再怎么聊，好感度也很难快速增加"）。

| 阶段 | 正向系数 | 负向系数 |
|------|----------|---------|
| stranger | ×1.0 | ×0.8（陌生人，受伤害小） |
| acquaintance | ×0.8 | ×1.0 |
| friend | ×0.6 | ×1.2 |
| lover | ×0.4 | ×1.5（越亲密越在意，受伤越深） |

---

## 六、阶段自动推进

好感度超过阈值时，`story_phase` 自动升级（**不自动降级**）：

| 阶段 | 触发阈值 |
|------|---------|
| stranger → acquaintance | ≥ 20 |
| acquaintance → friend | ≥ 50 |
| friend → lover | ≥ 80 |

- **只升不降**：降级需要 AI 在 delta 里显式指定 `story_phase`
- AI 显式指定 `story_phase` 优先级高于自动推进

---

## 七、角色卡自定义规则

### 7.1 配置位置

`characters` 表的 `affection_rules_json` 字段，JSON 对象格式：

```json
{
  "first_hug": 8,
  "call_nickname": 3,
  "mention_enemy": -10,
  "study_together": 2,
  "enabled": true
}
```

#### ⚠️ 覆盖（override），不是叠加（add）

角色卡同名事件直接**替换**全局底座的值，最终只生效一个分值：

```
底座 compliment = +2
角色卡 compliment = +3
最终结果 = +3（取角色卡，不是 +2+3=+5）
```

这是故意的设计：防止"双重加分"bug，也让角色卡作者可以精确控制每个事件的感情分。

#### ⚠️ 数值安全 clamp（防绕过三防）

三防机制只折减比例（×0.6 / ×0.3），如果 base_change 写得离谱大（比如 +50），折减后仍然很高。
因此 `_get_affection_rules` 会对角色卡的数值做自动 clamp：

| 场景 | 规则 |
|------|------|
| 覆盖底座已有的正向事件 | 上限 = `min(底座原值 × 2, 15)` |
| 覆盖底座已有的负向事件 | 下限 = `max(底座原值 × 2, -15)` |
| 角色卡新增事件（底座没有的） | clamp 到 `[-10, +10]` |

示例：底座 `compliment = +2`，卡里写 `compliment = +50` → 实际取 `min(50, 2×2=4, 15)` = **+4**，安全。

- 同名 key 覆盖全局底座规则（含 clamp 保护）
- 全局底座有但角色卡没有的事件保留全局值
- `"enabled": false` 可关闭该角色的整套好感度系统（scenario 卡用）

### 7.2 手动配置方式

目前需要手动通过 SQL 或 Python 脚本写入，后续可在 `card_analyze.py` 里自动从 `character_book` 词条提取。

**示例（SQLite 直接写）**：
```sql
UPDATE characters
SET affection_rules_json = '{"first_hug": 10, "pet_name": 4, "enabled": true}'
WHERE name = '陈序';
```

### 7.3 从 character_book 词条提取（未来规划）

在 `character_book` 里加一条特殊词条：
```json
{
  "comment": "[affection_rules]",
  "content": "first_hug=8\ncall_nickname=3\nmention_ex=-8\nkiss=10",
  "constant": true
}
```
`card_feature_mapper.py` 解析到这条词条，自动提取并写入 `affection_rules_json`。

---

## 八、卡类型与好感度

| card_type | 是否启用好感度 | 说明 |
|-----------|--------------|------|
| `intimate` | ✅ 默认启用 | 核心就是养成关系 |
| `scenario` | 🔶 可选（默认启用） | 在 `affection_rules_json` 里设 `"enabled": false` 关闭 |
| `world` | ❌ 强制禁用 | 知识库型，无单一 NPC，不适用亲密度 |

---

## 九、数据库字段说明

### character_states 表（新增字段）

| 字段 | 类型 | 说明 |
|------|------|------|
| `daily_event_counts` | JSON 对象 | 今日各事件有效触发次数（边际递减用） |
| `daily_affection_gained` | 整数 | 今日累计好感度涨幅（日上限用） |
| `last_event_timestamps` | JSON 对象 | 各事件上次触发的 UTC ISO 时间（冷却用） |
| `daily_reset_date` | 字符串 | 记录上次重置日期（YYYY-MM-DD，惰性重置判断） |

### characters 表（新增字段）

| 字段 | 类型 | 说明 |
|------|------|------|
| `affection_enabled` | 整数（0/1） | 是否启用好感度，默认 1；world 卡建议设 0 |
| `affection_rules_json` | JSON 字符串 | 角色卡自定义加减分规则，空时使用全局底座 |

---

## 十、API 行为说明

### GET /api/character/state

返回前端可见的状态（过滤了内部三防字段）：

```json
{
  "character_id": "xxx",
  "state": {
    "affection": 35,
    "story_phase": "acquaintance",
    "mood": "warm",
    "custom_vars": {}
  }
}
```

注意：`_daily_event_counts` / `_daily_affection_gained` 等以 `_` 开头的字段不对外暴露。

### POST /api/character/state/reset

重置状态为默认值（好感度 30 / stranger / neutral），同时清空三防计数器。

---

## 十一、后期维护说明

### 调整某个事件的分值

编辑 `main.py` 里的 `_AFFECTION_BASE_RULES` 字典即可，改后重启后端生效。

### 调整某个事件的冷却时间

编辑 `main.py` 里的 `_AFFECTION_COOLDOWN_SECONDS` 字典。

### 调整日上限

修改 `main.py` 里的 `_DAILY_AFFECTION_CAP = 15`。

### 调整边际递减系数

修改 `main.py` 里的 `_AFFECTION_DIMINISHING_RETURNS` 列表（从第 1 次到第 N 次的系数）。

### 调整阶段阈值

修改 `main.py` 里的 `_PHASE_THRESHOLDS` 字典。

### 给某个角色卡配置自定义规则

1. 直接写 SQL：
   ```sql
   UPDATE characters SET affection_rules_json = '{"event_name": score}' WHERE name = '角色名';
   ```
2. 或者在 Python 里通过 `conn.execute()` 写入。

### 禁用某张卡的好感度

方法一（推荐）：`UPDATE characters SET affection_enabled = 0 WHERE name = '角色名';`
方法二：在 `affection_rules_json` 里加 `"enabled": false`

---

## 十二、设计取舍说明

| 决策 | 方案 | 原因 |
|------|------|------|
| AI 上报事件名 vs 数字 | 事件名 | 服务端控制规则，防止 AI 自裁加 50 |
| 冷却 vs 无冷却 | 有冷却 | 防连续刷同类事件 |
| 日上限 vs 无上限 | 有上限（+15/天） | 防一天内快速满格 |
| 阶段自动推进 vs AI 控制 | 阈值自动推进 + AI 可覆盖 | 更稳定，同时保留 AI 叙事自由 |
| 降级策略 | 不自动降级 | 关系降级是大事件，应由 AI 显式判断 |
| 负向事件三防 | 负向不受保护 | 惩罚要真实，让用户感受到行为后果 |
| 角色卡规则合并策略 | 覆盖（override）而非叠加（add） | 防"双重加分"bug；底座+角色卡同名事件若叠加，进度会虚快 |
| 角色卡数值 clamp | 正向≤底座原值×2且≤15，负向≥底座原值×2且≥-15 | 防卡作者写极大值绕过三防的百分比折减 |
