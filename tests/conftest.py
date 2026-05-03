"""
测试共享配置 - 统一 Mock 基础设施与 Fixtures

设计原则：
  - 所有需要数据库/外部服务的依赖都通过 mock 隔离
  - 纯逻辑函数不使用任何 mock，直接测试
  - 每个测试文件独立可运行，不依赖执行顺序
  - 一套 FakeConn 体系，消除 _helpers.py 的重复

目录结构：
  tests/
  ├── conftest.py          ← 本文件（唯一基础设施）
  ├── unit/                纯函数单元测试（零 mock）
  ├── services/            服务层测试（轻 mock）
  ├── routers/             路由集成测试（TestClient + mock DB）
  └── contracts/           API 契约 / 安全测试
"""

import importlib
import sys
import os
import warnings
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone

import pytest


# ── 路径设置（模块级别，确保在测试收集前生效）────────────────────────
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

# 重要：BACKEND_DIR 必须在 TESTS_DIR 之前，避免 tests/ 下的目录名
# （如 services/、routers/）遮蔽 backend 中的同名包
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

# 确保 BACKEND_DIR 在 TESTS_DIR 之前
if TESTS_DIR in sys.path and BACKEND_DIR in sys.path:
    bi = sys.path.index(BACKEND_DIR)
    ti = sys.path.index(TESTS_DIR)
    if bi > ti:
        sys.path.remove(BACKEND_DIR)
        sys.path.insert(ti, BACKEND_DIR)


def pytest_configure(config):
    """pytest 初始化 hook — 路径已在模块级别设置，此处为保险再次确认。"""
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)


# ── 全局警告过滤 ────────────────────────────────────────────────────
warnings.filterwarnings(
    "ignore",
    message=r".*asyncio\.iscoroutinefunction.*inspect\.iscoroutinefunction\(\) instead",
    category=DeprecationWarning,
)

# 允许旧代码 `from conftest import ...` 继续工作
sys.modules.setdefault("conftest", sys.modules[__name__])


# ====================================================================
# 统一 FakeConn 体系 — 替代原 conftest.FakeConn + _helpers 全部类
# ====================================================================

class FakeRow(dict):
    """模拟 psycopg2 RealDictRow，支持 dict 和属性访问。"""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


class FakeQueryResult:
    """模拟查询结果对象，供 FakeSequenceConn.execute() 返回。

    用法：
        result = FakeQueryResult(one=FakeRow({"id": 1}), many=[...], rowcount=1)
        result.fetchone()  → FakeRow 或 None
        result.fetchall()  → list
        result.rowcount    → int

    commit 后调用 _invalidate()，fetchone/fetchall 将抛出 RuntimeError。
    """

    def __init__(self, *, one=None, many=None, rowcount=0):
        self._one = one
        self._many = many or []
        self.rowcount = rowcount
        self._invalidated = False

    def _invalidate(self):
        """标记游标已失效（commit 后调用）。"""
        self._invalidated = True

    def fetchone(self):
        if self._invalidated:
            raise RuntimeError(
                "Cannot fetchone after commit — cursor is closed (psycopg2 behavior). "
                "Move fetchone() before commit()."
            )
        return self._one

    def fetchall(self):
        if self._invalidated:
            raise RuntimeError(
                "Cannot fetchall after commit — cursor is closed (psycopg2 behavior). "
                "Move fetchall() before commit()."
            )
        return self._many


