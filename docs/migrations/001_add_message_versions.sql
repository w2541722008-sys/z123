-- ============================================
-- Regenerate + Continue 功能数据库迁移
-- 为 chat_messages 表添加版本管理支持
-- 执行时间：2026-04-02
-- ============================================

-- 为 chat_messages 表添加版本管理字段
ALTER TABLE chat_messages
ADD COLUMN IF NOT EXISTS versions jsonb NOT NULL DEFAULT '[]',
ADD COLUMN IF NOT EXISTS current_version_index int NOT NULL DEFAULT 0;

-- 创建索引：加速按消息 ID 查询（regenerate/continue 会频繁使用）
CREATE INDEX IF NOT EXISTS idx_chat_messages_id_role
ON chat_messages(id, role)
WHERE role = 'assistant';

-- 添加注释
COMMENT ON COLUMN chat_messages.versions IS '所有生成的版本列表，格式：[{"content": "...", "created_at": "ISO时间"}]';
COMMENT ON COLUMN chat_messages.current_version_index IS '当前显示的版本索引（0-based），-1 表示原始版本被删除';
