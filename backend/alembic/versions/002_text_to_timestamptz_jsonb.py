"""text columns to timestamptz / jsonb (idempotent)

将所有时间戳列从 text 改为 timestamptz，JSON 列从 text 改为 jsonb。
- 幂等：已转换的列会跳过，不会报错
- created_at / updated_at 添加 DEFAULT now()
- 空字符串时间戳转为 NULL（可空列）或 created_at（NOT NULL 列）
- 空字符串 JSON 转为 NULL（raw_card_json）或有效 JSON

Revision ID: 002_timestamptz_jsonb
Revises: 001_initial
Create Date: 2026-05-03
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '002_timestamptz_jsonb'
down_revision = '001_initial'
branch_labels = None
depends_on = None


# ================================================================
# 辅助：安全地做 text → timestamptz 转换（幂等）
# ================================================================
def _safe_alter_to_timestamptz(table, col, *, set_default_now=False, nullable=True, fill_empty_with=None):
    # 内部函数：table/col 仅从下方硬编码调用传入，不接收用户输入
    """幂等地将 text 列转为 timestamptz。如果已经是 timestamptz 则跳过。

    fill_empty_with: 空字符串时用哪个列的值填充（如 'created_at'），适用于 NOT NULL 列。
    """
    if fill_empty_with:
        empty_clause = f"UPDATE {table} SET {col} = {fill_empty_with} WHERE {col} = '';"
    else:
        empty_clause = f"UPDATE {table} SET {col} = NULL WHERE {col} = '';"
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = '{table}'
                  AND column_name = '{col}'
                  AND data_type = 'text'
            ) THEN
                -- 清理空字符串
                {empty_clause}
                -- 先 DROP DEFAULT（text 类型的 DEFAULT 无法自动转为 timestamptz）
                ALTER TABLE {table} ALTER COLUMN {col} DROP DEFAULT;
                -- 转换类型
                ALTER TABLE {table} ALTER COLUMN {col} TYPE timestamptz USING {col}::timestamptz;
            END IF;
        END
        $$;
    """)
    if set_default_now:
        op.execute(f"""
            DO $$
            BEGIN
                ALTER TABLE {table} ALTER COLUMN {col} SET DEFAULT now();
            EXCEPTION WHEN others THEN
                NULL;
            END
            $$;
        """)


