# 后端 API 文档（当前可用）

基址：`/api`

## 系统与媒体

- `GET /health`：健康检查
- `GET /avatar/{character_id}`：角色头像
- `GET /cover/{character_id}`：角色封面
- `POST /user/avatar`：上传当前用户头像
- `GET /user/avatar`：获取当前用户头像

## 认证（auth）

- `POST /auth/register`：注册
- `POST /auth/login`：登录
- `GET /auth/me`：当前用户信息
- `POST /auth/logout`：登出
- `POST /auth/forgot-password`：发送重置验证码
- `POST /auth/verify-code`：校验重置验证码
- `POST /auth/reset-password`：重置密码

## 角色与会话（characters）

- `GET /characters`：角色列表（按用户身份/档位过滤）
- `GET /character/profile`：读取用户角色个性化资料
- `POST /character/profile`：更新用户角色个性化资料
- `GET /character/greetings`：角色开场白列表
- `GET /character/state`：角色状态
- `POST /character/state/reset`：重置角色状态
- `POST /chat/clear`：清空会话并恢复开场白
- `GET /chat/history`：会话历史

## 聊天（chat）

- `POST /chat/send`：同步聊天
- `POST /chat/stream`：登录用户流式聊天（SSE）
- `POST /chat/guest-stream`：游客流式聊天（SSE）
- `POST /chat/regenerate`：重生 AI 回复（SSE）
- `POST /chat/continue`：继续生成（SSE）

SSE 事件格式：

- `event: chunk` — 流式文本片段（`data: {"text": "..."}`）
- `event: done` — 生成完成（含 `message_id`、`reply`、`summary_enabled` 等字段）
- `event: error` — 错误事件

## 计费（billing）

- `GET /billing/plans`：套餐列表
- `POST /billing/orders`：创建订单
- `GET /billing/orders`：我的订单列表
- `GET /billing/orders/{order_no}`：订单详情
- `POST /billing/orders/{order_no}/cancel`：取消订单

## 管理后台（admin）

后台路由统一要求管理员权限。

- 用户：
  - `GET /admin/users`
  - `GET /admin/users/export`
  - `GET /admin/users/{user_id}`
  - `PATCH /admin/users/{user_id}`
  - `DELETE /admin/users/{user_id}`
  - `POST /admin/users/batch-plan`
  - `POST /admin/users/{user_id}/plan`
- 订单：
  - `GET /admin/orders`
  - `GET /admin/orders/export`
  - `GET /admin/orders/{order_id}`
- 仪表盘与审计：
  - `GET /admin/db-stats`
  - `POST /admin/db-stats/reset`
  - `GET /admin/dashboard/stats`
  - `GET /admin/dashboard/trend`
  - `GET /admin/audit-logs`
- 角色管理：
  - `GET /admin/characters`
  - `POST /admin/characters`
  - `GET /admin/character/{character_id}`
  - `POST /admin/character/{character_id}`
  - `DELETE /admin/character/{character_id}`
  - 以及 memories / greetings / storylines / post-rules / story-events / test-keywords / message-preview 等子路由

## 鉴权说明

- 需要登录的接口使用 `Authorization: Bearer <token>`
- 管理接口需要管理员身份

## 错误返回约定

- 参数校验失败：`422`（`detail` 为列表）
- 业务错误：`4xx`（`detail` 为字符串）
- 未处理异常：`500`（`detail` 为通用错误文案）
