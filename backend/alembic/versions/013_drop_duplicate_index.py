"""删除重复索引 idx_chat_messages_search_user_char

011 号迁移创建的 idx_chat_messages_search_user_char 与
001 号迁移创建的 idx_chat_messages_user_char 在 (user_id, character_id) 上完全重复。
保留 001 的索引（命名风格与 idx_chat_messages_summarized、idx_chat_messages_created_at 一致）。

注意：文件名编号（013）与内部 revision ID（012）差 1，原因是 010_add_life_profile
使用了 alembic revision --autogenerate 生成的哈希 ID（5f37709aff83），后续手动迁移
从 010 重新开始计数。Alembic 按 revision ID 追踪，不受影响。

Revision ID: 012_drop_duplicate_index
Revises: 011_add_message_search
Create Date: 2026-05-18
"""
from alembic import op

revision = "012_drop_duplicate_index"
down_revision = "011_add_message_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_messages_search_user_char")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_search_user_char ON chat_messages(user_id, character_id)"
    )
