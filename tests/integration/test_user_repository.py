"""user_repository 集成测试 — 真实 SQL 执行验证。

运行条件：需要 DATABASE_URL 环境变量指向测试数据库。
默认不执行（@pytest.mark.integration），需 pytest -m integration 启用。

验证内容：
  - SQL 语法正确
  - %s 占位符与参数对齐
  - RETURNING id 返回正确
  - 约束触发（UNIQUE/NOT NULL）
  - COALESCE 默认值
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def _setup_user(db_conn):
    """创建测试用户，测试完回滚。"""
    db_conn.execute(
        "INSERT INTO users(email, password_hash, password_algo, nickname) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        ("integration@test.com", "hash123", "bcrypt", "集成测试"),
    )
    row = db_conn.fetchone()
    db_conn.commit()
    user_id = row["id"]
    yield user_id
    # 回滚由 db_conn fixture 处理


class TestFindUserByEmail:
    def test_found(self, db_conn, _setup_user):
        from repositories.user_repository import find_user_by_email
        result = find_user_by_email(db_conn, "integration@test.com")
        assert result is not None
        assert result["email"] == "integration@test.com"
        assert result["nickname"] == "集成测试"

    def test_not_found(self, db_conn):
        from repositories.user_repository import find_user_by_email
        result = find_user_by_email(db_conn, "nonexistent@test.com")
        assert result is None


class TestCheckEmailExists:
    def test_exists(self, db_conn, _setup_user):
        from repositories.user_repository import check_email_exists
        assert check_email_exists(db_conn, "integration@test.com") is True

    def test_not_exists(self, db_conn):
        from repositories.user_repository import check_email_exists
        assert check_email_exists(db_conn, "nobody@test.com") is False


class TestInsertUser:
    def test_returns_id(self, db_conn):
        from repositories.user_repository import insert_user
        user_id = insert_user(
            db_conn,
            email="new@test.com",
            password_hash="hash",
            password_algo="bcrypt",
            nickname="newuser",
        )
        assert user_id is not None
        assert isinstance(user_id, int)

    def test_duplicate_email_raises(self, db_conn, _setup_user):
        """UNIQUE 约束应阻止重复邮箱。"""
        from repositories.user_repository import insert_user
        import psycopg2
        with pytest.raises(psycopg2.IntegrityError):
            insert_user(
                db_conn,
                email="integration@test.com",  # 已存在
                password_hash="hash",
                password_algo="bcrypt",
                nickname="dup",
            )


class TestCoalesceDefaults:
    """验证 COALESCE 在 NULL 值时的默认值行为。"""

    def test_null_nickname_coalesces(self, db_conn):
        from repositories.user_repository import find_user_by_email
        db_conn.execute(
            "INSERT INTO users(email, password_hash, password_algo) VALUES (%s, %s, %s)",
            ("null_nick@test.com", "h", "bcrypt"),
        )
        db_conn.commit()
        result = find_user_by_email(db_conn, "null_nick@test.com")
        assert result["nickname"] == ""  # COALESCE(nickname, '') → ''

    def test_null_plan_type_coalesces(self, db_conn):
        from repositories.user_repository import find_user_by_email
        db_conn.execute(
            "INSERT INTO users(email, password_hash, password_algo) VALUES (%s, %s, %s)",
            ("null_plan@test.com", "h", "bcrypt"),
        )
        db_conn.commit()
        result = find_user_by_email(db_conn, "null_plan@test.com")
        assert result["plan_type"] == "free"  # COALESCE(plan_type, 'free') → 'free'
