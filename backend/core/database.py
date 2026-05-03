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
from typing import Generator, Optional

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

    def __init__(self, raw_conn, pool: ThreadedConnectionPool, *, auto_commit: bool = False):
        """初始化连接包装器。

        Args:
            raw_conn: psycopg2 原始连接对象
            pool: ThreadedConnectionPool 实例，用于归还连接
            auto_commit: 是否在 __exit__ 时自动提交。默认 False（安全），
                         设为 True 时行为与旧版一致（无异常即 commit）。
        """
        self._conn = raw_conn
        self._pool = pool
        self._returned = False
        self._auto_commit = auto_commit
        self._open_cursors: list = []

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

        注意：
            返回的 cursor 会在连接归还时自动关闭，无需手动关闭。
            但如果长期持有 cursor 不归还连接，可能导致服务端资源泄漏。
        """
        self._ensure_open()
        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        self._open_cursors.append(cur)
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
        # 归还前关闭所有未关闭的 cursor，防止 PostgreSQL 服务端资源泄漏
        for cur in self._open_cursors:
            try:
                cur.close()
            except Exception:
                pass
        self._open_cursors.clear()
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
        cur = self._conn.cursor(**kwargs)
        self._open_cursors.append(cur)
        return cur

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
        """退出上下文管理器：异常时 rollback，正常时根据 auto_commit 决定行为，然后归还连接。"""
        if exc_type:
            self.rollback()
        elif self._auto_commit:
            self.commit()
        # auto_commit=False 且无异常时不自动提交，防止半完成事务被意外提交
        self.close()
        return False


def init_db_pool(database_url: str, min_conn: Optional[int] = None, max_conn: Optional[int] = None):
    global _connection_pool
    # 支持从 config 读取默认值，也支持直接传参覆盖
    if min_conn is None or max_conn is None:
        from core.config import DB_POOL_MIN_CONN, DB_POOL_MAX_CONN
        min_conn = min_conn if min_conn is not None else DB_POOL_MIN_CONN
        max_conn = max_conn if max_conn is not None else DB_POOL_MAX_CONN
    try:
        _connection_pool = ThreadedConnectionPool(
            min_conn,
            max_conn,
            database_url,
        )
        logger.info("✅ 数据库连接池初始化成功 (min=%s, max=%s)", min_conn, max_conn)
    except Exception as e:
        logger.error("❌ 数据库连接池初始化失败: %s", e)
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
def get_db() -> Generator[ConnWrapper, None, None]:
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("数据库操作失败: %s", e)
        raise
    finally:
        conn.close()


# 类型别名：供业务代码中 conn 参数标注使用，替代 conn: Any
ConnType = ConnWrapper


def get_db_dep() -> Generator[ConnType, None, None]:
    """FastAPI Depends 注入：自动获取连接并在请求结束后归还。

    用法：
        @router.get("/example")
        def example(conn: ConnType = Depends(get_db_dep)):
            ...

    注意：
        - 异常时自动 rollback
        - 归还前 rollback 未提交的事务，防止脏连接进入池
          （PostgreSQL 中 ROLLBACK 在已 commit 的事务上是 no-op，安全）
    """
    conn = get_conn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            conn.rollback()  # 安全兜底：回滚任何未提交的事务
        except Exception:
            pass
        conn.close()






