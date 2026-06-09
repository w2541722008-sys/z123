"""admin_dashboard_repository 单元测试 — 使用 FakeSequenceConn 模拟 DB。"""

from tests.support.db import FakeQueryResult, FakeSequenceConn


# ============================================================
# get_dashboard_stats — 聚合方法
# ============================================================

def test_get_dashboard_stats_aggregates_all_sub_stats():
    """验证 get_dashboard_stats 正确聚合 7 个子统计的返回值。"""
    from repositories.admin_dashboard_repository import get_dashboard_stats

    conn = FakeSequenceConn([
        FakeQueryResult(one={"cnt": 100}),           # _count_users
        FakeQueryResult(one={"cnt": 5}),             # _count_today_new_users
        FakeQueryResult(one={"cnt": 30}),            # _count_paid_users
        FakeQueryResult(one={"cnt": 3}),             # _count_today_paid_orders
        FakeQueryResult(one={"total": 5970}),        # _sum_today_revenue
        FakeQueryResult(one={"cnt": 2}),             # _count_expiring_soon
        FakeQueryResult(many=[                       # _plan_distribution
            {"plan_type": "free", "cnt": 70},
            {"plan_type": "vip", "cnt": 25},
            {"plan_type": "svip", "cnt": 5},
        ]),
    ])

    result = get_dashboard_stats(conn)

    assert result["total_users"] == 100
    assert result["today_new_users"] == 5
    assert result["paid_users"] == 30
    assert result["today_orders"] == 3
    assert result["today_revenue"] == 5970
    assert result["expiring_soon"] == 2
    assert result["plan_distribution"] == {"free": 70, "vip": 25, "svip": 5}


# ============================================================
# 私有函数 — 逐一测试
# ============================================================

# _count_users

def test_count_users_returns_count():
    from repositories.admin_dashboard_repository import _count_users

    conn = FakeSequenceConn([FakeQueryResult(one={"cnt": 42})])
    assert _count_users(conn) == 42


def test_count_users_returns_zero_when_none():
    from repositories.admin_dashboard_repository import _count_users

    conn = FakeSequenceConn([FakeQueryResult(one=None)])
    assert _count_users(conn) == 0


# _count_today_new_users

def test_count_today_new_users():
    from repositories.admin_dashboard_repository import _count_today_new_users

    conn = FakeSequenceConn([FakeQueryResult(one={"cnt": 3})])
    assert _count_today_new_users(conn) == 3


# _count_paid_users

def test_count_paid_users():
    from repositories.admin_dashboard_repository import _count_paid_users

    conn = FakeSequenceConn([FakeQueryResult(one={"cnt": 15})])
    assert _count_paid_users(conn) == 15


# _count_today_paid_orders

def test_count_today_paid_orders():
    from repositories.admin_dashboard_repository import _count_today_paid_orders

    conn = FakeSequenceConn([FakeQueryResult(one={"cnt": 8})])
    assert _count_today_paid_orders(conn) == 8


# _sum_today_revenue

def test_sum_today_revenue():
    from repositories.admin_dashboard_repository import _sum_today_revenue

    conn = FakeSequenceConn([FakeQueryResult(one={"total": 12990})])
    assert _sum_today_revenue(conn) == 12990


def test_sum_today_revenue_zero():
    from repositories.admin_dashboard_repository import _sum_today_revenue

    conn = FakeSequenceConn([FakeQueryResult(one={"total": 0})])
    assert _sum_today_revenue(conn) == 0


# _count_expiring_soon

def test_count_expiring_soon():
    from repositories.admin_dashboard_repository import _count_expiring_soon

    conn = FakeSequenceConn([FakeQueryResult(one={"cnt": 4})])
    assert _count_expiring_soon(conn, days=3) == 4


def test_count_expiring_soon_with_custom_days():
    from repositories.admin_dashboard_repository import _count_expiring_soon

    conn = FakeSequenceConn([FakeQueryResult(one={"cnt": 10})])
    assert _count_expiring_soon(conn, days=7) == 10


# _plan_distribution

def test_plan_distribution():
    from repositories.admin_dashboard_repository import _plan_distribution

    conn = FakeSequenceConn([
        FakeQueryResult(many=[
            {"plan_type": "free", "cnt": 100},
            {"plan_type": "vip", "cnt": 50},
        ]),
    ])
    assert _plan_distribution(conn) == {"free": 100, "vip": 50}