class FakeSequenceConn:
    """序列化 Mock 连接 — 最通用的集成测试 mock。

    execute() 依次返回预设的结果对象（FakeQueryResult / FakeRow / None 等）。
    如果结果不是 FakeQueryResult 且不支持 fetchone/fetchall，自动包装为 FakeQueryResult。

    重要：commit() 后上一个 execute 返回的游标失效（fetchone 抛 RuntimeError），
    但可以执行新的 execute 创建新游标。这模拟了 psycopg2 的真实行为：
    commit 关闭所有打开的游标，但连接本身可以继续执行新 SQL。
    """

    def __init__(self, results):
        self._results = list(results)
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self._last_cursor = None  # 最近一次 execute 返回的游标
        self._committed_cursors = set()  # 已 commit 后失效的游标集合
        self.executed = []  # 记录所有执行的 SQL

    @staticmethod
    def _wrap_result(result):
        """将各种类型的结果包装为支持 fetchone/fetchall/rowcount 的对象。"""
        if isinstance(result, FakeQueryResult):
            return result
        if isinstance(result, FakeRow):
            # FakeRow 可能有自定义 rowcount（用于 UPDATE/DELETE 返回影响行数）
            rowcount = getattr(result, 'rowcount', 1)
            return FakeQueryResult(one=result, rowcount=rowcount)
        if isinstance(result, list):
            return FakeQueryResult(many=result, rowcount=len(result))
        if result is None:
            return FakeQueryResult(one=None, rowcount=0)
        # 带有 rowcount 属性的自定义对象
        if hasattr(result, 'rowcount') and not hasattr(result, 'fetchone'):
            rowcount = result.rowcount
            return FakeQueryResult(one=None, rowcount=rowcount)
        # 其他类型直接返回（可能自身已有 fetchone/fetchall）
        return result

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if not self._results:
            raise AssertionError(f"Unexpected SQL: {sql}")
        cursor = self._wrap_result(self._results.pop(0))
        self._last_cursor = cursor
        return cursor

    def _check_cursor_valid(self, cursor):
        """检查游标是否在 commit 后已失效。"""
        if cursor is not None and cursor in self._committed_cursors:
            raise RuntimeError(
                "Cannot fetchone after commit — cursor is closed (psycopg2 behavior). "
                "Move fetchone() before commit()."
            )

    def commit(self):
        self.committed = True
        # commit 后，当前游标失效
        if self._last_cursor is not None:
            self._committed_cursors.add(self._last_cursor)
            # 使 FakeQueryResult 的 fetchone 抛异常
            if isinstance(self._last_cursor, FakeQueryResult):
                self._last_cursor._invalidate()

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class FakeCursorConn:
    """游标风格 Mock 连接。

    execute() 返回 self，fetchone() 从序列中弹出预设值。
    适用于 execute+fetchone 紧凑写法的代码。

    重要：commit() 后游标失效，fetchone() 将抛出 RuntimeError，
    但可以执行新的 execute。这模拟 psycopg2 的真实行为。
    """

    def __init__(self, one_results):
        self._one_results = list(one_results)
        self._current_one = None
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self._cursor_invalidated = False  # commit 后游标失效标记
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._current_one = self._one_results.pop(0) if self._one_results else None
        self._cursor_invalidated = False  # 新 execute 创建新游标
        return self

    def fetchone(self):
        if self._cursor_invalidated:
            raise RuntimeError(
                "Cannot fetchone after commit — cursor is closed (psycopg2 behavior). "
                "Move fetchone() before commit()."
            )
        return self._current_one

    def commit(self):
        self.committed = True
        self._cursor_invalidated = True  # commit 后游标失效

    def rollback(self):
        self.rolled_back = True
        self._cursor_invalidated = False

    def close(self):
        self.closed = True


class FakeDummyConn:
    """最简 mock 连接，用于不需要实际 DB 操作的 422/400 契约测试。"""

    def execute(self, sql, params=None):
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    @property
    def rowcount(self):
        return 0

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class FakeAuthConn:
    """admin 认证测试专用最简连接。"""

    def execute(self, sql, params=None):
        return self

    def fetchone(self):
        return None

    def close(self):
        pass


# ── 兼容旧 conftest 的 make_fake_conn ──────────────────────────────

class _LegacyFakeConn:
    """兼容旧 conftest.FakeConn 的游标风格连接。"""

    def __init__(self):
        self.executed_sql = []
        self._committed = False
        self._rolled_back = False

    def execute(self, sql, params=None):
        self.executed_sql.append((sql, params))
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    @property
    def rowcount(self):
        return 0

    def commit(self):
        self._committed = True

    def rollback(self):
        self._rolled_back = True

    def close(self):
        pass


def make_fake_conn(return_rows=None, rowcount=0):
    """创建一个预设返回值的 FakeConn（兼容旧接口）。"""
    conn = _LegacyFakeConn()
    conn._rows = return_rows or []
    conn._rowcount_val = rowcount

    def fake_fetchone():
        if conn._rows:
            row_data = conn._rows.pop(0)
            return FakeRow(row_data) if isinstance(row_data, dict) else row_data
        return None

    def fake_fetchall():
        rows = [FakeRow(r) if isinstance(r, dict) else r for r in conn._rows]
        conn._rows = []
        return rows

    conn.fetchone = fake_fetchone
    conn.fetchall = fake_fetchall
    type(conn).rowcount = property(lambda s: s._rowcount_val)

    return conn


# ====================================================================
# 断言辅助函数（原 _helpers.py）
# ====================================================================

def assert_detail_as_list(payload: dict):
    assert isinstance(payload.get("detail"), list)
    assert len(payload["detail"]) > 0


def assert_detail_as_string(payload: dict, expected: str):
    assert payload == {"detail": expected}
    assert isinstance(payload["detail"], str)


# ====================================================================
# 时间与样本数据
# ====================================================================

NOW_UTC = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)


def sample_token_hash():
    import hashlib
    return hashlib.sha256(b"test_token_xyz_123").hexdigest()


def sample_expires_soon():
    return (NOW_UTC + timedelta(days=3)).isoformat()


