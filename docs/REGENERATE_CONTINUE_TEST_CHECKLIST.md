# Regenerate / Continue 测试清单

本文档用于验证聊天重生成与续写链路在当前版本可用。

## 数据库

- [ ] `chat_messages` 包含 `versions` 字段（jsonb）
- [ ] `chat_messages` 包含 `current_version_index` 字段（int）
- [ ] `chat_messages` 包含 `updated_at` 字段（text）

## 接口行为

- [ ] `POST /api/chat/regenerate` 正常返回 SSE（`chunk/done/error`）
- [ ] `POST /api/chat/continue` 正常返回 SSE（`chunk/done/error`）
- [ ] 非法 `message_id` 返回 404
- [ ] 未登录访问返回 401/403

## 数据一致性

- [ ] regenerate 后消息 `content` 被替换
- [ ] continue 后消息 `content` 为原文 + 追加
- [ ] `versions` 保存最终版本记录

## 前端交互

- [ ] 点击 regenerate 时原气泡内容流式替换
- [ ] 点击 continue 时创建新的追加气泡
- [ ] 并发点击被正确拦截（避免重复提交）

## 回归

- [ ] 普通聊天 `/api/chat/stream` 不受影响
- [ ] 聊天历史 `/api/chat/history` 不受影响
- [ ] 前端测试 `node tests/test_frontend_utils.js` 通过