def _safe_alter_to_jsonb(table, col, *, default_value="'[]'::jsonb", nullable=True):
    """幂等地将 text 列转为 jsonb。如果已经是 jsonb 则跳过。"""
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = '{table}'
                  AND column_name = '{col}'
                  AND data_type = 'text'
            ) THEN
                -- 清理空字符串（jsonb 不接受空字符串）
                UPDATE {table} SET {col} = NULL WHERE {col} = '' OR {col} IS NULL;
                -- 先 DROP DEFAULT（text 类型的 DEFAULT 无法自动转为 jsonb）
                ALTER TABLE {table} ALTER COLUMN {col} DROP DEFAULT;
                -- 转换类型
                ALTER TABLE {table} ALTER COLUMN {col} TYPE jsonb USING {col}::jsonb;
            END IF;
        END
        $$;
    """)
    if not nullable:
        op.execute(f"""
            DO $$
            BEGIN
                ALTER TABLE {table} ALTER COLUMN {col} DROP NOT NULL;
            EXCEPTION WHEN others THEN
                NULL;
            END
            $$;
        """)
    op.execute(f"""
        DO $$
        BEGIN
            ALTER TABLE {table} ALTER COLUMN {col} SET DEFAULT {default_value};
        EXCEPTION WHEN others THEN
            NULL;
        END
        $$;
    """)


def upgrade() -> None:
    """将 text 时间戳列转为 timestamptz，text JSON 列转为 jsonb。"""

    # ================================================================
    # 时间戳列转换
    # updated_at 等可能为 NOT NULL 的列：空字符串用 created_at 填充
    # plan_expires_at / expires_at / paid_at / closed_at 等可空列：空字符串设为 NULL
    # ================================================================

    # --- users ---
    _safe_alter_to_timestamptz("users", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("users", "updated_at", set_default_now=True, fill_empty_with="created_at")
    _safe_alter_to_timestamptz("users", "plan_expires_at")

    # --- auth_tokens ---
    _safe_alter_to_timestamptz("auth_tokens", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("auth_tokens", "expires_at")

    # --- password_reset_codes ---
    _safe_alter_to_timestamptz("password_reset_codes", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("password_reset_codes", "expires_at")

    # --- characters ---
    _safe_alter_to_timestamptz("characters", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("characters", "updated_at", set_default_now=True, fill_empty_with="created_at")

    # --- chat_messages ---
    _safe_alter_to_timestamptz("chat_messages", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("chat_messages", "updated_at", set_default_now=True, fill_empty_with="created_at")

    # --- chat_summaries ---
    _safe_alter_to_timestamptz("chat_summaries", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("chat_summaries", "updated_at", set_default_now=True, fill_empty_with="created_at")
    _safe_alter_to_timestamptz("chat_summaries", "last_summarized_at")

    # --- user_character_profiles ---
    _safe_alter_to_timestamptz("user_character_profiles", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("user_character_profiles", "updated_at", set_default_now=True, fill_empty_with="created_at")

    # --- character_states ---
    _safe_alter_to_timestamptz("character_states", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("character_states", "updated_at", set_default_now=True, fill_empty_with="created_at")

    # --- membership_orders ---
    _safe_alter_to_timestamptz("membership_orders", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("membership_orders", "updated_at", set_default_now=True, fill_empty_with="created_at")
    _safe_alter_to_timestamptz("membership_orders", "paid_at")
    _safe_alter_to_timestamptz("membership_orders", "expires_at")
    _safe_alter_to_timestamptz("membership_orders", "closed_at")

    # --- ai_request_logs ---
    _safe_alter_to_timestamptz("ai_request_logs", "created_at", set_default_now=True)

    # --- memory_categories ---
    _safe_alter_to_timestamptz("memory_categories", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("memory_categories", "updated_at", set_default_now=True, fill_empty_with="created_at")

    # --- character_memories ---
    _safe_alter_to_timestamptz("character_memories", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("character_memories", "updated_at", set_default_now=True, fill_empty_with="created_at")

    # --- character_storylines ---
    _safe_alter_to_timestamptz("character_storylines", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("character_storylines", "updated_at", set_default_now=True, fill_empty_with="created_at")

    # --- character_greetings ---
    _safe_alter_to_timestamptz("character_greetings", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("character_greetings", "updated_at", set_default_now=True, fill_empty_with="created_at")

    # --- character_post_rules ---
    _safe_alter_to_timestamptz("character_post_rules", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("character_post_rules", "updated_at", set_default_now=True, fill_empty_with="created_at")

    # --- story_events ---
    _safe_alter_to_timestamptz("story_events", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("story_events", "updated_at", set_default_now=True, fill_empty_with="created_at")

    # --- user_story_progress ---
    _safe_alter_to_timestamptz("user_story_progress", "created_at", set_default_now=True)
    _safe_alter_to_timestamptz("user_story_progress", "last_updated", set_default_now=True, fill_empty_with="created_at")

    # ================================================================
    # JSON 列转换
    # ================================================================

    # --- characters JSON 列 ---
    _safe_alter_to_jsonb("characters", "tags", default_value="'[]'::jsonb")
    _safe_alter_to_jsonb("characters", "affection_rules_json", default_value="'{}'::jsonb")
    _safe_alter_to_jsonb("characters", "mock_reply_style", default_value="'[]'::jsonb")
    _safe_alter_to_jsonb("characters", "runtime_cache_json", default_value="'{}'::jsonb")
    _safe_alter_to_jsonb("characters", "structured_asset_json", default_value="'{}'::jsonb")
    _safe_alter_to_jsonb("characters", "raw_card_json", default_value="NULL", nullable=True)
    _safe_alter_to_jsonb("characters", "import_diagnostics", default_value="'[]'::jsonb")

    # --- character_states JSON 列 ---
    _safe_alter_to_jsonb("character_states", "custom_vars", default_value="'{}'::jsonb")
    _safe_alter_to_jsonb("character_states", "daily_event_counts", default_value="'{}'::jsonb")
    _safe_alter_to_jsonb("character_states", "last_event_timestamps", default_value="'{}'::jsonb")

    # --- membership_orders JSON 列 ---
    _safe_alter_to_jsonb("membership_orders", "meta_json", default_value="'{}'::jsonb")


def downgrade() -> None:
    """降级：jsonb → text, timestamptz → text。注意：会丢失时区信息和 JSON 索引。"""

    # --- membership_orders JSON ---
    op.execute("""
        ALTER TABLE membership_orders
            ALTER COLUMN meta_json TYPE text USING meta_json::text,
            ALTER COLUMN meta_json SET DEFAULT '{}';
    """)

    # --- character_states JSON ---
    op.execute("""
        ALTER TABLE character_states
            ALTER COLUMN custom_vars TYPE text USING custom_vars::text,
            ALTER COLUMN custom_vars SET DEFAULT '{}',
            ALTER COLUMN daily_event_counts TYPE text USING daily_event_counts::text,
            ALTER COLUMN daily_event_counts SET DEFAULT '{}',
            ALTER COLUMN last_event_timestamps TYPE text USING last_event_timestamps::text,
            ALTER COLUMN last_event_timestamps SET DEFAULT '{}';
    """)

    # --- characters JSON ---
    op.execute("""
        ALTER TABLE characters
            ALTER COLUMN tags TYPE text USING tags::text,
            ALTER COLUMN tags SET DEFAULT '[]',
            ALTER COLUMN affection_rules_json TYPE text USING affection_rules_json::text,
            ALTER COLUMN affection_rules_json SET DEFAULT '{}',
            ALTER COLUMN mock_reply_style TYPE text USING mock_reply_style::text,
            ALTER COLUMN mock_reply_style SET DEFAULT '[]',
            ALTER COLUMN runtime_cache_json TYPE text USING runtime_cache_json::text,
            ALTER COLUMN runtime_cache_json SET DEFAULT '{}',
            ALTER COLUMN structured_asset_json TYPE text USING structured_asset_json::text,
            ALTER COLUMN structured_asset_json SET DEFAULT '{}',
            ALTER COLUMN raw_card_json TYPE text USING COALESCE(raw_card_json::text, ''),
            ALTER COLUMN raw_card_json SET DEFAULT '',
            ALTER COLUMN raw_card_json SET NOT NULL,
            ALTER COLUMN import_diagnostics TYPE text USING import_diagnostics::text,
            ALTER COLUMN import_diagnostics SET DEFAULT '[]';
    """)

    # --- 时间戳列回退（所有表） ---
    tables_timestamp_cols = [
        ("users", ["created_at", "updated_at", "plan_expires_at"]),
        ("auth_tokens", ["created_at", "expires_at"]),
        ("password_reset_codes", ["created_at", "expires_at"]),
        ("characters", ["created_at", "updated_at"]),
        ("chat_messages", ["created_at", "updated_at"]),
        ("chat_summaries", ["created_at", "updated_at", "last_summarized_at"]),
        ("user_character_profiles", ["created_at", "updated_at"]),
        ("character_states", ["created_at", "updated_at"]),
        ("membership_orders", ["created_at", "updated_at", "paid_at", "expires_at", "closed_at"]),
        ("ai_request_logs", ["created_at"]),
        ("memory_categories", ["created_at", "updated_at"]),
        ("character_memories", ["created_at", "updated_at"]),
        ("character_storylines", ["created_at", "updated_at"]),
        ("character_greetings", ["created_at", "updated_at"]),
        ("character_post_rules", ["created_at", "updated_at"]),
        ("story_events", ["created_at", "updated_at"]),
        ("user_story_progress", ["created_at", "last_updated"]),
    ]

    for table, cols in tables_timestamp_cols:
        for col in cols:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {col} TYPE text USING {col}::text"
            )
            if col in ("created_at", "updated_at"):
                op.execute(
                    f"ALTER TABLE {table} ALTER COLUMN {col} DROP DEFAULT"
                )
