"""
真实数据库集成测试

目的：
1. 验证 SQL 语句在真实数据库上能正常执行
2. 验证数据库迁移完整性
3. 验证连接池稳定性

运行条件：
- 需要真实数据库连接（测试环境或本地 Docker）
- 标记为 @pytest.mark.integration，默认跳过
- 手动运行: pytest -m integration
"""

import pytest
from core.database import get_db
from repositories.character_repository import get_character_by_id
from repositories.user_repository import find_user_by_email


@pytest.mark.integration
def test_character_repository_real_db():
    """测试角色查询（真实数据库）"""
    with get_db() as conn:
        # 假设数据库中有 ID=1 的角色
        char = get_character_by_id(conn, 1)
        assert char is not None, "角色查询失败"
        assert "id" in char, "缺少 id 字段"
        assert "name" in char, "缺少 name 字段"
        assert isinstance(char["id"], int), "id 类型错误"


@pytest.mark.integration
def test_user_repository_real_db():
    """测试用户查询（真实数据库）"""
    with get_db() as conn:
        # 查询不存在的用户应返回 None
        user = find_user_by_email(conn, "nonexistent@example.com")
        assert user is None, "不存在的用户应返回 None"


@pytest.mark.integration
def test_connection_pool_stability():
    """测试连接池稳定性（并发获取连接）"""
    connections = []
    try:
        # 连续获取 5 个连接
        for _ in range(5):
            conn = get_db().__enter__()
            connections.append(conn)
            # 简单查询验证连接可用
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1, "连接不可用"
    finally:
        # 释放所有连接
        for conn in connections:
            get_db().__exit__(None, None, None)


@pytest.mark.integration
def test_database_schema_integrity():
    """测试数据库表结构完整性"""
    with get_db() as conn:
        cursor = conn.cursor()

        # 检查核心表是否存在
        required_tables = [
            "users",
            "characters",
            "chat_messages",
            "character_greetings",
            "story_events",
            "user_character_state",
        ]

        for table in required_tables:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
                (table,),
            )
            exists = cursor.fetchone()[0]
            assert exists, f"表 {table} 不存在"

        # 检查 characters 表的关键字段
        cursor.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'characters'
        """)
        columns = {row[0]: row[1] for row in cursor.fetchall()}

        required_columns = {
            "id": "integer",
            "name": "character varying",
            "card_type": "character varying",
            "affection_enabled": "integer",
            "life_profile_json": "text",
        }

        for col, expected_type in required_columns.items():
            assert col in columns, f"characters 表缺少字段: {col}"
            actual_type = columns[col]
            # 简化类型比较（忽略长度限制）
            if expected_type.startswith("character varying"):
                assert actual_type.startswith("character varying"), \
                    f"字段 {col} 类型错误: 期望 {expected_type}，实际 {actual_type}"
            else:
                assert actual_type == expected_type, \
                    f"字段 {col} 类型错误: 期望 {expected_type}，实际 {actual_type}"
