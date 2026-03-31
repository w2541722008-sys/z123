-- AI男友项目完整数据库（PostgreSQL / Supabase）
-- 用途：云端正式部署时建表
-- 最后更新：2026-03-31（与代码字段完全对齐）

create extension if not exists pgcrypto;

-- ============================================
-- 用户相关表
-- ============================================

create table if not exists users (
  id         bigserial primary key,
  email      text not null unique,
  password_hash text not null,
  password_algo text not null default 'bcrypt',   -- 'bcrypt' 或 'sha256'（旧版）
  nickname   text,
  avatar_url text,
  plan_type  text not null default 'free',        -- 'free' | 'vip' | 'svip'
  plan_expires_at text,                            -- ISO 字符串，过期时间
  created_at text not null,
  updated_at text not null
);

create table if not exists auth_tokens (
  id         bigserial primary key,
  user_id    bigint not null references users(id) on delete cascade,
  token      text not null unique,
  expires_at text not null,
  created_at text not null
);

create index if not exists idx_auth_tokens_token   on auth_tokens(token);
create index if not exists idx_auth_tokens_user_id on auth_tokens(user_id);

create table if not exists password_reset_codes (
  id         bigserial primary key,
  email      text not null,
  code       text not null,
  expires_at text not null,
  used       int  not null default 0,   -- 0=未使用 1=已使用
  created_at text not null
);

create index if not exists idx_password_reset_codes_email on password_reset_codes(email);

-- ============================================
-- 角色相关表
-- ============================================

create table if not exists characters (
  id                  text primary key,
  name                text not null,
  abbr                text,                        -- 简称
  subtitle            text,
  avatar_url          text,
  cover_url           text,
  description         text,
  tags                text not null default '[]',  -- JSON 字符串
  opening_message     text,
  system_prompt       text not null default '',
  asset_type          text not null default 'hybrid',  -- 'character'|'hybrid'|'scenario'|'world'|'system'
  card_type           text not null default 'intimate', -- 'intimate'|'scenario'|'world'|'divination'
  required_plan       text not null default 'guest',   -- 'guest'|'free'|'vip'|'svip'
  is_visible          int  not null default 1,          -- 1=展示 0=隐藏
  is_public           int  not null default 1,
  home_priority       int  not null default 0,
  sort_order          int  not null default 0,
  import_locked       int  not null default 0,          -- 1=禁止覆盖导入
  affection_enabled   int  not null default 1,          -- 1=启用好感度系统
  affection_rules_json text not null default '{}',     -- 好感度规则 JSON
  mock_reply_style    text not null default '[]',       -- 降级回复风格 JSON
  runtime_cache_json  text not null default '{}',       -- 导卡时缓存的 runtime layers
  structured_asset_json text not null default '{}',     -- 结构化资产数据（包含 runtime_layers）
  raw_card_json       text not null default '',         -- 原始角色卡 JSON（用于 AI 分析）
  source_kind         text not null default 'manual',   -- 来源类型：png/json/manual
  source_path         text not null default '',         -- 来源路径
  embedded_format     text not null default 'json',     -- 嵌入格式
  import_diagnostics  text not null default '[]',       -- 导入诊断信息
  created_at          text not null,
  updated_at          text not null
);

create index if not exists idx_characters_is_visible on characters(is_visible);
create index if not exists idx_characters_sort_order on characters(sort_order);

-- ============================================
-- 聊天相关表
-- ============================================

create table if not exists chat_messages (
  id           bigserial primary key,
  user_id      bigint not null references users(id) on delete cascade,
  character_id text   not null references characters(id) on delete cascade,
  role         text   not null check (role in ('user', 'assistant', 'system')),
  content      text   not null,
  is_summarized int   not null default 0,   -- 0=未摘要 1=已摘要
  created_at   text   not null
);

create index if not exists idx_chat_messages_user_char on chat_messages(user_id, character_id);
create index if not exists idx_chat_messages_summarized on chat_messages(user_id, character_id, is_summarized);

