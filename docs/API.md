# API 文档

基址：`/api`

## 认证

- **方式**: Cookie（`aifriend_session`）或 `Authorization: Bearer <token>`
- **Cookie 属性**: HttpOnly、SameSite=Strict（生产）、Secure（生产）
- **双 Token 模型**: Access Token（15 分钟）用于 API 鉴权，Refresh Token（30 天）用于续期

---

## 系统

### `GET /health`
健康检查

**响应**:
```json
{
  "status": "ok",
  "time": "2026-01-01T00:00:00+00:00"
}
```
`status` 为 `ok` 表示全部健康，`degraded` 表示部分异常。

---

## 认证 (auth)

### `POST /auth/register`
注册

**请求**:
```json
{
  "email": "user@example.com",
  "password": "password123",
  "nickname": "用户名"
}
```

### `POST /auth/login`
登录

**请求**:
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**响应**: 设置 Cookie

### `GET /auth/me`
当前用户信息（需登录）

### `POST /auth/logout`
登出（需登录）

### `POST /auth/forgot-password`
发送重置验证码

### `POST /auth/verify-code`
校验重置验证码

### `POST /auth/reset-password`
重置密码

---

## 角色 (characters)

### `GET /characters`
角色列表（按用户档位过滤）

**响应**:
```json
[
  {
    "id": 1,
    "name": "角色名",
    "avatar_url": "/api/avatar/1",
    "cover_url": "/api/cover/1",
    "subtitle": "简介",
    "tags": ["标签1", "标签2"],
    "card_type": "intimate",
    "required_plan": "guest"
  }
]
```

### `GET /character/greetings?character_id=1`
角色开场白列表（需登录）

### `GET /character/state?character_id=1`
角色状态（需登录）

**响应**:
```json
{
  "affection": 30,
  "story_phase": "stranger",
  "mood": "neutral",
  "custom_vars": {}
}
```

### `POST /character/state/reset`
重置角色状态（需登录）

---

## 聊天 (chat)

### `POST /chat/stream`
流式聊天（需登录）

**请求**:
```json
{
  "character_id": 1,
  "message": "你好"
}
```

**响应**: SSE 流
- `event: chunk` — 文本片段 `{"text": "..."}`
- `event: done` — 完成 `{"message_id": 123, "reply": "...", "character_state": {...}}`
- `event: error` — 错误

### `POST /chat/guest-stream`
游客流式聊天（无需登录）

### `POST /chat/regenerate`
重新生成回复（需登录）

### `POST /chat/continue`
继续生成（需登录）

### `GET /chat/history?character_id=1`
会话历史（需登录）

### `POST /chat/clear`
清空会话（需登录）

---

## 计费 (billing)

### `GET /billing/plans`
套餐列表

### `POST /billing/orders`
创建订单（需登录）

### `GET /billing/orders`
我的订单列表（需登录）

### `GET /billing/orders/{order_no}`
订单详情（需登录）

### `POST /billing/orders/{order_no}/cancel`
取消订单（需登录）

---

## 媒体 (media)

### `GET /avatar/{character_id}`
角色头像

### `GET /cover/{character_id}`
角色封面

### `POST /user/avatar`
上传用户头像（需登录）

### `GET /user/avatar`
获取用户头像（需登录）

---

## 管理后台 (admin)

**所有 admin 端点需要管理员权限**

### 用户管理
- `GET /admin/users` — 用户列表
- `GET /admin/users/{user_id}` — 用户详情
- `PATCH /admin/users/{user_id}` — 更新用户
- `DELETE /admin/users/{user_id}` — 删除用户
- `POST /admin/users/{user_id}/plan` — 修改用户档位

### 订单管理
- `GET /admin/orders` — 订单列表
- `GET /admin/orders/{order_id}` — 订单详情

### 角色管理
- `GET /admin/characters` — 角色列表
- `POST /admin/characters` — 创建角色
- `GET /admin/character/{id}` — 角色详情
- `POST /admin/character/{id}` — 更新角色
- `DELETE /admin/character/{id}` — 删除角色

### 角色子资源
- **记忆**: `GET/POST/PUT/DELETE /admin/character/{id}/memories`
- **记忆分类**: `GET/POST/PUT/DELETE /admin/character/{id}/memory-categories`
- **开场白**: `GET/POST/PUT/DELETE /admin/character/{id}/greetings`
- **剧情线**: `GET/POST/PUT/DELETE /admin/character/{id}/storylines`
- **后规则**: `GET/POST/PUT/DELETE /admin/character/{id}/post-rules`
- **剧情事件**: `GET/POST/PUT/DELETE /admin/character/{id}/story-events`

### 洞察
- `GET /admin/character/{id}/config-summary` — 配置摘要
- `GET /admin/character/{id}/message-preview` — Prompt 预览
- `POST /admin/character/{id}/test-keywords` — 测试关键词触发

### 仪表盘
- `GET /admin/dashboard/stats` — 统计数据
- `GET /admin/dashboard/trend` — 趋势数据
- `GET /admin/db-stats` — 数据库统计

---

## 错误码

- `400` — 参数错误
- `401` — 未登录
- `403` — 无权限
- `404` — 资源不存在
- `422` — 参数校验失败（`detail` 为列表）
- `500` — 服务器错误
