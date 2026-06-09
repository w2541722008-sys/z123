"""Fake database primitives used by tests.

These classes intentionally model the small psycopg2 surface that the app uses:
``execute()``, ``fetchone()``, ``fetchall()``, transaction flags, and cursor
invalidation after ``commit()``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


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


class FakeRow(dict):
    """Small RealDictRow stand-in that supports dict and attribute access."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


class FakeQueryResult:
    """Query result returned by FakeSequenceConn.execute()."""

    def __init__(self, rows=None, *, one=None, many=None, rowcount=0):
        if rows is not None:
            self._one = None
            self._many = rows
        else:
            self._one = one
            self._many = many or []
        self.rowcount = rowcount
        self._invalidated = False

    def _invalidate(self):
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
    """Connection fake that returns queued query results in execution order."""

    def __init__(self, results):
        self._results = list(results)
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self._last_cursor = None
        self._committed_cursors = set()
        self.executed = []

    @staticmethod
    def _wrap_result(result):
        if isinstance(result, FakeQueryResult):
            return result
        if isinstance(result, FakeRow):
            rowcount = getattr(result, "rowcount", 1)
            return FakeQueryResult(one=result, rowcount=rowcount)
        if isinstance(result, list):
            return FakeQueryResult(many=result, rowcount=len(result))
        if result is None:
            return FakeQueryResult(one=None, rowcount=0)
        if hasattr(result, "rowcount") and not hasattr(result, "fetchone"):
            return FakeQueryResult(one=None, rowcount=result.rowcount)
        return result

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if not self._results:
            raise AssertionError(f"Unexpected SQL: {sql}")
        cursor = self._wrap_result(self._results.pop(0))
        self._last_cursor = cursor
        return cursor

    def _check_cursor_valid(self, cursor):
        if cursor is not None and cursor in self._committed_cursors:
            raise RuntimeError(
                "Cannot fetchone after commit — cursor is closed (psycopg2 behavior). "
                "Move fetchone() before commit()."
            )

    def commit(self):
        self.committed = True
        if self._last_cursor is not None:
            self._committed_cursors.add(self._last_cursor)
            if isinstance(self._last_cursor, FakeQueryResult):
                self._last_cursor._invalidate()

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class FakeCursorConn:
    """Cursor-style connection fake for execute().fetchone() code paths."""

    def __init__(self, one_results):
        self._one_results = list(one_results)
        self._current_one = None
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self._cursor_invalidated = False
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._current_one = self._one_results.pop(0) if self._one_results else None
        self._cursor_invalidated = False
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
        self._cursor_invalidated = True

    def rollback(self):
        self.rolled_back = True
        self._cursor_invalidated = False

    def close(self):
        self.closed = True


class FakeDummyConn:
    """Minimal connection fake for validation tests that must not hit the DB."""

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
    """Minimal connection for admin/auth guard tests."""

    def execute(self, sql, params=None):
        return self

    def fetchone(self):
        return None

    def close(self):
        pass


class _LegacyFakeConn:
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
    """Compatibility helper for older tests while they are migrated."""
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
