# AI男友项目后端接口说明

基址：`http://127.0.0.1:8000/api`

---

## 接口列表

### 0. 用户头像
**`POST /api/user/avatar`**
- 上传/更换当前登录用户的头像
- 请求头：`Authorization: Bearer <token>`
- 请求体：`multipart/form-data`，字段名 `file`
- 安全措施：
  - MIME 白名单：仅允许 `image/jpeg`、`image/png`、`image/webp`
  - 文件大小限制：2MB
  - 扩名校验：`.jpg` / `.jpeg` / `.png` / `.webp`
  - UUID v4 随机文件名（防止路径遍历和猜测）
- 返回：`{ "avatar_url": "/avatars/uuid.webp" }`
- 存储路径：项目根目录 `avatars/`（通过 StaticFiles 挂载在 `/avatars`）

**`GET /api/user/avatar`**
- 获取当前登录用户的头像图片
- 请求头：`Authorization: Bearer <token>`
- 返回：用户头像图片（`FileResponse`），或默认头像 `default-avatar.png`

### 静态文件挂载

| 路径 | 说明 |
|------|------|
| `/avatars` | 用户上传头像静态目录（StaticFiles） |

### 1. 注册
**`POST /auth/register`**
- 单独注册新用户
- 请求体：`{ "email": "demo@example.com", "password": "123456", "nickname": "可选" }`
- 返回：`{ "token": "...", "user": { "id": 1, "email": "...", "nickname": "...", "plan_type": "free", "effective_plan": "free", "plan_expires_at": "" } }`

### 2. 登录
**`POST /auth/login`**
- 用户已存在时校验密码
- 请求体：`{ "email": "demo@example.com", "password": "123456" }`
- 返回：`{ "token": "...", "user": { "id": 1, "email": "...", "nickname": "...", "plan_type": "vip", "effective_plan": "vip", "plan_expires_at": "2026-04-30T..." } }`

### 3. 当前用户信息
**`GET /auth/me`**
- 请求头：`Authorization: Bearer <token>`
- 返回当前登录用户的基础信息 + 当前会员状态：
  - `plan_type`：数据库原始档位（`free / vip / svip`）
  - `effective_plan`：按到期时间计算后的当前生效档位
  - `plan_expires_at`：会员到期时间
  - `plan_display_name`：中文档位名

### 4. 登出
**`POST /auth/logout`**
- 请求头：`Authorization: Bearer <token>`

> Token 为随机 Bearer Token，服务端只存 SHA-256 哈希；默认 30 天过期。

### 5. 忘记密码
**`POST /auth/forgot-password`**
- 发送密码重置验证码邮件
- 为避免泄露“邮箱是否注册”，接口会尽量返回统一成功提示
- 同一来源短时间高频请求会返回 `429`

**`POST /auth/verify-code`**
- 校验验证码是否可用

**`POST /auth/reset-password`**
- 使用验证码重置密码

### 6. 角色列表
**`GET /characters`**
- 游客也可访问（无 token 时不叠加用户个性化数据）
- 只返回 `is_visible=1` 的角色
- 同时会按当前访问者档位过滤 `required_plan`，例如游客看不到 VIP / SVIP 专属角色
- 每个角色条目包含：
  - `card_type`：`intimate / scenario / world`（产品层手动标注，决定前台分区）
  - `display_name` / `sign`：已叠加用户私有备注/签名的展示层字段
  - `required_plan` / `required_plan_label`：访问该角色所需的最低档位
  - `avatar_url` / `cover_url`：前端可直接访问的图片接口地址

### 7. 角色个性化资料
**`GET /character/profile?character_id=xxx`**
- 请求头：`Authorization: Bearer <token>`
- 返回结构：
  ```json
  {
    "character": { "id": "xxx", "display_name": "阿沉", "sign": "今晚早点睡" },
    "remark": "阿沉",
    "custom_signature": "今晚早点睡"
  }
  ```

