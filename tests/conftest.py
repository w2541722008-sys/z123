"""Pytest fixtures for AIFriend tests.

Shared helpers live in ``tests/support``. Keep this file focused on pytest
configuration and fixture registration so tests do not import implementation
helpers from ``conftest``.
"""

from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("AIFRIEND_DISABLE_BACKGROUND_DB_TASKS", "1")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

if TESTS_DIR in sys.path and BACKEND_DIR in sys.path:
    backend_index = sys.path.index(BACKEND_DIR)
    tests_index = sys.path.index(TESTS_DIR)
    if backend_index > tests_index:
        sys.path.remove(BACKEND_DIR)
        sys.path.insert(tests_index, BACKEND_DIR)


def pytest_configure(config):
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)


warnings.filterwarnings(
    "ignore",
    message=r".*asyncio\.iscoroutinefunction.*inspect\.iscoroutinefunction\(\) instead",
    category=DeprecationWarning,
)

import pytest

from tests.support.app import load_main_app
from tests.support.factories import (
    CharacterFactory,
    CharacterStateFactory,
    MessageFactory,
    OrderFactory,
    UserFactory,
)


@pytest.fixture(scope="session")
def app_module():
    yield load_main_app()


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


@pytest.fixture
def admin_client(app_client):
    """TestClient with admin dependencies preconfigured."""
    app, client = app_client
    from core.auth import CurrentUser, get_admin_user, get_current_user, get_optional_user

    admin = CurrentUser(
        id=1,
        email="admin@example.com",
        nickname="admin",
        plan_type="vip",
        effective_plan="vip",
        is_admin=True,
    )
    saved_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_optional_user] = lambda: admin
    app.dependency_overrides[get_admin_user] = lambda: admin
    yield app, client
    app.dependency_overrides = saved_overrides


@pytest.fixture
def sample_user():
    return UserFactory.build()


@pytest.fixture
def sample_user_row():
    return UserFactory.as_row()


@pytest.fixture
def sample_admin_row():
    return UserFactory.as_row(is_admin=True, plan_type="vip")


@pytest.fixture
def sample_character():
    return CharacterFactory.build()


@pytest.fixture
def sample_character_row():
    return CharacterFactory.as_row()


@pytest.fixture
def sample_state():
    return CharacterStateFactory.build()


@pytest.fixture
def sample_state_row():
    return CharacterStateFactory.as_row()


@pytest.fixture
def sample_message_row():
    return MessageFactory.as_row()


@pytest.fixture
def sample_order_row():
    return OrderFactory.as_row()
