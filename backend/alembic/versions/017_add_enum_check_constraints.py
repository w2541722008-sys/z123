"""为枚举型文本字段补充 CHECK 约束。

上线前先预检非法值；如存在脏数据则迁移失败，不静默修改生产数据。

Revision ID: 016_enum_check_constraints
Revises: 015_drop_dead_columns
Create Date: 2026-06-08
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision = "016_enum_check_constraints"
down_revision = "015_drop_dead_columns"
branch_labels = None
depends_on = None


def _sql_values(values: Sequence[str]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def _raise_if_invalid(table: str, column: str, values: Sequence[str]) -> None:
    allowed = _sql_values(values)
    op.execute(
        f"""
        DO $$
        DECLARE
          bad_values text;
        BEGIN
          SELECT string_agg(DISTINCT {column}, ', ')
            INTO bad_values
            FROM {table}
           WHERE {column} IS NOT NULL
             AND {column} NOT IN ({allowed});

          IF bad_values IS NOT NULL THEN
            RAISE EXCEPTION
              'Cannot add CHECK constraint %.%: invalid values: %',
              '{table}', '{column}', bad_values;
          END IF;
        END $$;
        """
    )


def _add_check(table: str, name: str, column: str, values: Sequence[str]) -> None:
    allowed = _sql_values(values)
    op.execute(
        f"""
        ALTER TABLE {table}
        ADD CONSTRAINT {name}
        CHECK ({column} IN ({allowed}))
        """
    )


def _drop_check(table: str, name: str) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")


def upgrade() -> None:
    checks = [
        ("characters", "ck_characters_card_type", "card_type", ("intimate", "scenario")),
        ("characters", "ck_characters_required_plan", "required_plan", ("guest", "free", "vip", "svip")),
        ("users", "ck_users_plan_type", "plan_type", ("free", "vip", "svip")),
        ("membership_orders", "ck_membership_orders_plan_type", "plan_type", ("vip", "svip")),
        ("membership_orders", "ck_membership_orders_status", "status", ("pending", "paid", "closed")),
        ("auth_tokens", "ck_auth_tokens_token_type", "token_type", ("access", "refresh")),
        ("ai_request_logs", "ck_ai_request_logs_status", "status", ("success", "fallback", "error")),
    ]
    for table, _, column, values in checks:
        _raise_if_invalid(table, column, values)
    for table, name, column, values in checks:
        _add_check(table, name, column, values)


def downgrade() -> None:
    for table, name in (
        ("ai_request_logs", "ck_ai_request_logs_status"),
        ("auth_tokens", "ck_auth_tokens_token_type"),
        ("membership_orders", "ck_membership_orders_status"),
        ("membership_orders", "ck_membership_orders_plan_type"),
        ("users", "ck_users_plan_type"),
        ("characters", "ck_characters_required_plan"),
        ("characters", "ck_characters_card_type"),
    ):
        _drop_check(table, name)