def sample_expires_later():
    return (NOW_UTC + timedelta(days=20)).isoformat()


def sample_user_row(**overrides):
    defaults = {
        "id": 1,
        "email": "test@example.com",
        "nickname": "测试用户",
        "plan_type": "free",
        "plan_expires_at": "",
    }
    defaults.update(overrides)
    return defaults


# ====================================================================
# Fixtures
# ====================================================================

_cached_app = None


def _load_main_app():
    """加载 FastAPI app，仅在首次调用时执行（结果缓存至会话结束）。

    关键设计：
    1. importlib.reload 期间 patch init_db_pool/close_db_pool/threading.Thread
       → main.init_db_pool 等被绑定为 MagicMock，lifespan 不会尝试连接真实数据库
    2. reload 后额外 patch check_media_health/start_order_cleanup_daemon 等
       → 避免 lifespan 执行真实的 I/O 操作（查询 DB、启动后台线程）
    3. 结果缓存，避免每个测试都重新 reload
    """
    global _cached_app
    if _cached_app is not None:
        return _cached_app

    with patch("core.database.init_db_pool"), patch("core.database.close_db_pool"), patch("threading.Thread"):
        if "main" in sys.modules:
            main_module = importlib.reload(sys.modules["main"])
        else:
            import main as main_module

    # Patch lifespan 中会执行真实 I/O 的函数（reload 后直接替换 main 模块级名称）
    main_module.check_media_health = MagicMock(return_value={"ok": True, "missing_count": 0, "samples": []})
    main_module.check_db_health = MagicMock(return_value=True)
    main_module.start_order_cleanup_daemon = MagicMock()
    main_module.validate_production_config = MagicMock(return_value=[])

    _cached_app = main_module.app
    return _cached_app


@pytest.fixture(scope="session")
def app_module():
    yield _load_main_app()


@pytest.fixture
def app_client(app_module):
    from fastapi.testclient import TestClient

    with TestClient(app_module) as client:
        yield app_module, client


@pytest.fixture
def admin_user():
    from core.auth import CurrentUser
    return CurrentUser(
        id=1,
        email="admin@example.com",
        nickname="admin",
        plan_type="vip",
        effective_plan="vip",
        is_admin=True,
    )


@pytest.fixture
def normal_user():
    from core.auth import CurrentUser
    return CurrentUser(
        id=2,
        email="user@example.com",
        nickname="user",
        plan_type="free",
        effective_plan="free",
        is_admin=False,
    )


@pytest.fixture
def vip_user():
    from core.auth import CurrentUser
    return CurrentUser(
        id=3,
        email="vip@example.com",
        nickname="vip",
        plan_type="vip",
        effective_plan="vip",
        is_admin=False,
    )


@contextmanager
def override_user(app, user):
    """临时覆盖 FastAPI 的当前用户依赖。"""
    from core.auth import get_current_user, get_optional_user, get_admin_user

    overrides = {
        get_current_user: lambda: user,
        get_optional_user: lambda: user,
    }
    if getattr(user, "is_admin", False):
        overrides[get_admin_user] = lambda: user

    original = {}
    for dep, fn in overrides.items():
        original[dep] = app.dependency_overrides.get(dep)
        app.dependency_overrides[dep] = fn
    try:
        yield
    finally:
        for dep, fn in original.items():
            if fn is None:
                app.dependency_overrides.pop(dep, None)
            else:
                app.dependency_overrides[dep] = fn


@contextmanager
def override_db(app, conn):
    """临时覆盖数据库依赖，返回指定的 FakeConn。

    get_db_dep 是 generator 依赖（yield conn + finally: conn.close()），
    覆盖时也需要用 generator，否则 FastAPI 不会执行 finally 中的 close()。
    """
    from core.database import get_db_dep

    def _fake_db_dep():
        try:
            yield conn
        finally:
            conn.close()

    original = app.dependency_overrides.get(get_db_dep)
    app.dependency_overrides[get_db_dep] = _fake_db_dep
    try:
        yield
    finally:
        if original is None:
            app.dependency_overrides.pop(get_db_dep, None)
        else:
            app.dependency_overrides[get_db_dep] = original


@pytest.fixture
def admin_client(app_client):
    """预配置管理员用户的 TestClient（app, client 二元组）。"""
    app, client = app_client
    from core.auth import CurrentUser, get_admin_user, get_current_user, get_optional_user
    _admin = CurrentUser(
        id=1, email="admin@example.com", nickname="admin",
        plan_type="vip", effective_plan="vip", is_admin=True,
    )
    saved_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: _admin
    app.dependency_overrides[get_optional_user] = lambda: _admin
    app.dependency_overrides[get_admin_user] = lambda: _admin
    yield app, client
    app.dependency_overrides = saved_overrides
