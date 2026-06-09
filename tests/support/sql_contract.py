"""SQL contract support for schema/column consistency tests."""

from __future__ import annotations

import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
if not BACKEND_DIR.exists():
    BACKEND_DIR = Path(os.getcwd()) / "backend"

ALEMBIC_DIR = BACKEND_DIR / "alembic" / "versions"

CHECKED_TABLES = {
    "admin_audit_logs",
    "ai_request_logs",
    "auth_tokens",
    "character_greetings",
    "character_memories",
    "character_post_rules",
    "character_states",
    "character_storylines",
    "characters",
    "chat_messages",
    "chat_summaries",
    "memory_categories",
    "membership_orders",
    "password_reset_codes",
    "story_events",
    "user_character_profiles",
    "user_story_progress",
    "users",
}


def parse_alembic_columns() -> dict[str, set[str]]:
    """Return final table columns inferred from the Alembic migration chain."""
    tables: dict[str, set[str]] = {}

    for migration_file in sorted(ALEMBIC_DIR.glob("*.py")):
        content = migration_file.read_text(encoding="utf-8")

        for match in re.finditer(r'op\.execute\(\s*"""(.*?)"""\s*\)', content, re.DOTALL):
            apply_sql_to_tables(tables, match.group(1))

        for match in re.finditer(r'op\.execute\(\s*"((?:[^"\\]|\\.)*)"\s*\)', content):
            apply_sql_to_tables(tables, match.group(1))

        for match in re.finditer(
            r"op\.add_column\(\s*['\"](\w+)['\"],\s*sa\.Column\(\s*['\"](\w+)['\"]",
            content,
        ):
            table_name, column_name = match.groups()
            tables.setdefault(table_name, set()).add(column_name)

    return tables


def apply_sql_to_tables(tables: dict[str, set[str]], sql: str) -> None:
    """Update ``tables`` with CREATE/ALTER column definitions from SQL."""
    for match in re.finditer(
        r"create\s+table\s+if\s+not\s+exists\s+(\w+)\s*\((.*?)\);",
        sql,
        re.DOTALL | re.IGNORECASE,
    ):
        table_name = match.group(1).strip()
        tables.setdefault(table_name, set())
        for line in match.group(2).split("\n"):
            line = line.strip().rstrip(",")
            if not line:
                continue
            column_match = re.match(r"^(\w+)\s+\w+", line)
            if column_match:
                column_name = column_match.group(1).strip()
                if column_name.lower() not in {
                    "check",
                    "constraint",
                    "create",
                    "foreign",
                    "index",
                    "key",
                    "primary",
                    "unique",
                }:
                    tables[table_name].add(column_name)

    for match in re.finditer(
        r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+(\w+)",
        sql,
        re.IGNORECASE,
    ):
        tables.setdefault(match.group(1).strip(), set()).add(match.group(2).strip())

    for match in re.finditer(
        r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
        sql,
        re.IGNORECASE,
    ):
        tables.setdefault(match.group(1).strip(), set()).add(match.group(2).strip())

    for match in re.finditer(
        r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+(\w+)\s+\w+",
        sql,
        re.IGNORECASE,
    ):
        table_name, column_name = match.group(1).strip(), match.group(2).strip()
        if column_name.upper() not in {"CHECK", "CONSTRAINT", "FOREIGN", "INDEX", "PRIMARY", "UNIQUE"}:
            tables.setdefault(table_name, set()).add(column_name)


def extract_code_column_refs() -> dict[str, set[str]]:
    """Extract INSERT/UPDATE column references from backend Python SQL snippets."""
    refs: dict[str, set[str]] = {}

    for py_file in BACKEND_DIR.rglob("*.py"):
        if ".venv" in str(py_file) or "alembic" in str(py_file):
            continue
        content = py_file.read_text(encoding="utf-8")

        for match in re.finditer(r'"""(.*?)"""', content, re.DOTALL):
            extract_columns_from_sql(match.group(1), refs)

        for match in re.finditer(r'"((?:SELECT|INSERT|UPDATE)\s[^"]*)"', content, re.IGNORECASE):
            extract_columns_from_sql(match.group(1), refs)

        for match in re.finditer(r"'((?:SELECT|INSERT|UPDATE)\s[^']*)'", content, re.IGNORECASE):
            extract_columns_from_sql(match.group(1), refs)

    return refs


def extract_columns_from_sql(sql: str, refs: dict[str, set[str]]) -> None:
    """Extract deterministic INSERT/UPDATE column references from one SQL string."""
    for match in re.finditer(
        r"INSERT\s+INTO\s+(\w+)\s*\((.*?)\)\s*VALUES",
        sql,
        re.IGNORECASE | re.DOTALL,
    ):
        table_name = match.group(1).strip()
        refs.setdefault(table_name, set())
        for column_name in re.findall(r"(\w+)", match.group(2).strip()):
            if column_name.lower() not in {"default", "returning", "select", "values"}:
                refs[table_name].add(column_name.strip())

    for match in re.finditer(
        r"UPDATE\s+(\w+)\s+SET\s+(.*?)(?:\s+WHERE)",
        sql,
        re.IGNORECASE | re.DOTALL,
    ):
        table_name = match.group(1).strip()
        refs.setdefault(table_name, set())
        for column_name in re.findall(r"(\w+)\s*=", match.group(2).strip()):
            if column_name and not column_name[0].isdigit():
                refs[table_name].add(column_name.strip())


def missing_columns_by_table() -> dict[str, list[str]]:
    """Return code-referenced columns that are absent from migration metadata."""
    alembic_columns = parse_alembic_columns()
    code_refs = extract_code_column_refs()
    return {
        table_name: sorted(code_refs.get(table_name, set()) - alembic_columns.get(table_name, set()))
        for table_name in CHECKED_TABLES
    }