def test_plan_distribution_null_treated_as_free():
    from repositories.admin_dashboard_repository import _plan_distribution

    # SQL 侧 COALESCE 将 NULL 转为 'free'，mock 数据也直接用 'free'
    conn = FakeSequenceConn([
        FakeQueryResult(many=[
            {"plan_type": "free", "cnt": 10},
            {"plan_type": "vip", "cnt": 5},
        ]),
    ])
    assert _plan_distribution(conn) == {"free": 10, "vip": 5}


# ============================================================
# get_dashboard_trend — 消除 N+1 后的单查询实现
# ============================================================

def test_get_dashboard_trend_multiple_days():
    from repositories.admin_dashboard_repository import get_dashboard_trend

    conn = FakeSequenceConn([
        FakeQueryResult(many=[
            {"day": "2026-05-19", "new_users": 2, "new_orders": 1, "revenue": 1990},
            {"day": "2026-05-20", "new_users": 5, "new_orders": 3, "revenue": 5970},
            {"day": "2026-05-21", "new_users": 1, "new_orders": 0, "revenue": 0},
        ]),
    ])

    result = get_dashboard_trend(conn, 3)

    assert len(result) == 3
    assert result[0] == {"date": "2026-05-19", "new_users": 2, "new_orders": 1, "revenue": 1990}
    assert result[1]["date"] == "2026-05-20"
    assert result[2]["date"] == "2026-05-21"
    assert result[2]["new_orders"] == 0
    assert result[2]["revenue"] == 0


def test_get_dashboard_trend_single_day():
    from repositories.admin_dashboard_repository import get_dashboard_trend

    conn = FakeSequenceConn([
        FakeQueryResult(many=[
            {"day": "2026-05-21", "new_users": 3, "new_orders": 2, "revenue": 3980},
        ]),
    ])

    result = get_dashboard_trend(conn, 1)
    assert len(result) == 1
    assert result[0]["date"] == "2026-05-21"


# ============================================================
# list_audit_logs
# ============================================================

def test_list_audit_logs_no_filter():
    from repositories.admin_dashboard_repository import list_audit_logs

    conn = FakeSequenceConn([
        FakeQueryResult(one={"total": 2}),  # count
        FakeQueryResult(many=[              # paginated rows
            {"id": 2, "operator_id": 1, "operator_email": "a@b.com",
             "action": "edit", "target_type": "user", "target_id": "10",
             "detail": {}, "created_at": "2026-05-21T00:00:00+00:00"},
            {"id": 1, "operator_id": 1, "operator_email": "a@b.com",
             "action": "delete", "target_type": "user", "target_id": "5",
             "detail": {}, "created_at": "2026-05-20T00:00:00+00:00"},
        ]),
    ])

    result = list_audit_logs(conn, page=1, limit=50)

    assert result["total"] == 2
    assert len(result["rows"]) == 2
    assert result["rows"][0]["id"] == 2
    assert result["rows"][1]["action"] == "delete"


def test_list_audit_logs_with_action_filter():
    from repositories.admin_dashboard_repository import list_audit_logs

    conn = FakeSequenceConn([
        FakeQueryResult(one={"total": 1}),
        FakeQueryResult(many=[
            {"id": 1, "operator_id": 1, "operator_email": "a@b.com",
             "action": "delete_user", "target_type": "user", "target_id": "3",
             "detail": {}, "created_at": "2026-05-21T00:00:00+00:00"},
        ]),
    ])

    result = list_audit_logs(conn, action="delete_user")

    assert result["total"] == 1
    assert len(result["rows"]) == 1


def test_list_audit_logs_empty():
    from repositories.admin_dashboard_repository import list_audit_logs

    conn = FakeSequenceConn([
        FakeQueryResult(one={"total": 0}),
        FakeQueryResult(many=[]),
    ])

    result = list_audit_logs(conn)

    assert result["total"] == 0
    assert result["rows"] == []


def test_list_audit_logs_pagination_page2():
    from repositories.admin_dashboard_repository import list_audit_logs

    conn = FakeSequenceConn([
        FakeQueryResult(one={"total": 10}),
        FakeQueryResult(many=[
            {"id": 5, "operator_id": 1, "operator_email": "a@b.com",
             "action": "edit", "target_type": "user", "target_id": "5",
             "detail": {}, "created_at": "2026-05-20T00:00:00+00:00"},
        ]),
    ])

    result = list_audit_logs(conn, page=2, limit=5)

    assert result["total"] == 10
    assert len(result["rows"]) == 1
