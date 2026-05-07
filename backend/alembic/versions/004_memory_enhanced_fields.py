"""memory entries: add selective / sticky / cooldown / constant fields

为 character_memories 表增加 4 个字段，对标 SillyTavern World Info 增强：
- selective (int, 默认1): 选择性注入，1=仅关键词匹配时注入，0=始终注入（等同 constant）
- constant  (int, 默认0): 常驻注入，不需要关键词匹配，每轮都注入
- sticky    (int, 默认0): 一旦触发后持续注入的轮数（0=不持续，仅当轮）
- cooldown  (int, 默认0): 触发后冷却轮数（0=无冷却），冷却期内不再触发

Revision ID: 004_memory_enhanced
Revises: 003_reset_code_attempt
Create Date: 2026-05-04
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '004_memory_enhanced'
down_revision = '003_attempt_count'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # selective: 幂等添加
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='character_memories' AND column_name='selective'
            ) THEN
                ALTER TABLE character_memories ADD COLUMN selective int NOT NULL DEFAULT 1;
            END IF;
        END $$;
    """)

    # constant: 幂等添加
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='character_memories' AND column_name='constant'
            ) THEN
                ALTER TABLE character_memories ADD COLUMN constant int NOT NULL DEFAULT 0;
            END IF;
        END $$;
    """)

    # sticky: 幂等添加
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='character_memories' AND column_name='sticky'
            ) THEN
                ALTER TABLE character_memories ADD COLUMN sticky int NOT NULL DEFAULT 0;
            END IF;
        END $$;
    """)

    # cooldown: 幂等添加
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='character_memories' AND column_name='cooldown'
            ) THEN
                ALTER TABLE character_memories ADD COLUMN cooldown int NOT NULL DEFAULT 0;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE character_memories DROP COLUMN IF EXISTS cooldown")
    op.execute("ALTER TABLE character_memories DROP COLUMN IF EXISTS sticky")
    op.execute("ALTER TABLE character_memories DROP COLUMN IF EXISTS constant")
    op.execute("ALTER TABLE character_memories DROP COLUMN IF EXISTS selective")
