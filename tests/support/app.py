"""FastAPI app fixtures and dependency override helpers for tests."""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch


_cached_app = None


def load_main_app():
    """Load the FastAPI app with lifespan side effects patched out."""
    global _cached_app
    if _cached_app is not None:
        return _cached_app

    with patch("core.database.init_db_pool"), patch("core.database.close_db_pool"), patch("threading.Thread"):
        if "main" in sys.modules:
            main_module = importlib.reload(sys.modules["main"])
        else:
            import main as main_module

    main_module.check_media_health = MagicMock(return_value={"ok": True, "missing_count": 0, "samples": []})
    main_module.check_db_health = MagicMock(return_value=True)
    main_module.start_order_cleanup_daemon = MagicMock()
    main_module.validate_production_config = MagicMock(return_value=[])

    _cached_app = main_module.app
    return _cached_app


@contextmanager
def override_user(app, user):
    """Temporarily override FastAPI current-user dependencies."""
    from core.auth import get_admin_user, get_current_user, get_optional_user

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
    """Temporarily override the DB dependency with a fake connection."""
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

