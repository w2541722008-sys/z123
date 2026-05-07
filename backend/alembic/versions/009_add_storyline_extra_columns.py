"""character_storylines 增加 storyline_id/title/unlock_condition/stages 列

这些列已存在于线上数据库（通过 Supabase 直接添加），但缺少 alembic 迁移记录。
此次迁移补齐定义，使代码和迁移保持一致。

- storyline_id TEXT NOT NULL DEFAULT '' — 剧情线短标识（如 awakening_path）
- title TEXT NOT NULL DEFAULT '' — 剧情线显示名称
- unlock_condition TEXT — 解锁条件描述（可选）
- stages JSONB NOT NULL DEFAULT '[]' — 剧情阶段名称列表

Revision ID: 009_add_storyline_extra_columns
Revises: 008_add_missing_columns
Create Date: 2026-05-06
"""
from alembic import op

# revision identifiers
revision = "009_add_storyline_extra_columns"
down_revision = "008_add_missing_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE character_storylines ADD COLUMN IF NOT EXISTS storyline_id TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE character_storylines ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE character_storylines ADD COLUMN IF NOT EXISTS unlock_condition TEXT"
    )
    op.execute(
        "ALTER TABLE character_storylines ADD COLUMN IF NOT EXISTS stages JSONB NOT NULL DEFAULT '[]'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE character_storylines DROP COLUMN IF EXISTS stages"
    )
    op.execute(
        "ALTER TABLE character_storylines DROP COLUMN IF EXISTS unlock_condition"
    )
    op.execute(
        "ALTER TABLE character_storylines DROP COLUMN IF EXISTS title"
    )
    op.execute(
        "ALTER TABLE character_storylines DROP COLUMN IF EXISTS storyline_id"
    )