**`POST /character/profile`**
- 请求体：`{ "character_id": "xxx", "remark": "昵称", "custom_signature": "签名" }`
- 不修改角色原始数据，只改用户私有覆盖层
- 返回最新 `character` 对象，前端可直接刷新顶部名称和签名

### 8. 聊天历史
**`GET /chat/history?character_id=xxx`**
- 请求头：`Authorization: Bearer <token>`
- 首次进入角色时自动写入开场白
- 返回：`{ "character": {...}, "messages": [{role, content, created_at}] }`

### 9. 清空聊天
**`POST /chat/clear`**
- 请求体：`{ "character_id": "xxx" }` 或 `{ "character_id": "xxx", "greeting_index": 2 }`
- 清空消息 + 摘要记忆，重新写入开场白
- `greeting_index`（可选）：
  - `0 / -1` = 默认开场白
  - 其他值优先按后台开场白 ID 选择

### 10. 角色开场白列表
**`GET /character/greetings?character_id=xxx`**
- 请求头：`Authorization: Bearer <token>`
- 优先读取后台 `character_greetings` 中启用的开场白；若后台未配置，则回退到角色卡里的 `alternate_greetings`
- 返回：
  ```json
  {
    "first_mes": "默认开场内容",
    "alternate_greetings": ["备选1", "备选2"],
    "greetings": [
      { "index": 0, "label": "默认开场", "preview": "前100字...", "content": "完整内容" },
      { "index": 12, "label": "职业线", "preview": "...", "content": "完整内容" }
    ],
    "total": 2
  }
  ```
- 用途：前端 GreetingSelect 弹窗选择剧情线

### 11. 角色状态查询
**`GET /character/state?character_id=xxx`**
- 请求头：`Authorization: Bearer <token>`
- 返回当前用户与该角色的运行时状态
- 返回：
  ```json
  {
    "state": {
      "affection": 42,
      "story_phase": "friend",
      "mood": "warm",
      "custom_vars": {}
    }
  }
  ```

### 12. 角色状态重置
**`POST /character/state/reset`**
- 请求头：`Authorization: Bearer <token>`
- 请求体：`{ "character_id": "xxx" }`
- 将当前用户与该角色的状态重置为初始值（affection=30, story_phase='stranger', mood='neutral', custom_vars={}）

### 13. 发送消息（普通）
**`POST /chat/send`**
- 请求体：`{ "character_id": "xxx", "message": "今天好累" }`
- 返回：`{ "reply": "...", "history_count": 3, "summary_enabled": true }`
- 后端流程：先预估本轮 token 预算并校验额度 → 通过后再落用户消息 → 生成回复 → 落 AI 回复
- 已加基础限流：同一已登录用户短时间内高频请求会返回 `429`
- 已加每日 token 预算，超限也会返回 `429`
- 当前会按用户档位自动选择：
  - `free` → `basic` 模型策略
  - `vip` → `vip` 模型策略
  - `svip` → `svip` 模型策略
- 若用户访问了超过自己档位的角色，会返回 `403`

### 14. 发送消息（流式 SSE）
**`POST /chat/stream`**
- 返回 `text/event-stream`
- 事件格式：
  - `event: chunk`：增量文本片段
  - `event: done`：本轮完成，含完整 reply 和 fallback 标记
- 会自动过滤 `<think>...</think>` 内容

### 15. 游客试聊（流式）
**`POST /chat/guest-stream`**
- 无需登录
- 不写数据库
- 前端只展示游客体验额度；真正生效的是后端的游客额度判断
- 后端也有一层基础 IP 限流，避免被高频刷接口
- 后端当前主要限制游客每日 token 预算
- 游客统一走 `basic` 模型策略
- 若角色被标记为 `free / vip / svip` 才能访问，游客会收到 `403`

