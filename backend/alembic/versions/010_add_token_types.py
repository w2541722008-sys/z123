"""双 Token 模型支持：为 auth_tokens 增加 token_type / device_fingerprint / refresh_token_hash

- token_type: 'access' | 'refresh'，区分 token 类型
- device_fingerprint: 设备指纹哈希，用于绑定 refresh token 到设备
- refresh_token_hash: access token 关联的 refresh token 哈希，用于批量失效

Revision ID: 010_add_token_types
Revises: f5e37709aff83
Create Date: 2026-05-18
"""
from alembic import op

revision = "010_add_token_types"
down_revision = "5f37709aff83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE auth_tokens ADD COLUMN IF NOT EXISTS token_type TEXT NOT NULL DEFAULT 'access'"
    )
    op.execute(
        "ALTER TABLE auth_tokens ADD COLUMN IF NOT EXISTS device_fingerprint TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE auth_tokens ADD COLUMN IF NOT EXISTS refresh_token_hash TEXT NOT NULL DEFAULT ''"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_type ON auth_tokens(user_id, token_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_tokens_device ON auth_tokens(device_fingerprint)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_auth_tokens_device")
    op.execute("DROP INDEX IF EXISTS idx_auth_tokens_user_type")
    op.execute("ALTER TABLE auth_tokens DROP COLUMN IF EXISTS refresh_token_hash")
    op.execute("ALTER TABLE auth_tokens DROP COLUMN IF EXISTS device_fingerprint")
    op.execute("ALTER TABLE auth_tokens DROP COLUMN IF EXISTS token_type")
