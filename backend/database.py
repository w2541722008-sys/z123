"""
PostgreSQL 数据库连接和管理模块（Supabase）

兼容层说明
----------
业务代码继承自 SQLite 时代，大量使用 conn.execute() 语法。
psycopg2 的原生连接对象不支持 .execute()，需要先 cursor() 再 execute()。

解决方案：ConnWrapper
    - 包装 psycopg2 原始连接
    - 提供 SQLite 风格的 .execute() / .commit() / .rollback() / .close() 接口
    - 查询结果自动使用 RealDictCursor，支持 row["column_name"] 字典风格访问
    - 彻底屏蔽 SQLite → PostgreSQL 迁移带来的接口不兼容问题

使用方式（业务代码无需改动）：
    conn = get_conn()            # 返回 ConnWrapper
    row = conn.execute("SELECT * FROM users WHERE id = %s", (1,)).fetchone()
    conn.commit()
    conn.close()                 # 实际是归还连接池
"""
import logging
from contextlib import contextmanager
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

_connection_pool: Optional[ThreadedConnectionPool] = None


class ConnWrapper:
    """psycopg2 连接的 SQLite 风格包装器。

    将 psycopg2 原生连接包装为 SQLite 风格的 .execute() 接口，
    自动使用 RealDictCursor 返回字典风格的结果行。

    连接从 ThreadedConnectionPool 获取，close() 实际是归还连接池。
    支持上下文管理器协议（with 语句），自动 commit/rollback/close。

    使用方式：
        conn = get_conn()            # 返回 ConnWrapper
        row = conn.execute("SELECT * FROM users WHERE id = %s", (1,)).fetchone()
        conn.commit()
        conn.close()                 # 实际是归还连接池
    """

    def __init__(self, raw_conn, pool: ThreadedConnectionPool):
        """初始化连接包装器。

        Args:
            raw_conn: psycopg2 原始连接对象
            pool: ThreadedConnectionPool 实例，用于归还连接
        """
        self._conn = raw_conn
        self._pool = pool
        self._returned = False

    def _ensure_open(self):
        """检查连接是否仍然可用，已归还则抛出异常。"""
        if self._returned or self._conn is None:
            raise RuntimeError("数据库连接已归还，不能继续使用")

    def execute(self, sql: str, params=None):
        """执行 SQL 语句，返回 RealDictCursor。

        Args:
            sql: SQL 语句，使用 %s 作为参数占位符
            params: 参数元组，可选

        Returns:
            RealDictCursor，可调用 .fetchone() / .fetchall() 获取结果
        """
        self._ensure_open()
        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        return cur

    def commit(self):
        """提交当前事务。"""
        self._ensure_open()
        self._conn.commit()

    def rollback(self):
        """回滚当前事务。"""
        self._ensure_open()
        self._conn.rollback()

    def close(self):
        """归还连接到连接池（非真正关闭）。多次调用安全。"""
        if self._returned or self._conn is None:
            return
        try:
            self._pool.putconn(self._conn)
        finally:
            self._returned = True
            self._conn = None

    def cursor(self, **kwargs):
        """创建游标，默认使用 RealDictCursor。

        Args:
            **kwargs: 传递给 psycopg2 connection.cursor() 的参数

        Returns:
            psycopg2 游标对象
        """
        self._ensure_open()
        if "cursor_factory" not in kwargs:
            kwargs["cursor_factory"] = RealDictCursor
        return self._conn.cursor(**kwargs)

    @property
    def closed(self):
        """连接是否已关闭/归还。"""
        if self._returned or self._conn is None:
            return True
        return self._conn.closed

    def __enter__(self):
        """进入上下文管理器。"""
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文管理器：异常时 rollback，正常时 commit，然后归还连接。"""
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()
        return False


def init_db_pool(database_url: str, min_conn: int = 1, max_conn: int = 10):
    global _connection_pool
    try:
        _connection_pool = ThreadedConnectionPool(
            min_conn,
            max_conn,
            database_url,
        )
        logger.info("✅ 数据库连接池初始化成功")
    except Exception as e:
        logger.error(f"❌ 数据库连接池初始化失败: {e}")
        raise


def close_db_pool():
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None
        logger.info("数据库连接池已关闭")


def get_conn() -> ConnWrapper:
    if _connection_pool is None:
        raise RuntimeError("数据库连接池未初始化，请先调用 init_db_pool()")
    raw = _connection_pool.getconn()
    return ConnWrapper(raw, _connection_pool)


@contextmanager
def get_db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"数据库操作失败: {e}")
        raise
    finally:
        conn.close()