### 15.1 游客体验额度状态
**`GET /chat/guest-quota`**
- 无需登录
- 返回游客当前体验额度状态，供前端顶部轻提示使用
- 返回示例：
  ```json
  {
    "guest": true,
    "status_text": "额度充足",
    "remaining_percent": 68,
    "used_tokens": 12800,
    "remaining_tokens": 27200,
    "token_limit": 40000
  }
  ```

### 15.2 重新生成 AI 回复
**`POST /chat/regenerate`**
- 需要登录（Bearer Token）
- 请求体：`{ "message_id": "uuid" }`
- 返回 `text/event-stream`（SSE 流式）
- **功能**：基于用户最新消息，重新生成 AI 回复，**替换**原 AI 消息内容
- **上下文构建**：
  - 获取目标消息之前的所有历史消息（按 `created_at ASC, id ASC` 时间排序）
  - 自动裁剪末尾连续的 assistant 消息（防止 continue 后的残留影响上下文）
  - 使用与 `/chat/stream` 相同的 Prompt 组装逻辑
- **SSE 事件格式**：
  ```
  event: chunk → {"type":"chunk","text":"片段"}
  event: done  → {"type":"done","reply":"完整替换内容","message_id":"uuid","operation":"regenerate","character_state":{...}}
  event: error → {"type":"error","message":"错误描述"}
  ```
- **数据库更新**：流式完成后，更新 `chat_messages.content` 为新内容；`versions` 字段只保留最终版本
- **权限校验**：message_id 必须属于当前用户且 role=assistant

### 15.3 继续生成（追加内容）
**`POST /chat/continue`**
- 需要登录（Bearer Token）
- 请求体：`{ "message_id": "uuid" }`
- 返回 `text/event-stream`（SSE 流式）
- **功能**：在原 AI 回复基础上**追加**新内容（AI 会收到"请继续"指令）
- **上下文构建**：与 regenerate 类似，但 Prompt 中额外注入"【请继续】"指令
- **SSE 事件格式**：
  ```
  event: chunk → {"type":"chunk","text":"片段"}
  event: done  → {"type":"done","reply":"原始+追加完整内容","appended_text":"仅新增部分","message_id":"uuid","operation":"continue","character_state":{...}}
  event: error → {"type":"error","message":"错误描述"}
  ```
- **关键字段说明**：
  - `reply`：拼接后的完整内容（用于保存到数据库）
  - `appended_text`：仅新增的部分（前端用于渲染独立的新气泡）
- **数据库更新**：`content` 更新为拼接后的完整内容；`versions` 只保留最终版本

### 16. 会员套餐列表
**`GET /billing/plans`**
- 返回当前可售卖的套餐列表
- 当前内置：`vip / svip`

### 17. 创建会员订单
**`POST /billing/orders`**
- 请求头：`Authorization: Bearer <token>`
- 请求体：`{ "plan_type": "vip" }`
- 说明：当前先创建订单预留记录，真实支付回调尚未接入

### 18. 我的会员订单列表
**`GET /billing/orders`**
- 请求头：`Authorization: Bearer <token>`
- 返回当前用户自己的订单列表

### 19. 单个会员订单详情
**`GET /billing/orders/{order_no}`**
- 请求头：`Authorization: Bearer <token>`
- 查看当前用户某一笔订单的详细状态

### 20. 取消订单
**`POST /billing/orders/{order_no}/cancel`**
- 请求头：`Authorization: Bearer <token>`
- 取消指定订单

---

## 调试接口（仅开发环境）

### `GET /debug/cards`
查看全部导入卡的卡型识别和层填充情况。
- 返回字段：`asset_type / source_kind / source_path / diagnostics / layer_presence / missing_layers`

### `GET /debug/card?character_id=xxx`
查看某张卡的完整调试信息：`character / runtime_layers / structured_asset / raw_card`

