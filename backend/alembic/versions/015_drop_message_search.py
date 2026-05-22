"""删除聊天消息全文搜索基础设施

移除 search_vector 列、GIN 索引、触发器和触发器函数。
聊天记录搜索功能已从前端和后端代码中移除，不再需要这些数据库对象。

Revision ID: 014_drop_message_search
Revises: 013_fix_affection_default
Create Date: 2026-05-22
"""
from alembic import op

revision = "014_drop_message_search"
down_revision = "013_fix_affection_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_chat_messages_search ON chat_messages")
    op.execute("DROP FUNCTION IF EXISTS chat_messages_search_update()")
    op.execute("DROP INDEX IF EXISTS idx_chat_messages_search")
    op.execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS search_vector")


def downgrade() -> None:
    op.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS search_vector tsvector")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_search ON chat_messages USING GIN(search_vector)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION chat_messages_search_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('simple', COALESCE(NEW.content, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_chat_messages_search
            BEFORE INSERT OR UPDATE OF content ON chat_messages
            FOR EACH ROW EXECUTE FUNCTION chat_messages_search_update()
        """
    )
    op.execute(
        "UPDATE chat_messages SET search_vector = to_tsvector('simple', COALESCE(content, '')) WHERE search_vector IS NULL"
    )
