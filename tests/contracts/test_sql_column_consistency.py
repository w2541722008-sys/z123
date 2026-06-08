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
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
ALEMBIC_DIR = BACKEND_DIR / "alembic" / "versions"

# 确保路径存在
if not BACKEND_DIR.exists():
    BACKEND_DIR = Path(os.getcwd()) / "backend"
    ALEMBIC_DIR = BACKEND_DIR / "alembic" / "versions"


# ── 从 alembic 迁移链提取表结构 ──────────────────────────────────────

def _parse_alembic_columns() -> dict[str, set[str]]:
    """从 alembic 迁移文件中提取每个表最终拥有的列集合。

    按迁移顺序（001→最新）逐步叠加，最终得到每个表的完整列定义。
    支持三种写法：
      1. op.execute 三引号 SQL 中的 CREATE TABLE — 001 初始建表
      2. op.execute 三引号 SQL 中的 ALTER TABLE ADD COLUMN — 手写 SQL 迁移
      3. op.add_column API 调用 — SQLAlchemy API 迁移
    """
    tables: dict[str, set[str]] = {}

    migration_files = sorted(ALEMBIC_DIR.glob("*.py"))
    for mf in migration_files:
        content = mf.read_text(encoding="utf-8")

        # 1. 提取 op.execute("""...""") 中的 SQL（三引号）
        for match in re.finditer(r'op\.execute\(\s*"""(.*?)"""\s*\)', content, re.DOTALL):
            sql = match.group(1)
            _apply_sql_to_tables(tables, sql)

        # 2. 提取 op.execute("...") 单行 SQL
        for match in re.finditer(r'op\.execute\(\s*"((?:[^"\\]|\\.)*)"\s*\)', content):
            sql = match.group(1)
            _apply_sql_to_tables(tables, sql)

        # 3. 提取 op.add_column('table', sa.Column('col', ...))
        for match in re.finditer(
            r"op\.add_column\(\s*['\"](\w+)['\"],\s*sa\.Column\(\s*['\"](\w+)['\"]",
            content
        ):
            table_name = match.group(1)
            col_name = match.group(2)
            if table_name not in tables:
                tables[table_name] = set()
            tables[table_name].add(col_name)

    return tables


def _apply_sql_to_tables(tables: dict[str, set[str]], sql: str) -> None:
    """解析 SQL 语句并更新 tables 字典。"""
    # CREATE TABLE - 提取表名和列
    for m in re.finditer(r'create\s+table\s+if\s+not\s+exists\s+(\w+)\s*\((.*?)\);',
                         sql, re.DOTALL | re.IGNORECASE):
        table_name = m.group(1).strip()
        body = m.group(2)
        if table_name not in tables:
            tables[table_name] = set()
        for line in body.split('\n'):
            line = line.strip().rstrip(',')
            if not line:
                continue
            col_match = re.match(r'^(\w+)\s+\w+', line)
            if col_match:
                col_name = col_match.group(1).strip()
                if col_name.lower() not in ('primary', 'unique', 'foreign', 'check', 'constraint',
                                            'create', 'index', 'key'):
                    tables[table_name].add(col_name)

    # ALTER TABLE ADD COLUMN - 多种写法
    # 写法1: ALTER TABLE xxx ADD COLUMN IF NOT EXISTS yyy
    for m in re.finditer(r'ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+(\w+)',
                         sql, re.IGNORECASE):
        table_name = m.group(1).strip()
        col_name = m.group(2).strip()
        if table_name not in tables:
            tables[table_name] = set()
        tables[table_name].add(col_name)

    # 写法2: ALTER TABLE xxx ADD COLUMN yyy（不带 IF NOT EXISTS）
    for m in re.finditer(r'ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)', sql, re.IGNORECASE):
        table_name = m.group(1).strip()
        col_name = m.group(2).strip()
        if table_name not in tables:
            tables[table_name] = set()
        tables[table_name].add(col_name)

    # 写法3: ALTER TABLE xxx ADD yyy type（省略 COLUMN 关键字）
    for m in re.finditer(r'ALTER\s+TABLE\s+(\w+)\s+ADD\s+(\w+)\s+\w+', sql, re.IGNORECASE):
        table_name = m.group(1).strip()
        col_name = m.group(2).strip()
        # 排除 CONSTRAINT / INDEX 等非列 ADD
        if col_name.upper() not in ('CONSTRAINT', 'INDEX', 'UNIQUE', 'PRIMARY', 'FOREIGN', 'CHECK'):
            if table_name not in tables:
                tables[table_name] = set()
            tables[table_name].add(col_name)


