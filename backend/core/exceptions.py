"""
领域异常层次 — 让 service 层脱离 FastAPI HTTPException 依赖。

每个异常携带 `detail: str`，在 main.py 的 handler 中映射为 HTTP 状态码。
这样 service 层可以脱离 Web 框架复用（CLI 工具、后台任务等）。
"""

from __future__ import annotations


class AifriendError(Exception):
    """所有领域异常的基类。"""
    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(detail)


class NotFoundError(AifriendError):
    """资源不存在 — HTTP 404。"""


class BadRequestError(AifriendError):
    """请求参数不合法 — HTTP 400。"""


class ForbiddenError(AifriendError):
    """权限不足 — HTTP 403。"""


class RateLimitError(AifriendError):
    """频率限制 — HTTP 429。"""
    def __init__(self, detail: str = "", headers: dict[str, str] | None = None) -> None:
        super().__init__(detail)
        self.headers = headers


class BudgetExceededError(AifriendError):
    """Token 预算超限 — HTTP 429。"""