create table if not exists chat_summaries (
  id                bigserial primary key,
  user_id           bigint not null references users(id) on delete cascade,
  character_id      text   not null references characters(id) on delete cascade,
  summary           text   not null default '',
  memory_version    int    not null default 1,
  last_message_id   bigint references chat_messages(id) on delete set null,
  last_summarized_at text,
  created_at        text   not null,
  updated_at        text   not null,
  unique(user_id, character_id)
);

-- ============================================
-- 用户角色配置 & 关系状态表
-- ============================================

create table if not exists user_character_profiles (
  id                   bigserial primary key,
  user_id              bigint not null references users(id) on delete cascade,
  character_id         text   not null references characters(id) on delete cascade,
  remark               text   not null default '',
  custom_signature     text   not null default '',
  created_at           text   not null,
  updated_at           text   not null,
  unique(user_id, character_id)
);

create table if not exists character_states (
  id                    bigserial primary key,
  user_id               bigint not null references users(id) on delete cascade,
  character_id          text   not null references characters(id) on delete cascade,
  affection             int    not null default 30,
  story_phase           text   not null default 'stranger',  -- stranger|acquaintance|friend|lover
  mood                  text   not null default 'neutral',
  custom_vars           text   not null default '{}',        -- JSON 字符串
  -- 三防机制（反刷分）计数器
  daily_event_counts    text   not null default '{}',        -- 今日各事件触发次数 JSON
  daily_affection_gained int   not null default 0,           -- 今日已获得好感度
  last_event_timestamps text   not null default '{}',        -- 各事件最后触发时间 JSON
  daily_reset_date      text   not null default '',          -- 日计数归零日期 YYYY-MM-DD
  created_at            text   not null,
  updated_at            text   not null,
  unique(user_id, character_id)
);

-- ============================================
-- 会员相关表
-- ============================================

create table if not exists membership_orders (
  id             bigserial primary key,
  order_no       text     not null unique,
  user_id        bigint   not null references users(id) on delete cascade,
  plan_type      text     not null,
  amount_cents   int      not null default 0,   -- 单位：分
  status         text     not null default 'pending',  -- pending|paid|cancelled|expired
  payment_method text,
  paid_at        text,
  expires_at     text,
  created_at     text     not null,
  updated_at     text     not null
);

create index if not exists idx_membership_orders_user_id  on membership_orders(user_id);
create index if not exists idx_membership_orders_order_no on membership_orders(order_no);

-- ============================================
-- AI 请求日志表（用于成本防护和用量统计）
-- ============================================

create table if not exists ai_request_logs (
  id                      bigserial primary key,
  user_id                 bigint references users(id) on delete set null,
  guest_ip                text   not null default '',
  character_id            text   references characters(id) on delete set null,
  endpoint                text   not null default '',
  request_chars           int    not null default 0,
  estimated_input_tokens  int    not null default 0,
  estimated_output_tokens int    not null default 0,
  total_estimated_tokens  int    not null default 0,
  used_fallback           int    not null default 0,   -- 0=真实AI 1=降级
  status                  text   not null default 'success',  -- success|error|fallback
  error_detail            text   not null default '',
  created_at              text   not null
);

create index if not exists idx_ai_request_logs_user_id    on ai_request_logs(user_id);
create index if not exists idx_ai_request_logs_guest_ip   on ai_request_logs(guest_ip);
create index if not exists idx_ai_request_logs_created_at on ai_request_logs(created_at desc);

-- ============================================
-- 角色高级配置系统表（管理后台使用）
-- ============================================

-- 记忆分类标签
create table if not exists memory_categories (
  id           bigserial primary key,
  character_id text not null references characters(id) on delete cascade,
  name         text not null,
  description  text not null default '',
  color        text not null default '#1890FF',
  sort_order   int  not null default 0,
  created_at   text not null,
  updated_at   text not null
);

create index if not exists idx_memory_categories_character on memory_categories(character_id);

