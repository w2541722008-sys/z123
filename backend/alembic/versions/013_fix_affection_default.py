"""将 character_states.affection 默认值从 30 改为 0

对应用层 get_character_state() 默认值修正，确保新建 state 行从 0 好感度开始，
而非之前错误的 30（导致陌生人阶段被完全跳过）。

Revision ID: 013_fix_affection_default
Revises: 012_drop_duplicate_index
Create Date: 2026-05-20
"""
from alembic import op

revision = "013_fix_affection_default"
down_revision = "012_drop_duplicate_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE character_states ALTER COLUMN affection SET DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE character_states ALTER COLUMN affection SET DEFAULT 30")
