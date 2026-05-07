"""add_life_profile_to_characters

Revision ID: 5f37709aff83
Revises: 009_add_storyline_extra_columns
Create Date: 2026-05-07 09:43:45.876110

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f37709aff83'
down_revision: Union[str, Sequence[str], None] = '009_add_storyline_extra_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        ALTER TABLE characters
        ADD COLUMN IF NOT EXISTS life_profile_json jsonb DEFAULT '{}'::jsonb
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE characters DROP COLUMN IF EXISTS life_profile_json")
