-- AI男友项目最小正式版数据库（PostgreSQL / Supabase）
-- 用途：云端正式部署时建表

create extension if not exists pgcrypto;

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  password_hash text not null,
  nickname text,
  avatar_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists characters (
  id text primary key,
  name text not null,
  subtitle text,
  avatar_url text,
  cover_url text,
  description text,
  tags jsonb not null default '[]'::jsonb,
  opening_message text,
  system_prompt text not null,
  is_public boolean not null default true,
  sort_order int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists chat_messages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  character_id text not null references characters(id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'system')),
  content text not null,
  seq int,
  token_count int,
  is_summarized boolean not null default false,
  created_at timestamptz not null default now()
);

create index if not exists idx_chat_messages_user_char_time
on chat_messages(user_id, character_id, created_at desc);

create index if not exists idx_chat_messages_user_char_seq
on chat_messages(user_id, character_id, seq);

create table if not exists chat_summaries (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  character_id text not null references characters(id) on delete cascade,
  summary text not null default '',
  memory_version int not null default 1,
  last_message_id uuid references chat_messages(id) on delete set null,
  last_summarized_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id, character_id)
);

create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_users_updated_at on users;
create trigger trg_users_updated_at
before update on users
for each row
execute function set_updated_at();

drop trigger if exists trg_characters_updated_at on characters;
create trigger trg_characters_updated_at
before update on characters
for each row
execute function set_updated_at();

drop trigger if exists trg_chat_summaries_updated_at on chat_summaries;
create trigger trg_chat_summaries_updated_at
before update on chat_summaries
for each row
execute function set_updated_at();
