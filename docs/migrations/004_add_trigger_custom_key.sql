-- 剧情事件增加复合触发条件字段
-- trigger_custom_key: 逗号分隔的 custom_vars 键名，需全部存在且非空才触发
-- 例如 "club" 表示 custom_vars.club 必须存在且非空
-- 例如 "club,team" 表示 custom_vars.club 和 custom_vars.team 都必须存在且非空
-- 空字符串或 NULL 表示无额外条件（仅依赖好感度阈值，保持向后兼容）

ALTER TABLE story_events
ADD COLUMN IF NOT EXISTS trigger_custom_key text NOT NULL DEFAULT '';
