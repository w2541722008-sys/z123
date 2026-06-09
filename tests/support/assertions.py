"""Shared assertion helpers for API contract tests."""

from __future__ import annotations


def assert_detail_as_list(payload: dict):
    assert isinstance(payload.get("detail"), list)
    assert len(payload["detail"]) > 0


def assert_detail_as_string(payload: dict, expected: str):
    assert payload == {"detail": expected}
    assert isinstance(payload["detail"], str)

