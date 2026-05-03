"""add attempt_count to password_reset_codes (idempotent)

为 password_reset_codes 表添加 attempt_count 列，用于限制验证码尝试次数。
- 幂等：列已存在时跳过，不会报错
- 默认值 0，NOT NULL

Revision ID: 003_attempt_count
Revises: 002_timestamptz_jsonb
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003_attempt_count'
down_revision = '002_timestamptz_jsonb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 幂等添加 attempt_count 列
    conn = op.get_bind()
    exists = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'password_reset_codes' AND column_name = 'attempt_count'"
    )).fetchone()
    if not exists:
        op.add_column(
            'password_reset_codes',
            sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        )


def downgrade() -> None:
    op.drop_column('password_reset_codes', 'attempt_count')
