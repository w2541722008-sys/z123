"""initial schema baseline

将 docs/supabase_schema.sql 中的完整建表语句作为初始迁移基线。
此迁移仅用于新部署环境，已有数据库应使用 alembic stamp head 标记。

Revision ID: 001_initial
Revises: 
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建所有基础表。与 docs/supabase_schema.sql 保持一致。"""
    # 用户相关表
    op.execute("""
    create table if not exists users (
      id         bigserial primary key,
      email      text not null unique,
      password_hash text not null,
      password_algo text not null default 'bcrypt',
      nickname   text,
      avatar_url text,
      plan_type  text not null default 'free',
      plan_expires_at text,
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
      used       int  not null default 0,
      created_at text not null
    );

    create index if not exists idx_password_reset_codes_email on password_reset_codes(email);
    """)

    # 角色相关表
    op.execute("""
    create table if not exists characters (
      id                  text primary key,
      name                text not null,
      abbr                text,
      subtitle            text,
      avatar_url          text,
      cover_url           text,
      description         text,
      tags                text not null default '[]',
      opening_message     text,
      system_prompt       text not null default '',
      asset_type          text not null default 'hybrid',
      card_type           text not null default 'intimate',
      required_plan       text not null default 'guest',
      is_visible          int  not null default 1,
      is_public           int  not null default 1,
      home_priority       int  not null default 0,
      sort_order          int  not null default 0,
      import_locked       int  not null default 0,
      affection_enabled   int  not null default 1,
      affection_rules_json text not null default '{}',
      mock_reply_style    text not null default '[]',
      runtime_cache_json  text not null default '{}',
      structured_asset_json text not null default '{}',
      raw_card_json       text not null default '',
      source_kind         text not null default 'manual',
      source_path         text not null default '',
      embedded_format     text not null default 'json',
      import_diagnostics  text not null default '[]',
      created_at          text not null,
      updated_at          text not null
    );

    create index if not exists idx_characters_is_visible on characters(is_visible);
    create index if not exists idx_characters_sort_order on characters(sort_order);
    """)

    # 聊天相关表
    op.execute("""
    create table if not exists chat_messages (
      id           bigserial primary key,
      user_id      bigint not null references users(id) on delete cascade,
      character_id text   not null references characters(id) on delete cascade,
      role         text   not null check (role in ('user', 'assistant', 'system')),
      content      text   not null,
      versions     jsonb  not null default '[]',
      current_version_index int not null default 0,
      is_summarized int   not null default 0,
      created_at   text   not null,
      updated_at   text   not null default ''
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
    """)

    # 用户角色配置 & 关系状态表
    op.execute("""
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
      story_phase           text   not null default 'stranger',
      mood                  text   not null default 'neutral',
      custom_vars           text   not null default '{}',
      daily_event_counts    text   not null default '{}',
      daily_affection_gained int   not null default 0,
      last_event_timestamps text   not null default '{}',
      daily_reset_date      text   not null default '',
      created_at            text   not null,
      updated_at            text   not null,
      unique(user_id, character_id)
    );
    """)

    # 会员相关表
    op.execute("""
    create table if not exists membership_orders (
      id             bigserial primary key,
      order_no       text     not null unique,
      user_id        bigint   not null references users(id) on delete cascade,
      plan_type      text     not null,
      amount_cents   int      not null default 0,
      currency       text     not null default 'CNY',
      duration_days  int      not null default 30,
      status         text     not null default 'pending',
      payment_provider text,
      provider_trade_no text,
      checkout_url   text,
      paid_at        text,
      expires_at     text,
      closed_at      text,
      meta_json      text     not null default '{}',
      created_at     text     not null,
      updated_at     text     not null
    );

    create index if not exists idx_membership_orders_user_id  on membership_orders(user_id);
    create index if not exists idx_membership_orders_order_no on membership_orders(order_no);
    """)

    # AI 请求日志表
    op.execute("""
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
      used_fallback           int    not null default 0,
      status                  text   not null default 'success',
      error_detail            text   not null default '',
      created_at              text   not null
    );

    create index if not exists idx_ai_request_logs_user_id    on ai_request_logs(user_id);
    create index if not exists idx_ai_request_logs_guest_ip   on ai_request_logs(guest_ip);
    create index if not exists idx_ai_request_logs_created_at on ai_request_logs(created_at desc);
    """)

    # 角色高级配置系统表
    op.execute("""
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

    create table if not exists character_memories (
      id            bigserial primary key,
      character_id  text   not null references characters(id) on delete cascade,
      category_id   bigint references memory_categories(id) on delete set null,
      keywords      text   not null,
      trigger_logic text   not null default 'any',
      content       text   not null,
      position      text   not null default 'before',
      priority      int    not null default 100,
      comment       text   not null default '',
      is_active     int    not null default 1,
      created_at    text   not null,
      updated_at    text   not null
    );

    create index if not exists idx_character_memories_character on character_memories(character_id);
    create index if not exists idx_character_memories_active    on character_memories(character_id, is_active);

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

    create table if not exists character_greetings (
      id           bigserial primary key,
      character_id text not null references characters(id) on delete cascade,
      content      text not null,
      story_phase  text not null default 'stranger',
      mood         text not null default 'neutral',
      storyline_id bigint references character_storylines(id) on delete set null,
      priority     int  not null default 100,
      is_active    int  not null default 1,
      use_count    int  not null default 0,
      created_at   text not null,
      updated_at   text not null
    );

    create index if not exists idx_character_greetings_character on character_greetings(character_id);
    create index if not exists idx_character_greetings_phase     on character_greetings(character_id, story_phase, is_active);

    create table if not exists character_post_rules (
      id           bigserial primary key,
      character_id text   not null references characters(id) on delete cascade,
      name         text   not null,
      content      text   not null,
      storyline_id bigint references character_storylines(id) on delete set null,
      story_phase  text,
      priority     int    not null default 100,
      is_active    int    not null default 1,
      created_at   text   not null,
      updated_at   text   not null
    );

    create index if not exists idx_character_post_rules_character on character_post_rules(character_id, is_active);

    create table if not exists story_events (
      id                    bigserial primary key,
      character_id          text   not null references characters(id) on delete cascade,
      title                 text   not null,
      description           text   not null default '',
      trigger_score         int    not null default 0,
      unlocked_memory_ids   text   not null default '',
      unlocked_greeting_ids text   not null default '',
      unlocked_storyline_id bigint references character_storylines(id) on delete set null,
      event_content         text   not null default '',
      sort_order            int    not null default 0,
      is_active             int    not null default 1,
      created_at            text   not null,
      updated_at            text   not null
    );

    create index if not exists idx_story_events_character on story_events(character_id, is_active);

    create table if not exists user_story_progress (
      id                   bigserial primary key,
      user_id              bigint not null references users(id) on delete cascade,
      character_id         text   not null references characters(id) on delete cascade,
      triggered_event_ids  text   not null default '',
      current_storyline_id bigint references character_storylines(id) on delete set null,
      last_updated         text   not null,
      created_at           text   not null,
      unique(user_id, character_id)
    );

    create index if not exists idx_user_story_progress_user on user_story_progress(user_id, character_id);

    create table if not exists admin_audit_logs (
        id          bigserial       primary key,
        operator_id     text            not null,
        operator_email  varchar(255)    not null,
        action      varchar(100)    not null,
        target_type varchar(50)     not null,
        target_id   text,
        detail      text,
        created_at  timestamptz     not null default now()
    );

    create index if not exists idx_admin_audit_logs_created on admin_audit_logs(created_at desc);
    create index if not exists idx_admin_audit_logs_action on admin_audit_logs(action);
    create index if not exists idx_admin_audit_logs_target on admin_audit_logs(target_type, target_id);
    """)

    # 增量迁移：message versions + 性能索引
    op.execute("""
    -- 001_add_message_versions 已合并到 chat_messages 建表语句中（versions / current_version_index 列）

    -- 002_add_performance_indexes
    create index if not exists idx_chat_messages_created_at on chat_messages(user_id, character_id, created_at desc);
    create index if not exists idx_character_states_user on character_states(user_id);
    create index if not exists idx_user_character_profiles_user on user_character_profiles(user_id);

    -- 003_add_reset_code_attempt_count 已迁移到独立脚本 003_add_reset_code_attempt_count.py
    """)


def downgrade() -> None:
    """降级：按依赖顺序逆序删除所有表。"""
    op.execute("""
    drop table if exists admin_audit_logs;
    drop table if exists user_story_progress;
    drop table if exists story_events;
    drop table if exists character_post_rules;
    drop table if exists character_greetings;
    drop table if exists character_storylines;
    drop table if exists character_memories;
    drop table if exists memory_categories;
    drop table if exists ai_request_logs;
    drop table if exists membership_orders;
    drop table if exists character_states;
    drop table if exists user_character_profiles;
    drop table if exists chat_summaries;
    drop table if exists chat_messages;
    drop table if exists characters;
    drop table if exists password_reset_codes;
    drop table if exists auth_tokens;
    drop table if exists users;
    """)
