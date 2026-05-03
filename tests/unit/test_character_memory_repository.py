"""character_memory_repository 单元测试。

覆盖：fetch_character_memories / fetch_character_post_rules。
使用 FakeSequenceConn 模拟数据库。
"""
from conftest import FakeSequenceConn, FakeRow, FakeQueryResult


# ============================================================
# fetch_character_memories
# ============================================================
class TestFetchCharacterMemories:
    def test_no_rows(self):
        from services.character_memory_repository import fetch_character_memories
        conn = FakeSequenceConn([
            [],  # fetchall returns empty
        ])
        before, after = fetch_character_memories(conn, "c1", "hello world")
        assert before == []
        assert after == []

    def test_no_context_text(self):
        from services.character_memory_repository import fetch_character_memories
        conn = FakeSequenceConn([
            [FakeRow({"keywords": "hello", "trigger_logic": "any", "content": "text", "position": "before", "priority": 1})],
        ])
        before, after = fetch_character_memories(conn, "c1", "")
        assert before == []
        assert after == []

    def test_any_trigger_logic_match(self):
        from services.character_memory_repository import fetch_character_memories
        conn = FakeSequenceConn([
            [FakeRow({"keywords": "魔法,战斗", "trigger_logic": "any", "content": "魔法系统说明", "position": "before", "priority": 1})],
        ])
        before, after = fetch_character_memories(conn, "c1", "他使用了魔法攻击")
        assert len(before) == 1
        assert "魔法系统说明" in before[0]

    def test_any_trigger_logic_no_match(self):
        from services.character_memory_repository import fetch_character_memories
        conn = FakeSequenceConn([
            [FakeRow({"keywords": "魔法,战斗", "trigger_logic": "any", "content": "魔法系统说明", "position": "before", "priority": 1})],
        ])
        before, after = fetch_character_memories(conn, "c1", "今天天气不错")
        assert before == []
        assert after == []

    def test_all_trigger_logic_all_match(self):
        from services.character_memory_repository import fetch_character_memories
        conn = FakeSequenceConn([
            [FakeRow({"keywords": "魔法,精灵", "trigger_logic": "all", "content": "精灵魔法", "position": "before", "priority": 1})],
        ])
        before, after = fetch_character_memories(conn, "c1", "精灵使用了魔法")
        assert len(before) == 1

    def test_all_trigger_logic_partial_match(self):
        from services.character_memory_repository import fetch_character_memories
        conn = FakeSequenceConn([
            [FakeRow({"keywords": "魔法,精灵", "trigger_logic": "all", "content": "精灵魔法", "position": "before", "priority": 1})],
        ])
        before, after = fetch_character_memories(conn, "c1", "他使用了魔法攻击")
        assert before == []

    def test_position_after(self):
        from services.character_memory_repository import fetch_character_memories
        conn = FakeSequenceConn([
            [FakeRow({"keywords": "hello", "trigger_logic": "any", "content": "after content", "position": "after", "priority": 1})],
        ])
        before, after = fetch_character_memories(conn, "c1", "say hello")
        assert before == []
        assert len(after) == 1
        assert "after content" in after[0]

    def test_priority_ordering(self):
        from services.character_memory_repository import fetch_character_memories
        conn = FakeSequenceConn([
            [FakeRow({"keywords": "hello", "trigger_logic": "any", "content": "low priority", "position": "before", "priority": 10}),
             FakeRow({"keywords": "hello", "trigger_logic": "any", "content": "high priority", "position": "before", "priority": 1})],
        ])
        before, after = fetch_character_memories(conn, "c1", "say hello")
        assert len(before) == 2
        assert before[0] == "high priority"
        assert before[1] == "low priority"

    def test_max_triggered_limit(self):
        from services.character_memory_repository import fetch_character_memories
        rows = [
            FakeRow({"keywords": f"kw{i}", "trigger_logic": "any", "content": f"content{i}", "position": "before", "priority": i})
            for i in range(20)
        ]
        conn = FakeSequenceConn([rows])
        before, after = fetch_character_memories(conn, "c1", " ".join(f"kw{i}" for i in range(20)), max_triggered=5)
        assert len(before) == 5

    def test_content_truncation(self):
        from services.character_memory_repository import fetch_character_memories
        long_content = "x" * 1000
        conn = FakeSequenceConn([
            [FakeRow({"keywords": "hello", "trigger_logic": "any", "content": long_content, "position": "before", "priority": 1})],
        ])
        before, after = fetch_character_memories(conn, "c1", "say hello", max_per_entry=100)
        assert len(before[0]) < 200  # truncated
        assert "截断" in before[0]

    def test_wi_max_budget(self):
        from services.character_memory_repository import fetch_character_memories
        rows = [
            FakeRow({"keywords": "hello", "trigger_logic": "any", "content": "a" * 300, "position": "before", "priority": i})
            for i in range(10)
        ]
        conn = FakeSequenceConn([rows])
        before, after = fetch_character_memories(conn, "c1", "say hello " * 20, wi_max=500)
        total = sum(len(x) for x in before)
        assert total <= 500

    def test_empty_keywords_skipped(self):
        from services.character_memory_repository import fetch_character_memories
        conn = FakeSequenceConn([
            [FakeRow({"keywords": "", "trigger_logic": "any", "content": "text", "position": "before", "priority": 1}),
             FakeRow({"keywords": "hello", "trigger_logic": "any", "content": "matched", "position": "before", "priority": 2})],
        ])
        before, after = fetch_character_memories(conn, "c1", "say hello")
        assert len(before) == 1
        assert "matched" in before[0]

    def test_case_insensitive_matching(self):
        from services.character_memory_repository import fetch_character_memories
        conn = FakeSequenceConn([
            [FakeRow({"keywords": "Hello", "trigger_logic": "any", "content": "matched", "position": "before", "priority": 1})],
        ])
        before, after = fetch_character_memories(conn, "c1", "say hello")
        assert len(before) == 1


