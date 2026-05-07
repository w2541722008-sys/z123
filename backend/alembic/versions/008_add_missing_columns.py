"""补齐代码引用但数据库缺失的列

- story_events 增加 event_id TEXT NOT NULL DEFAULT ''（UUID 格式，便于外部引用）
- character_greetings 增加 comment TEXT NOT NULL DEFAULT ''（备注说明）

这两个列在代码中已被引用但缺少数据库迁移，导致线上报错。

Revision ID: 008_add_missing_columns
Revises: 007_add_trigger_custom_key
Create Date: 2026-05-06
"""
from alembic import op

# revision identifiers
revision = "008_add_missing_columns"
down_revision = "007_add_trigger_custom_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE story_events ADD COLUMN IF NOT EXISTS event_id TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE character_greetings ADD COLUMN IF NOT EXISTS comment TEXT NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE story_events DROP COLUMN IF EXISTS event_id"
    )
    op.execute(
        "ALTER TABLE character_greetings DROP COLUMN IF EXISTS comment"
    )
