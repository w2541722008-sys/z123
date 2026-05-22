"""清理 15 个死列 — DB 中存在但代码完全不用的字段

涉及 6 张表：
- chat_messages: seq, token_count
- character_post_rules: trigger_logic, position, keywords, category_id
- character_greetings: condition_type, condition_value, sort_order
- character_memories: importance, story_phase
- story_events: effects, trigger_condition
- character_states: affection_level, trust_level

Revision ID: 015_drop_dead_columns
Revises: 014_drop_message_search
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa


revision = "015_drop_dead_columns"
down_revision = "014_drop_message_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # chat_messages
    op.drop_column("chat_messages", "seq")
    op.drop_column("chat_messages", "token_count")

    # character_post_rules
    op.drop_column("character_post_rules", "trigger_logic")
    op.drop_column("character_post_rules", "position")
    op.drop_column("character_post_rules", "keywords")
    op.drop_column("character_post_rules", "category_id")

    # character_greetings
    op.drop_column("character_greetings", "condition_type")
    op.drop_column("character_greetings", "condition_value")
    op.drop_column("character_greetings", "sort_order")

    # character_memories
    op.drop_column("character_memories", "importance")
    op.drop_column("character_memories", "story_phase")

    # story_events
    op.drop_column("story_events", "effects")
    op.drop_column("story_events", "trigger_condition")

    # character_states
    op.drop_column("character_states", "affection_level")
    op.drop_column("character_states", "trust_level")


def downgrade() -> None:
    # character_states
    op.add_column("character_states", sa.Column("affection_level", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("character_states", sa.Column("trust_level", sa.Integer(), nullable=False, server_default="0"))

    # story_events
    op.add_column("story_events", sa.Column("effects", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("story_events", sa.Column("trigger_condition", sa.Text(), nullable=True))

    # character_memories
    op.add_column("character_memories", sa.Column("importance", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("character_memories", sa.Column("story_phase", sa.Text(), nullable=True))

    # character_greetings
    op.add_column("character_greetings", sa.Column("condition_type", sa.Text(), nullable=True))
    op.add_column("character_greetings", sa.Column("condition_value", sa.Text(), nullable=True))
    op.add_column("character_greetings", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))

    # character_post_rules
    op.add_column("character_post_rules", sa.Column("trigger_logic", sa.Text(), nullable=True))
    op.add_column("character_post_rules", sa.Column("position", sa.Text(), nullable=True))
    op.add_column("character_post_rules", sa.Column("keywords", sa.Text(), nullable=True))
    op.add_column("character_post_rules", sa.Column("category_id", sa.Text(), nullable=True))

    # chat_messages
    op.add_column("chat_messages", sa.Column("seq", sa.Integer(), nullable=True))
    op.add_column("chat_messages", sa.Column("token_count", sa.Integer(), nullable=True))
