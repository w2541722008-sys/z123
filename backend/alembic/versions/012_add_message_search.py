"""消息全文搜索：添加 tsvector 列和 GIN 索引

- chat_messages 新增 search_vector 列（tsvector）
- GIN 索引加速中文全文搜索
- 触发器自动维护 search_vector（INSERT/UPDATE content 时同步更新）
- 支持中文分词（使用 simple 配置 + pg_bigm 或内置分词）

Revision ID: 011_add_message_search
Revises: 010_add_token_types
Create Date: 2026-05-18
"""
from alembic import op

revision = "011_add_message_search"
down_revision = "010_add_token_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 添加 tsvector 列
    op.execute(
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS search_vector tsvector"
    )
    # 2. GIN 索引（加速全文搜索）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_search ON chat_messages USING GIN(search_vector)"
    )
    # 3. 复合索引（按用户+角色限定搜索范围时使用）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_search_user_char ON chat_messages(user_id, character_id)"
    )
    # 4. 创建触发器函数：content 变更时自动更新 search_vector
    op.execute("""
        CREATE OR REPLACE FUNCTION chat_messages_search_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('simple', COALESCE(NEW.content, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    # 5. 创建触发器
    op.execute("""
        DROP TRIGGER IF EXISTS trg_chat_messages_search ON chat_messages;
        CREATE TRIGGER trg_chat_messages_search
            BEFORE INSERT OR UPDATE OF content ON chat_messages
            FOR EACH ROW EXECUTE FUNCTION chat_messages_search_update();
    """)
    # 6. 回填现有数据的 search_vector
    op.execute(
        "UPDATE chat_messages SET search_vector = to_tsvector('simple', COALESCE(content, '')) WHERE search_vector IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_chat_messages_search ON chat_messages")
    op.execute("DROP FUNCTION IF EXISTS chat_messages_search_update()")
    op.execute("DROP INDEX IF EXISTS idx_chat_messages_search_user_char")
    op.execute("DROP INDEX IF EXISTS idx_chat_messages_search")
    op.execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS search_vector")
