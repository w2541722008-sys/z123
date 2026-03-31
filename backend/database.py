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
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# 数据库连接池（存储原始 psycopg2 连接）
_connection_pool: Optional[SimpleConnectionPool] = None


# ============================================================
# ConnWrapper：让 psycopg2 连接支持 SQLite 风格的 .execute()
# ============================================================
class ConnWrapper:
    """
    包装 psycopg2 连接，提供 SQLite 兼容接口。

    核心特性：
        - .execute(sql, params) 返回游标，可以继续 .fetchone() / .fetchall()
        - .commit() / .rollback() 直接透传给底层连接
        - .close() 把连接归还连接池（而非真正关闭）
        - 所有查询自动使用 RealDictCursor，结果支持 row["column_name"] 访问
    """

    def __init__(self, raw_conn, pool: SimpleConnectionPool):
        self._conn = raw_conn          # psycopg2 原始连接
        self._pool = pool              # 连接池引用（用于归还）

    # ---- 核心接口 ----

    def execute(self, sql: str, params=None):
        """
        执行 SQL，返回游标（RealDictCursor）。
        兼容 conn.execute(sql).fetchone() 的 SQLite 写法。
        """
        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        return cur

    def commit(self):
        """提交当前事务。"""
        self._conn.commit()

    def rollback(self):
        """回滚当前事务。"""
        self._conn.rollback()

    def close(self):
        """
        将连接归还连接池。
        注意：调用 close() 之后不应再使用此连接对象。
        """
        try:
            self._pool.putconn(self._conn)
        except Exception:
            pass

    # ---- 透传属性（兼容少量直接用 cursor() 的地方）----

    def cursor(self, **kwargs):
        """直接获取游标（用于 with conn.cursor() as cur: 写法）。"""
        if "cursor_factory" not in kwargs:
            kwargs["cursor_factory"] = RealDictCursor
        return self._conn.cursor(**kwargs)

    # ---- 连接状态透传 ----

    @property
    def closed(self):
        return self._conn.closed

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()
        return False


# ============================================================
# 连接池管理
# ============================================================

def init_db_pool(database_url: str, min_conn: int = 1, max_conn: int = 10):
    """初始化数据库连接池。应在应用启动时调用一次。"""
    global _connection_pool
    try:
        _connection_pool = SimpleConnectionPool(
            min_conn,
            max_conn,
            database_url,
        )
        logger.info("✅ 数据库连接池初始化成功")
    except Exception as e:
        logger.error(f"❌ 数据库连接池初始化失败: {e}")
        raise


def close_db_pool():
    """关闭数据库连接池。应在应用关闭时调用。"""
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None
        logger.info("数据库连接池已关闭")


def get_conn() -> ConnWrapper:
    """
    从连接池取出一条连接，包装为 ConnWrapper 后返回。

    使用完毕后必须调用 conn.close() 归还，或使用 with 语句自动归还。

    示例：
        conn = get_conn()
        try:
            row = conn.execute("SELECT 1").fetchone()
            conn.commit()
        finally:
            conn.close()

        # 或者：
        with get_conn() as conn:
            conn.execute("INSERT ...")
    """
    if _connection_pool is None:
        raise RuntimeError("数据库连接池未初始化，请先调用 init_db_pool()")
    raw = _connection_pool.getconn()
    return ConnWrapper(raw, _connection_pool)


@contextmanager
def get_db():
    """
    获取数据库连接的上下文管理器版本。
    自动提交/回滚/归还连接。

    示例：
        with get_db() as conn:
            conn.execute("INSERT ...")
        # 离开 with 块后自动 commit 并归还
    """
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


def return_conn(conn):
    """
    手动归还连接（向后兼容的辅助函数）。
    推荐改用 conn.close() 或 with 语句。
    """
    if isinstance(conn, ConnWrapper):
        conn.close()
    elif _connection_pool:
        _connection_pool.putconn(conn)


def execute_query(query: str, params: tuple = None, fetch_one: bool = False, fetch_all: bool = False):
    """执行查询的便捷辅助函数（适合一次性查询）。"""
    with get_db() as conn:
        cur = conn.execute(query, params or ())
        if fetch_one:
            return cur.fetchone()
        elif fetch_all:
            return cur.fetchall()
        return cur.rowcount
