"""Centralized test data factories."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from tests.support.db import FakeRow


NOW_UTC = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)


class UserFactory:
    @staticmethod
    def defaults() -> dict:
        return {
            "id": 1,
            "email": "test@example.com",
            "nickname": "TestUser",
            "password_hash": "$2b$12$hashed_for_test",
            "password_algo": "bcrypt",
            "plan_type": "free",
            "plan_expires_at": None,
            "is_admin": False,
            "avatar_url": None,
            "created_at": NOW_UTC.isoformat(),
        }

    @classmethod
    def build(cls, **overrides) -> dict:
        data = cls.defaults()
        data.update(overrides)
        return data

    @classmethod
    def as_row(cls, **overrides) -> FakeRow:
        return FakeRow(cls.build(**overrides))

    @classmethod
    def admin(cls, **overrides) -> dict:
        return cls.build(is_admin=True, plan_type="vip", email="admin@example.com", **overrides)

    @classmethod
    def vip(cls, **overrides) -> dict:
        return cls.build(plan_type="vip", **overrides)

    @classmethod
    def free(cls, **overrides) -> dict:
        return cls.build(plan_type="free", **overrides)

    @classmethod
    def expired_vip(cls, **overrides) -> dict:
        return cls.build(
            plan_type="vip",
            plan_expires_at=(NOW_UTC.replace(year=NOW_UTC.year - 1)).isoformat(),
            **overrides,
        )


class CharacterFactory:
    @staticmethod
    def defaults() -> dict:
        return {
            "id": "char-001",
            "name": "TestChar",
            "card_type": "intimate",
            "is_visible": 1,
            "affection_enabled": 1,
            "affection_rules_json": None,
            "opening_message": "Hello!",
            "greeting": "Hello!",
            "life_profile_json": "{}",
            "mock_reply_style": [],
            "tags": [],
            "plan_required": "guest",
            "required_plan": "guest",
            "scenario_type": None,
            "created_at": NOW_UTC.isoformat(),
        }

    @classmethod
    def build(cls, **overrides) -> dict:
        data = cls.defaults()
        data.update(overrides)
        return data

    @classmethod
    def as_row(cls, **overrides) -> FakeRow:
        return FakeRow(cls.build(**overrides))

    @classmethod
    def intimate(cls, **overrides) -> dict:
        return cls.build(card_type="intimate", **overrides)

    @classmethod
    def scenario(cls, **overrides) -> dict:
        return cls.build(card_type="scenario", scenario_type="adventure", **overrides)

    @classmethod
    def hybrid(cls, **overrides) -> dict:
        return cls.build(card_type="hybrid", **overrides)

    @classmethod
    def with_affection_rules(cls, rules: dict, **overrides) -> dict:
        return cls.build(affection_rules_json=json.dumps(rules), **overrides)

    @classmethod
    def hidden(cls, **overrides) -> dict:
        return cls.build(is_visible=0, **overrides)

    @classmethod
    def vip_only(cls, **overrides) -> dict:
        return cls.build(required_plan="vip", plan_required="vip", **overrides)


class MessageFactory:
    @staticmethod
    def defaults() -> dict:
        return {
            "id": 1,
            "user_id": 1,
            "character_id": "char-001",
            "role": "user",
            "content": "Hello",
            "created_at": NOW_UTC.isoformat(),
            "is_summarized": 0,
        }

    @classmethod
    def build(cls, **overrides) -> dict:
        data = cls.defaults()
        data.update(overrides)
        return data

    @classmethod
    def as_row(cls, **overrides) -> FakeRow:
        return FakeRow(cls.build(**overrides))

    @classmethod
    def user_message(cls, content: str = "Hello", **overrides) -> dict:
        return cls.build(role="user", content=content, **overrides)

    @classmethod
    def assistant_message(cls, content: str = "Hi there!", **overrides) -> dict:
        return cls.build(role="assistant", content=content, **overrides)

    @classmethod
    def system_message(cls, content: str = "System info", **overrides) -> dict:
        return cls.build(role="system", content=content, **overrides)

    @classmethod
    def history(cls, turns: int = 3, character_id: str = "char-001", user_id: int = 1) -> list[dict]:
        messages = []
        for i in range(1, turns + 1):
            messages.append(
                cls.build(
                    id=i * 2 - 1,
                    user_id=user_id,
                    character_id=character_id,
                    role="user",
                    content=f"User message {i}",
                )
            )
            messages.append(
                cls.build(
                    id=i * 2,
                    user_id=user_id,
                    character_id=character_id,
                    role="assistant",
                    content=f"Assistant reply {i}",
                )
            )
        return messages

    @classmethod
    def history_rows(cls, turns: int = 3, character_id: str = "char-001", user_id: int = 1) -> list[FakeRow]:
        return [FakeRow(message) for message in cls.history(turns, character_id, user_id)]


class CharacterStateFactory:
    @staticmethod
    def defaults() -> dict:
        return {
            "user_id": 1,
            "character_id": "char-001",
            "affection": 0,
            "story_phase": "stranger",
            "mood": "neutral",
            "immersion": 0,
            "_last_event_timestamps": {},
            "_daily_event_counts": {},
            "_daily_affection_gained": 0,
            "custom_vars": {},
        }

    @classmethod
    def build(cls, **overrides) -> dict:
        data = cls.defaults()
        data.update(overrides)
        return data

    @classmethod
    def as_row(cls, **overrides) -> FakeRow:
        return FakeRow(cls.build(**overrides))

    @classmethod
    def at_phase(cls, phase: str, affection: int = 0, **overrides) -> dict:
        phase_affection_map = {"stranger": 0, "acquaintance": 25, "friend": 55, "lover": 85}
        default_affection = phase_affection_map.get(phase, affection)
        return cls.build(story_phase=phase, affection=default_affection or affection, **overrides)

    @classmethod
    def with_cooldown(cls, event_name: str, timestamp: str | None = None, **overrides) -> dict:
        ts = timestamp or NOW_UTC.isoformat()
        return cls.build(_last_event_timestamps={event_name: ts}, **overrides)

    @classmethod
    def at_daily_cap(cls, cap: int = 15, **overrides) -> dict:
        return cls.build(_daily_affection_gained=cap, **overrides)

    @classmethod
    def with_diminishing(cls, event_name: str, count: int, **overrides) -> dict:
        return cls.build(_daily_event_counts={event_name: count}, **overrides)


class OrderFactory:
    @staticmethod
    def defaults() -> dict:
        return {
            "id": 1,
            "user_id": 1,
            "plan_type": "vip",
            "amount": 29.9,
            "status": "pending",
            "created_at": NOW_UTC.isoformat(),
            "paid_at": None,
            "expires_at": None,
        }

    @classmethod
    def build(cls, **overrides) -> dict:
        data = cls.defaults()
        data.update(overrides)
        return data

    @classmethod
    def as_row(cls, **overrides) -> FakeRow:
        return FakeRow(cls.build(**overrides))

    @classmethod
    def pending(cls, **overrides) -> dict:
        return cls.build(status="pending", **overrides)

    @classmethod
    def paid(cls, **overrides) -> dict:
        return cls.build(status="paid", paid_at=NOW_UTC.isoformat(), **overrides)

    @classmethod
    def expired(cls, **overrides) -> dict:
        return cls.build(
            status="paid",
            paid_at=(NOW_UTC.replace(year=NOW_UTC.year - 1)).isoformat(),
            expires_at=(NOW_UTC.replace(year=NOW_UTC.year - 1, month=6)).isoformat(),
            **overrides,
        )

    @classmethod
    def cancelled(cls, **overrides) -> dict:
        return cls.build(status="cancelled", **overrides)

