"""移除 world/divination 卡类型：将旧数据迁移到 intimate/scenario

- card_type='world' → 'scenario'
- card_type='divination' → 'intimate'
- asset_type='world' → 'hybrid'

Revision ID: 005_remove_world_divination
Revises: 004_memory_enhanced_fields
Create Date: 2026-05-04
"""
from alembic import op

# revision identifiers
revision = "005_remove_world_divination"
down_revision = "004_memory_enhanced"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # card_type 迁移
    op.execute("UPDATE characters SET card_type = 'scenario' WHERE card_type = 'world'")
    op.execute("UPDATE characters SET card_type = 'intimate' WHERE card_type = 'divination'")
    # asset_type 迁移
    op.execute("UPDATE characters SET asset_type = 'hybrid' WHERE asset_type = 'world'")


def downgrade() -> None:
    # downgrade 无法自动区分原来的 world/divination 记录，仅保留占位
    pass
