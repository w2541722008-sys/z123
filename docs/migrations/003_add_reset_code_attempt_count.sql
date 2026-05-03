-- ============================================
-- 验证码安全增强：添加单码尝试计数
-- 为 password_reset_codes 表添加 attempt_count 列
-- 执行时间：2026-05-01
-- ============================================

-- 添加尝试计数列，默认 0，最大允许 5 次错误尝试
ALTER TABLE password_reset_codes
ADD COLUMN IF NOT EXISTS attempt_count int NOT NULL DEFAULT 0;

-- 为已有数据补默认值（空值安全）
UPDATE password_reset_codes SET attempt_count = 0 WHERE attempt_count IS NULL;
