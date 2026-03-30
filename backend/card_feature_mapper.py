from __future__ import annotations

from typing import Any


PROFILE_KEYWORDS = [
    "基础", "信息", "身份", "简介", "概述", "background", "profile", "character", "basic info", "basic", "role",
    "学生", "角色身份", "protagonist", "hero", "user", "appearance", "look", "shape", "body", "外貌",
    "name", "年龄", "介绍", "背景", "经历", "履历", "设定集", "档案",
]

PERSONALITY_KEYWORDS = [
    # ── 中文核心 ──
    "性格", "人格", "特点", "气质", "标签", "心态", "想法", "倾向", "特点说明",
    "说话", "语气", "口癖", "聊天", "反应", "看法", "态度", "偏好", "习惯", "风格",
    # section 级别的人格段落
    "core personality", "personality traits", "personal traits", "人格特质",
    "人设阶段", "behavior", "temperament",
    # 英文 ──
    "personality", "trait", "speech", "style", "dialogue", "tone", "reaction",
    "teachers", "students", "接受度", "tips",
]

SCENARIO_KEYWORDS = [
    "关系", "相处", "状态", "scenario", "relationship", "设定", "当前", "plot", "story", "summary",
    "时间", "地点", "time", "location", "scene", "场景", "开局", "开场", "opening", "content", "update",
    "剧情", "章节", "流程", "事件", "随机事件", "start", "status", "event", "route",
    "情节", "起始", "背景剧情", "推进", "当前阶段", "触发", "流程说明",
]

WORLD_RULES_KEYWORDS = [
    "世界", "规则", "校规", "系统", "world", "rule", "setting", "school", "city", "facilities", "course", "社团",
    "settings", "rules", "school city rules", "school facilities", "lady course", "requirements", "statusblock_rule",
    "设施", "课程", "区域", "阵营", "地图", "组织", "学院", "学校", "都市", "规章", "玩法",
    "机制", "运行规则", "学校设施", "基础规则", "世界观", "组织设定",
]

EXAMPLE_KEYWORDS = [
    "示例", "example", "dialogue sample", "对话样例", "example dialogue", "dialogue", "sample",
    "tips", "statusblock", "模板", "样例", "示范", "格式示例", "例子",
    # 从 description sections 中提取对话示例（含角色名的对话示例节）
    "dialogue_examples", "behavior_examples", "personal_traits",
    # 明确的对话示例词，不含 opening/greeting/first_mes，避免误把开场白放进 examples 层
]

POST_HISTORY_KEYWORDS = [
    "回复规则", "禁忌", "限制", "约束", "rule", "instruction", "requirements", "settings",
    "system prompt", "post history instructions", "format", "输出规则", "输出格式", "注意事项",
    "constraint", "forbid", "remember", "must", "禁止", "必须", "after history", "post history",
    "注意", "补充规则", "生成要求", "输出要求", "约定", "规则说明",
]


def build_feature_layers(
    *,
    description: str,
    description_yaml: str,
    description_sections: dict[str, str],
    personality: str,
    scenario: str,
    creator_notes: str,
    mes_example: str,
    alternates: list[str],
    alternate_sections: list[dict[str, str]],
    character_book_text: str,
    post_history: str,
    extensions: dict[str, Any],
    merge_text_parts,
    pick_root_text,
    pick_section_text,
    compact_json,
) -> dict[str, str]:
    """把导入后的原始文本块映射成更稳定的运行层。

    设计原则：
    1. 这里只负责“字段归位”，不关心导卡来源或模型调用。
    2. 关键词尽量写得中性、可维护，便于后续继续扩展。
    3. 如果某层没命中，允许为空，不在这里做强行编造。
    """
    profile_text = merge_text_parts(
        description_yaml,
        pick_root_text(description_sections),
        pick_section_text(description_sections, PROFILE_KEYWORDS),
    )

    personality_text = merge_text_parts(
        personality,
        pick_section_text(description_sections, PERSONALITY_KEYWORDS),
        *[pick_section_text(section, ["tips", "看法", "态度", "反应", "personality", "style", "tone", "trait"]) for section in alternate_sections],
    )

    scenario_text = merge_text_parts(
        scenario,
        pick_section_text(description_sections, SCENARIO_KEYWORDS),
        *[pick_section_text(section, SCENARIO_KEYWORDS + ["greeting", "opening", "route", "content", "summary"]) for section in alternate_sections],
    )

    world_rules_text = merge_text_parts(
        # 注意：character_book_text（全量摘要）不在这里放，
        # 因为 card_asset_parser.py 已对 character_book 做了分层分流（cb_layers），
        # 最终会在外部调用方通过 merge_text_parts(feature_layers["world_rules"], cb_layers["world_rules"]) 合并。
        # 若此处再塞 character_book_text，会导致 world_rules 层严重重复膨胀。
        compact_json(extensions.get("world") if isinstance(extensions, dict) else None, 1800),
        pick_section_text(description_sections, WORLD_RULES_KEYWORDS),
        *[pick_section_text(section, ["rule", "statusblock_rule", "requirements", "settings", "system", "world"]) for section in alternate_sections],
    )

    example_text = merge_text_parts(
        mes_example,
        pick_section_text(description_sections, EXAMPLE_KEYWORDS),
        *[pick_section_text(section, EXAMPLE_KEYWORDS + ["tips", "status"]) for section in alternate_sections],
    )

    post_history_text = merge_text_parts(
        post_history,
        pick_section_text(description_sections, POST_HISTORY_KEYWORDS),
        *[pick_section_text(section, ["requirements", "format", "constraint", "must", "禁止", "必须", "rule", "instruction"]) for section in alternate_sections],
    )

    return {
        "profile": profile_text,
        "personality": personality_text,
        "scenario": scenario_text,
        "world_rules": world_rules_text,
        "examples": example_text,
        "post_history_rules": post_history_text,
        "description_fallback": description,
    }
