"""SQL 辅助工具 — 安全的参数化 IN 子句构建。

统一项目中多处手动拼接 `%s` 占位符的模式，避免 SQL 注入风险。
"""

from __future__ import annotations


def in_clause(values: list, *, placeholder: str = "%s") -> tuple[str, list]:
    """构建安全的参数化 IN 子句。

    Args:
        values: IN 子句的值列表（不能为空）
        placeholder: 占位符格式，默认 `%s`（psycopg2）

    Returns:
        (placeholder_string, value_list) — 可直接用于 f-string SQL 和参数元组

    Example:
        placeholders, params = in_clause([1, 2, 3])
        # → ("%s, %s, %s", [1, 2, 3])
        sql = f"SELECT * FROM t WHERE id IN ({placeholders})"
        conn.execute(sql, tuple(params))
    """
    if not values:
        raise ValueError("in_clause requires non-empty list")
    return ", ".join([placeholder] * len(values)), list(values)
