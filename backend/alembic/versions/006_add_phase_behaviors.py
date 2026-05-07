"""添加 phase_behaviors_json 字段：角色卡自定义阶段行为配置

- characters 表增加 phase_behaviors_json TEXT 列
- 运营可为每个关系阶段定制行为规则，替代硬编码的 _get_behavior_tendency

Revision ID: 006_add_phase_behaviors
Revises: 005_remove_world_divination
Create Date: 2026-05-06
"""
from alembic import op

# revision identifiers
revision = "006_add_phase_behaviors"
down_revision = "005_remove_world_divination"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE characters ADD COLUMN IF NOT EXISTS phase_behaviors_json TEXT DEFAULT NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE characters DROP COLUMN IF EXISTS phase_behaviors_json"
    )