-- 关键词触发的记忆条目（World Info）
create table if not exists character_memories (
  id            bigserial primary key,
  character_id  text   not null references characters(id) on delete cascade,
  category_id   bigint references memory_categories(id) on delete set null,
  keywords      text   not null,        -- 逗号分隔的关键词
  trigger_logic text   not null default 'any',  -- 'any'|'all'
  content       text   not null,
  position      text   not null default 'before',  -- 'before'|'after'
  priority      int    not null default 100,
  comment       text   not null default '',
  is_active     int    not null default 1,
  created_at    text   not null,
  updated_at    text   not null
);

create index if not exists idx_character_memories_character on character_memories(character_id);
create index if not exists idx_character_memories_active    on character_memories(character_id, is_active);

-- 剧情线（必须在 character_greetings 之前创建，因为 greetings 引用了它）
create table if not exists character_storylines (
  id           bigserial primary key,
  character_id text not null references characters(id) on delete cascade,
  name         text not null,
  description  text not null default '',
  unlock_score int  not null default 0,
  is_default   int  not null default 0,
  is_active    int  not null default 1,
  sort_order   int  not null default 0,
  created_at   text not null,
  updated_at   text not null
);

create index if not exists idx_character_storylines_character on character_storylines(character_id);

-- 多阶段开场白
create table if not exists character_greetings (
  id           bigserial primary key,
  character_id text not null references characters(id) on delete cascade,
  content      text not null,
  story_phase  text not null default 'stranger',  -- stranger|acquaintance|friend|lover
  mood         text not null default 'neutral',    -- neutral|happy|sad|angry|flirty
  storyline_id bigint references character_storylines(id) on delete set null,
  priority     int  not null default 100,
  is_active    int  not null default 1,
  use_count    int  not null default 0,
  created_at   text not null,
  updated_at   text not null
);

create index if not exists idx_character_greetings_character on character_greetings(character_id);
create index if not exists idx_character_greetings_phase     on character_greetings(character_id, story_phase, is_active);

-- 后置规则（AI 回复约束）
create table if not exists character_post_rules (
  id           bigserial primary key,
  character_id text   not null references characters(id) on delete cascade,
  name         text   not null,
  content      text   not null,
  storyline_id bigint references character_storylines(id) on delete set null,
  story_phase  text,                              -- NULL=通用，否则限定阶段
  priority     int    not null default 100,
  is_active    int    not null default 1,
  created_at   text   not null,
  updated_at   text   not null
);

create index if not exists idx_character_post_rules_character on character_post_rules(character_id, is_active);

-- 剧情事件（好感度解锁）
create table if not exists story_events (
  id                    bigserial primary key,
  character_id          text   not null references characters(id) on delete cascade,
  title                 text   not null,
  description           text   not null default '',
  trigger_score         int    not null default 0,         -- 触发所需好感度
  unlocked_memory_ids   text   not null default '',        -- 逗号分隔的记忆ID
  unlocked_greeting_ids text   not null default '',        -- 逗号分隔的开场白ID
  unlocked_storyline_id bigint references character_storylines(id) on delete set null,
  event_content         text   not null default '',
  sort_order            int    not null default 0,
  is_active             int    not null default 1,
  created_at            text   not null,
  updated_at            text   not null
);

create index if not exists idx_story_events_character on story_events(character_id, is_active);

-- 用户剧情进度
create table if not exists user_story_progress (
  id                   bigserial primary key,
  user_id              bigint not null references users(id) on delete cascade,
  character_id         text   not null references characters(id) on delete cascade,
  triggered_event_ids  text   not null default '',   -- 逗号分隔的已触发事件ID
  current_storyline_id bigint references character_storylines(id) on delete set null,
  last_updated         text   not null,
  created_at           text   not null,
  unique(user_id, character_id)
);

create index if not exists idx_user_story_progress_user on user_story_progress(user_id, character_id);

-- ============================================
-- 注意：character_greetings 引用了 character_storylines，
--       所以 character_storylines 必须在 character_greetings 之前创建。
--       上面的顺序已经正确（storylines → greetings）。
-- ============================================
