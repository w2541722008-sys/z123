-- ============================================================
-- 数据库索引优化脚本
-- 文件：docs/migrations/002_add_performance_indexes.sql
-- 日期：2026-04-21
-- 目的：提升查询性能的索引
-- 注意：这是添加索引，不会影响现有数据和功能
-- ============================================================

-- 1. ai_request_logs 表优化
-- 用于快速查询用户每日用量（usage_guard 模块）
CREATE INDEX IF NOT EXISTS idx_ai_request_logs_user_created
ON ai_request_logs(user_id, created_at DESC);

-- 用于快速查询游客每日用量
CREATE INDEX IF NOT EXISTS idx_ai_request_logs_guest_created
ON ai_request_logs(guest_ip, created_at DESC)
WHERE guest_ip != '';

-- 用于按状态和时间过滤错误日志
CREATE INDEX IF NOT EXISTS idx_ai_request_logs_status_created
ON ai_request_logs(status, created_at DESC)
WHERE status != 'success';

-- 2. chat_messages 表优化
-- 用于快速获取用户的最新消息（排序）
CREATE INDEX IF NOT EXISTS idx_chat_messages_user_char_created
ON chat_messages(user_id, character_id, created_at DESC);

-- 用于批量获取消息（分页查询）
CREATE INDEX IF NOT EXISTS idx_chat_messages_user_char_id
ON chat_messages(user_id, character_id, id DESC);

-- 3. character_states 表优化
-- 用于批量获取用户的所有角色状态（首页加载）
CREATE INDEX IF NOT EXISTS idx_character_states_user_id
ON character_states(user_id);

-- 4. user_character_profiles 表优化
-- 用于批量获取用户的所有角色配置（首页加载）
CREATE INDEX IF NOT EXISTS idx_user_character_profiles_user_id
ON user_character_profiles(user_id);

-- 5. auth_tokens 表优化
-- 用于清理过期 token（按时间删除）
CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires
ON auth_tokens(expires_at)
WHERE expires_at IS NOT NULL;

-- 6. membership_orders 表优化
-- 用于查询用户当前生效的会员订单
CREATE INDEX IF NOT EXISTS idx_membership_orders_user_status
ON membership_orders(user_id, status)
WHERE status IN ('paid', 'pending');

-- 7. character_greetings 表优化
-- 用于获取用户特定阶段的开场白
CREATE INDEX IF NOT EXISTS idx_character_greetings_mood
ON character_greetings(character_id, mood, is_active, priority)
WHERE is_active = 1;

-- 8. chat_summaries 表优化
-- 用于批量获取用户的记忆摘要
CREATE INDEX IF NOT EXISTS idx_chat_summaries_user_id
ON chat_summaries(user_id);

-- ============================================================
-- 分析查询（建议在创建索引后执行）
-- ============================================================
-- 在 Supabase Dashboard 或 psql 中执行：
-- ANALYZE ai_request_logs;
-- ANALYZE chat_messages;
-- ANALYZE character_states;
-- ANALYZE user_character_profiles;
-- ANALYZE auth_tokens;
-- ANALYZE membership_orders;
-- ANALYZE character_greetings;
-- ANALYZE chat_summaries;

-- ============================================================
-- 验证索引创建
-- ============================================================
-- 在 Supabase Dashboard 或 psql 中执行：
-- SELECT indexname, indexdef FROM pg_indexes WHERE tablename IN (
--   'ai_request_logs', 'chat_messages', 'character_states',
--   'user_character_profiles', 'auth_tokens', 'membership_orders',
--   'character_greetings', 'chat_summaries'
-- );