# ── 从代码中提取 SQL 列引用 ──────────────────────────────────────────

def _extract_code_column_refs() -> dict[str, set[str]]:
    """扫描 backend/ 下所有 .py 文件中的 SQL，提取 INSERT 和 UPDATE 中的列引用。

    只检查 INSERT 和 UPDATE（确定性最高），SELECT 因 JOIN/子查询/别名太多误报暂不检查。
    """
    refs: dict[str, set[str]] = {}

    for py_file in BACKEND_DIR.rglob("*.py"):
        if ".venv" in str(py_file) or "alembic" in str(py_file):
            continue
        content = py_file.read_text(encoding="utf-8")

        # 提取三引号 SQL
        for match in re.finditer(r'"""(.*?)"""', content, re.DOTALL):
            sql = match.group(1)
            _extract_columns_from_sql(sql, refs)

        # 提取双引号 SQL
        for match in re.finditer(r'"((?:SELECT|INSERT|UPDATE)\s[^"]*)"', content, re.IGNORECASE):
            sql = match.group(1)
            _extract_columns_from_sql(sql, refs)

        # 提取单引号 SQL
        for match in re.finditer(r"'((?:SELECT|INSERT|UPDATE)\s[^']*)'", content, re.IGNORECASE):
            sql = match.group(1)
            _extract_columns_from_sql(sql, refs)

    return refs


def _extract_columns_from_sql(sql: str, refs: dict[str, set[str]]) -> None:
    """从一条 SQL 语句中提取列引用（仅 INSERT 和 UPDATE）。"""

    # INSERT INTO 表名 (列名列表) — 确定性最高
    for m in re.finditer(r'INSERT\s+INTO\s+(\w+)\s*\((.*?)\)\s*VALUES', sql, re.IGNORECASE | re.DOTALL):
        table_name = m.group(1).strip()
        columns_part = m.group(2).strip()
        if table_name not in refs:
            refs[table_name] = set()
        for col in re.findall(r'(\w+)', columns_part):
            col = col.strip()
            if col.lower() not in ('values', 'select', 'default', 'returning'):
                refs[table_name].add(col)

    # UPDATE 表名 SET 列名=...
    for m in re.finditer(r'UPDATE\s+(\w+)\s+SET\s+(.*?)(?:\s+WHERE)', sql, re.IGNORECASE | re.DOTALL):
        table_name = m.group(1).strip()
        set_part = m.group(2).strip()
        if table_name not in refs:
            refs[table_name] = set()
        for col in re.findall(r'(\w+)\s*=', set_part):
            col = col.strip()
            # 排除 now() 等函数调用和数字
            if col and not col[0].isdigit():
                refs[table_name].add(col)


# ── 只检查业务核心表 ──────────────────────────────────────────────────

CHECKED_TABLES = {
    "characters", "users", "chat_messages", "chat_summaries",
    "character_memories", "memory_categories", "character_greetings",
    "character_post_rules", "character_storylines", "story_events",
    "user_story_progress", "character_states", "user_character_profiles",
    "membership_orders", "ai_request_logs", "admin_audit_logs",
    "auth_tokens", "password_reset_codes",
}


class TestSQLColumnConsistency:
    """代码 SQL 列引用 vs alembic 迁移定义 一致性检查。

    如果代码中 INSERT/UPDATE 引用了某个列，但 alembic 迁移链中没有定义该列，
    说明迁移缺失，线上一定会 500。此测试在部署门禁阶段提前拦截。
    """

    @pytest.fixture(autouse=True)
    def _load_schemas(self):
        self.alembic_columns = _parse_alembic_columns()
        self.code_refs = _extract_code_column_refs()

    def _check_missing_columns(self, table_name: str) -> list[str]:
        """检查代码引用了但 alembic 中没有定义的列。"""
        if table_name not in self.code_refs:
            return []
        if table_name not in self.alembic_columns:
            return []

        code_cols = self.code_refs[table_name]
        db_cols = self.alembic_columns[table_name]
        missing = code_cols - db_cols
        return sorted(missing)

    @pytest.mark.parametrize("table_name", sorted(CHECKED_TABLES))
    def test_no_missing_columns(self, table_name: str):
        """INSERT/UPDATE 引用的列必须在 alembic 迁移中有定义。"""
        missing = self._check_missing_columns(table_name)
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
