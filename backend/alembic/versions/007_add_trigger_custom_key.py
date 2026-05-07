"""剧情事件增加复合触发条件字段 trigger_custom_key

- story_events 表增加 trigger_custom_key TEXT NOT NULL DEFAULT '' 列
- 逗号分隔的 custom_vars 键名，需全部存在且非空才触发
- 空字符串表示无额外条件（仅依赖好感度阈值，向后兼容）

Revision ID: 007_add_trigger_custom_key
Revises: 006_add_phase_behaviors
Create Date: 2026-05-06
"""
from alembic import op

# revision identifiers
revision = "007_add_trigger_custom_key"
down_revision = "006_add_phase_behaviors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE story_events ADD COLUMN IF NOT EXISTS trigger_custom_key TEXT NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE story_events DROP COLUMN IF EXISTS trigger_custom_key"
    )