### `GET /debug/message-preview?character_id=xxx`
预览某张卡最终发给模型的完整 messages，包含宏替换后的内容。
- 返回：`character / memory_summary / preview.messages / preview.runtime_layers`
- 用途：调试层顺序、检查宏替换是否生效、确认 post_history 位置

---

## 管理后台相关接口（常用）

### `GET /admin/character/{character_id}/config-summary`
- 返回角色配置完整度、警告项、启用中的记忆/开场白/剧情线/事件数量
- 用途：快速判断这张卡是否已经适合上线给用户

### `GET /admin/character/{character_id}/message-preview`
- 返回后台视角下的 Prompt 预览结果
- 用途：排查“为什么这张角色卡说话不对 / 记忆没接上 / 规则没生效”

---

## 核心机制说明

### Prompt 分层注入顺序（v1.5，对齐 SillyTavern）

```
1. 主系统规则 primary_system_prompt
2. 关联资产列表（若有）
3. 角色底稿 base_profile
4. 性格与表达风格 personality
5. 当前关系/剧情场景 scenario
6. 世界规则/补充设定 world_rules
7. 示例对话 examples
8. 备用开场片段（前2条）
9. 长期记忆摘要
10. 最近 N 条历史消息（含 depth_prompt 深度插入）
11. 回复前最后约束 post_history_rules   ← 夹在历史末尾和用户消息之间
12. 当前用户消息
```

> **注意**：post_history_rules 在用户消息之前（不是之后），这是 ST 的标准注入位置。

### 宏变量替换（v1.5 新增）
角色卡里的 `{{char}}` 替换为角色真实名字，`{{user}}` 替换为当前用户昵称。
在 `prompt_assembler._expand_bundle_macros()` 中统一处理，不影响数据库中的原始卡内容。

### 导卡流程（手动三步）
- `init_db()` 只做表结构初始化，**不自动扫描任何目录**
- `backend/cli/card_import.py`：手动指定 PNG，一次性解析并写库（技术字段）
- `backend/cli/card_analyze.py`：AI 分析填充展示字段（subtitle/tags/opening_message），设 `import_locked=1`
- 详见 `docs/CHARACTER_IMPORT_SOP.md`

### 长期记忆
- 触发条件：未压缩消息数 ≥ 24
- 压缩范围：除最近 12 条外的旧消息
- 结构：`[用户画像] / [用户偏好] / [近期事件] / [关系状态] / [待跟进事项]`
- 失败兜底：规则化 fallback 摘要，不阻断聊天主流程

### Regenerate/Continue 上下文构建（重要）
- **UUID v4 排序问题**：数据库主键使用 UUID v4，UUID 的字典序 ≠ 时间序。因此 regenerate/continue 获取历史消息时**必须使用 `ORDER BY created_at ASC, id ASC`** 而非 `WHERE id < message_id ORDER BY id ASC`
- **尾部裁剪**：获取历史后，会自动移除末尾连续的 assistant 消息（continue 操作可能产生连续 AI 回复，需避免影响上下文）
- **反向查找**：前端更新 history 数组时，必须从末尾反向查找匹配 messageId（`findIndex` 总是返回第一个匹配项）

---

## AI 配置（环境变量）

| 变量名 | 必填 | 说明 |
|-------|------|------|
| `AIFRIEND_API_KEY` | ✅ | 模型接口密钥 |
| `AIFRIEND_BASE_URL` | 可选 | 默认 `https://api.minimaxi.com/v1` |
| `AIFRIEND_MODEL` | 可选 | 默认 `MiniMax-M2.5` |
| `AIFRIEND_BASIC_*` | 可选 | 游客 / 注册免费用户模型配置 |
| `AIFRIEND_VIP_*` | 可选 | VIP 模型配置 |
| `AIFRIEND_SVIP_*` | 可选 | SVIP 模型配置 |

如果分档模型未配置，会自动回退到通用 `AIFRIEND_*`。未配置 Key 时，模型调用失败，后端自动回退 mock 回复，前端链路不断。
