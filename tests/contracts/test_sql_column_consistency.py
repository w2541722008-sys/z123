"""SQL 列一致性校验 — 静态扫描代码中的列引用，与 alembic 迁移定义做比对。

为什么需要这个测试？
    单元测试使用 FakeConn mock，SQL 里的列名从来不会被真正验证。
    代码引用了数据库不存在的列时，mock 测试照样通过，但线上直接 500。
    本测试静态提取所有 SQL 中的列引用，与 alembic 迁移链中定义的列做交叉验证，
    在部署门禁阶段提前拦截"代码-数据库结构不一致"的问题。

设计策略：
    - 宁可漏报（少抓），不可误报（假阳性太多会让人忽略真问题）
    - 只检查 INSERT 和 UPDATE 中的列名（确定性最高）
    - SELECT 列由于 JOIN/子查询/别名太容易误报，暂不检查
    - alembic 解析同时支持 op.execute() SQL 和 op.add_column() API
"""
import pytest
from tests.support.sql_contract import (
    ALEMBIC_DIR,
    CHECKED_TABLES,
    extract_code_column_refs,
    missing_columns_by_table,
    parse_alembic_columns,
)


class TestSQLColumnConsistency:
    """代码 SQL 列引用 vs alembic 迁移定义 一致性检查。

    如果代码中 INSERT/UPDATE 引用了某个列，但 alembic 迁移链中没有定义该列，
    说明迁移缺失，线上一定会 500。此测试在部署门禁阶段提前拦截。
    """

    @pytest.fixture(autouse=True)
    def _load_schemas(self):
        self.alembic_columns = parse_alembic_columns()
        self.code_refs = extract_code_column_refs()
        self.missing_columns = missing_columns_by_table()

    @pytest.mark.parametrize("table_name", sorted(CHECKED_TABLES))
    def test_no_missing_columns(self, table_name: str):
        """INSERT/UPDATE 引用的列必须在 alembic 迁移中有定义。"""
        missing = self.missing_columns[table_name]
        if missing:
            pytest.fail(
                f"表 {table_name} 中代码引用了但 alembic 迁移未定义的列: {missing}\n"
                f"  → 需要新建 alembic 迁移添加这些列，或从代码中移除引用\n"
                f"  → 代码 INSERT/UPDATE 引用的列: {sorted(self.code_refs.get(table_name, []))}\n"
                f"  → 迁移定义的列: {sorted(self.alembic_columns.get(table_name, []))}"
            )


def test_latest_constraint_migration_preflights_enum_values():
    """上线前的 CHECK 约束迁移必须先预检脏数据，不能静默改生产数据。"""
    migration = (
        ALEMBIC_DIR / "017_add_enum_check_constraints.py"
    ).read_text(encoding="utf-8")

    for check_name in (
        "ck_characters_card_type",
        "ck_characters_required_plan",
        "ck_users_plan_type",
        "ck_membership_orders_plan_type",
        "ck_membership_orders_status",
        "ck_auth_tokens_token_type",
        "ck_ai_request_logs_status",
    ):
        assert check_name in migration

    assert "_raise_if_invalid" in migration
    assert "SELECT" in migration
    assert "RAISE EXCEPTION" in migration
    assert "UPDATE characters SET card_type" not in migration