# ============================================================
# fetch_character_post_rules
# ============================================================
class TestFetchCharacterPostRules:
    def test_no_rows(self):
        from services.character_memory_repository import fetch_character_post_rules
        conn = FakeSequenceConn([[]])
        result = fetch_character_post_rules(conn, "c1")
        assert result == []

    def test_basic_rules(self):
        from services.character_memory_repository import fetch_character_post_rules
        conn = FakeSequenceConn([
            [FakeRow({"content": "Rule 1", "priority": 1}),
             FakeRow({"content": "Rule 2", "priority": 2})],
        ])
        result = fetch_character_post_rules(conn, "c1")
        assert len(result) == 2
        assert result[0] == "Rule 1"

    def test_with_storyline_filter(self):
        from services.character_memory_repository import fetch_character_post_rules
        conn = FakeSequenceConn([
            [FakeRow({"content": "Storyline rule", "priority": 1})],
        ])
        result = fetch_character_post_rules(conn, "c1", storyline_id=5)
        assert len(result) == 1

    def test_with_story_phase_filter(self):
        from services.character_memory_repository import fetch_character_post_rules
        conn = FakeSequenceConn([
            [FakeRow({"content": "Phase rule", "priority": 1})],
        ])
        result = fetch_character_post_rules(conn, "c1", story_phase="friend")
        assert len(result) == 1

    def test_max_chars_budget(self):
        from services.character_memory_repository import fetch_character_post_rules
        conn = FakeSequenceConn([
            [FakeRow({"content": "a" * 500, "priority": 1}),
             FakeRow({"content": "b" * 500, "priority": 2}),
             FakeRow({"content": "c" * 500, "priority": 3})],
        ])
        result = fetch_character_post_rules(conn, "c1", max_chars=800)
        total = sum(len(r) for r in result)
        assert total <= 800 + 20  # small tolerance for truncation marker

    def test_empty_content_skipped(self):
        from services.character_memory_repository import fetch_character_post_rules
        conn = FakeSequenceConn([
            [FakeRow({"content": "", "priority": 1}),
             FakeRow({"content": "Valid rule", "priority": 2})],
        ])
        result = fetch_character_post_rules(conn, "c1")
        assert len(result) == 1
        assert result[0] == "Valid rule"

    def test_truncation_of_last_rule(self):
        from services.character_memory_repository import fetch_character_post_rules
        conn = FakeSequenceConn([
            [FakeRow({"content": "a" * 300, "priority": 1}),
             FakeRow({"content": "b" * 500, "priority": 2})],
        ])
        result = fetch_character_post_rules(conn, "c1", max_chars=600)
        # First rule (300) fits, second rule (500) exceeds remaining 300
        # remaining=300 > 100, so second rule gets truncated
        assert len(result) == 2
        assert "截断" in result[-1]
