from __future__ import annotations

import base64
import json
import re
import struct
from hashlib import sha1
from pathlib import Path
from typing import Any

from card_feature_mapper import build_feature_layers
from card_text_utils import (
    collapse_blank_lines,
    compact_json,
    ensure_list,
    extract_yaml_block,
    merge_text_parts,
    normalize_text,
    pick_root_text,
    pick_section_text,
    remove_html_tags,
    shorten_text,
    split_structured_sections,
    strip_xml_wrappers,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SUPPORTED_SUFFIXES = {".png"}


# ============================================================
# PNG 元数据解析（借鉴 SillyTavern 的 chara / ccv3 读取思路）
# ============================================================
def extract_png_text_chunks(png_bytes: bytes) -> list[tuple[str, str]]:
    """从 PNG 的 tEXt chunk 中提取 keyword + text。"""
    if not png_bytes.startswith(PNG_SIGNATURE):
        raise ValueError("不是合法 PNG 文件")

    chunks: list[tuple[str, str]] = []
    offset = len(PNG_SIGNATURE)
    total = len(png_bytes)

    while offset + 8 <= total:
        length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        chunk_type = png_bytes[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > total:
            break

        chunk_data = png_bytes[data_start:data_end]
        if chunk_type == b"tEXt" and b"\x00" in chunk_data:
            keyword_raw, text_raw = chunk_data.split(b"\x00", 1)
            keyword = keyword_raw.decode("latin-1", errors="ignore")
            text = text_raw.decode("latin-1", errors="ignore")
            chunks.append((keyword, text))

        offset = crc_end
    return chunks


def read_card_json_from_png(file_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """优先读 ccv3，再回退 chara，行为与酒馆一致。"""
    png_bytes = file_path.read_bytes()
    text_chunks = extract_png_text_chunks(png_bytes)
    if not text_chunks:
        raise ValueError("PNG 里没有可用的文本元数据")

    selected_keyword = ""
    payload = ""
    lower_map = [(keyword.lower(), text) for keyword, text in text_chunks]
    for preferred in ("ccv3", "chara"):
        hit = next((text for keyword, text in lower_map if keyword == preferred), "")
        if hit:
            selected_keyword = preferred
            payload = hit
            break

    if not payload:
        raise ValueError("PNG 中没有 chara / ccv3 角色卡元数据")

    decoded = base64.b64decode(payload).decode("utf-8", errors="ignore")
    raw_card = json.loads(decoded)
    return raw_card, {
        "source_kind": "png",
        "source_path": str(file_path),
        "embedded_format": selected_keyword,
        "avatar_path": str(file_path),
    }


# ============================================================
# 卡片读取与归一化
# ============================================================
def canonical_card_stem(file_path: Path) -> str:
    stem = file_path.stem
    if stem.endswith("_data"):
        return stem[:-5]
    return stem


def discover_card_sources(card_dir: Path) -> list[dict[str, Any]]:
    """扫描目录，仅把 PNG 作为导卡入口。"""
    results: list[dict[str, Any]] = []
    for path in sorted(card_dir.iterdir() if card_dir.exists() else []):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        stem = canonical_card_stem(path)
        results.append(
            {
                "canonical_name": stem,
                "primary_path": path,
                "png_path": path,
            }
        )
    return results


def normalize_raw_card(raw_card: dict[str, Any]) -> dict[str, Any]:
    """把 v2/v3 或 data 包裹结构统一拍平。"""
    data = raw_card.get("data")
    normalized = dict(data) if isinstance(data, dict) else {}

    for key, value in raw_card.items():
        if key == "data":
            continue
        if key not in normalized or normalized.get(key) in (None, "", [], {}):
            normalized[key] = value

    return normalized


def load_card_source(source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """读取单个候选卡源，仅支持 PNG。"""
    primary = source["primary_path"]
    raw_card, meta = read_card_json_from_png(primary)
    meta["canonical_name"] = source["canonical_name"]
    return raw_card, meta


# ============================================================
# 卡型识别与结构化映射
# ============================================================
def detect_card_type(card: dict[str, Any]) -> str:
    """按当前卡库的真实特征做启发式识别。

    识别优先级（从高到低）：
      1. system  — 含世界/游戏系统标识符（英文/中文均覆盖）
      2. scenario — 含剧情推进结构标签（json_patch / ejs / 状态机等）
      3. hybrid  — 含脚本扩展但同时有角色描述
      4. world   — 只有 character_book 世界书、无角色档案
      5. character — 有明确角色档案字段
      6. hybrid  — 兜底
    """
    description = normalize_text(card.get("description"))
    first_mes = normalize_text(card.get("first_mes"))
    alternate = "\n".join(ensure_list(card.get("alternate_greetings")))
    creator_notes = normalize_text(card.get("creator_notes"))
    personality = normalize_text(card.get("personality"))
    scenario_field = normalize_text(card.get("scenario"))
    extensions = card.get("extensions") or {}
    character_book = card.get("character_book") or {}
    haystack = "\n".join([description, first_mes, alternate, creator_notes, personality, scenario_field, compact_json(character_book, 4000)]).lower()

    # ── 1. system / world-system 类 ────────────────────────────────────
    # 英文标识
    _SYSTEM_EN = [
        "not a specific character", "role play game system", "you are a game master",
        "you are a narrator", "you are the world", "you are a simulation",
    ]
    # 中文标识（世界/游戏系统类卡的典型表述）
    _SYSTEM_ZH = [
        "你不是某个具体角色", "你不是一个具体角色",
        "你是世界", "你扮演世界", "你负责驱动世界",
        "你是gm", "你是游戏主持人", "你扮演gm",
        "世界模拟器", "剧情模拟器", "游戏系统",
        "你是叙述者", "你是讲述者", "你是narr",
        "不扮演任何单一角色",
    ]
    if any(token in haystack for token in _SYSTEM_EN + _SYSTEM_ZH):
        return "system"

    # ── 2. scenario / story-engine 类 ──────────────────────────────────
    # 含剧情状态机或动态更新标签（常见于都市/学园类世界卡的 EJS 脚本段落）
    _SCENARIO_TOKENS = [
        "<json_patch>", "<update>", "<summary>", "<content>",
        "{{format_message", "mvu_update", "[ejs]",
        # 中文剧情引擎标识
        "剧情入口", "剧情推进", "剧情状态", "章节入口",
        "玩家行动", "行动结果", "推进节点",
    ]
    if any(token in haystack for token in _SCENARIO_TOKENS):
        # 如果同时有明确角色档案，归 hybrid（剧情+人物混合卡）
        has_char_fields = bool(description or personality or card.get("first_mes"))
        if has_char_fields:
            return "hybrid"
        return "scenario"

    # ── 3. hybrid — 含脚本扩展且有角色描述 ─────────────────────────────
    if isinstance(extensions, dict) and any(key in extensions for key in ["tavern_helper", "regex_scripts"]):
        has_char_fields = bool(description or personality or card.get("first_mes"))
        if has_char_fields:
            return "hybrid"
        return "scenario"

    # ── 4. world — 主要靠 character_book，无角色档案 ──────────────────
    has_char_book = bool(character_book)
    has_world_ext = isinstance(extensions, dict) and bool(extensions.get("world"))
    has_char_fields = bool(description or personality or card.get("first_mes"))

    if (has_char_book or has_world_ext) and not has_char_fields:
        return "world"

    # ── 5. character — 有明确角色档案字段 ─────────────────────────────
    if has_char_fields:
        return "character"

    # ── 6. 兜底 ────────────────────────────────────────────────────────
    return "hybrid"


def build_default_system_prompt(asset_type: str, display_name: str) -> str:
    if asset_type == "system":
        return (
            f"你现在不是普通闲聊助手，而是“{display_name}”这一套世界/系统规则的运行者。"
            "请严格根据设定推进剧情与反馈结果，用中文输出，不要跳出设定解释自己是 AI。"
        )
    if asset_type == "scenario":
        return (
            f"你现在负责驱动“{display_name}”这条剧情/场景。"
            "请延续剧情状态、明确反馈玩家行动结果，用中文自然推进，不要跳出戏。"
        )
    if asset_type == "world":
        return (
            f"你现在负责呈现“{display_name}”对应的世界观与规则。"
            "回复时优先维持世界逻辑、设定一致性和沉浸感。"
        )
    return (
        f"你要始终扮演“{display_name}”，保持设定稳定、语气自然、不要暴露自己是 AI。"
        "回复要像真实聊天，而不是解释设定。"
    )


def collect_tags(card: dict[str, Any], asset_type: str) -> list[str]:
    tags = ensure_list(card.get("tags"))
    if asset_type not in tags:
        tags.append(asset_type)
    return tags[:12]


def stringify_character_book(value: Any) -> str:
    """把世界书/角色书压成可读摘要（兜底用，完整内容请用 extract_character_book_layers）。"""
    if not value:
        return ""
    if isinstance(value, dict):
        entries = value.get("entries")
        if isinstance(entries, list):
            lines = []
            for item in entries[:12]:
                if not isinstance(item, dict):
                    continue
                comment = normalize_text(item.get("comment") or item.get("name") or item.get("key") or "")
                content = normalize_text(item.get("content") or item.get("entry") or "")
                merged = f"- {comment}: {shorten_text(content, 180)}".strip()
                if merged and merged != "- :":
                    lines.append(merged)
            return "\n".join(lines)
    return compact_json(value, limit=2500)


# ============================================================
# character_book entries 分层关键词（comment 匹配）
# 说明：很多高质量卡把角色全部设定塞进 character_book 的 entries，
# 顶层 description/personality 字段反而是空的。这里按 comment 关键词
# 把 entries 内容分流到对应运行层，与 card_feature_mapper 的 section
# 分层逻辑保持对应。
# ============================================================
_CB_PROFILE_KEYS = [
    "基础", "基本信息", "档案", "background", "profile", "basic", "character",
    "setting", "身份", "简介", "role info", "角色档案", "人物档案", "info",
    "外貌", "appearance", "身材", "体型", "性格档案", "角色速览", "速览",
    "name", "年龄", "介绍", "人物", "npc",
]
_CB_PERSONALITY_KEYS = [
    # ── 中文核心 ──
    "性格", "人格", "气质", "口吻", "性情", "偏好", "感情", "风格", "独立",
    "说话", "口癖", "表达", "演绎", "演绎指导", "缺点", "优点",
    # 含角色名的 NSFW/语言类 entry（角色名+下划线+这些词）
    "语料", "nsfw", "文风", "语言特征", "言语", "speech style",
    # 英文核心 ──
    "personality", "trait", "speech", "tone", "dialogue", "reaction",
    "guide", "independence",
    # 逻辑/演绎指导类 ──（不该进 post_history，是人格指导）
    "逻辑指导", "人设指导", "演绎核心", "行为指导", "独立人格",
]
_CB_SCENARIO_KEYS = [
    # ── 中文核心 ──
    "剧情", "开场", "主线", "支线", "节点", "背景故事", "状态", "当前", "事件",
    "活动", "假期", "节日", "开场白", "时期", "阶段", "线",
    "stage", "timeline", "时间锚", "记忆",
    "关系", "养成", "双重生", "骨科", "百合",
    # 英文核心 ──
    "scenario", "story", "plot", "opening", "status", "route", "relationship",
]
_CB_WORLD_RULES_KEYS = [
    # ── 中文核心 ──
    "世界观", "世界", "规则", "系统", "机制", "玩法", "设施", "组织", "地图",
    "法则", "文化", "校园", "黑社会", "帮派", "民族", "大背景",
    # 英文核心 ──
    "world", "rule", "setting", "school", "city", "guidelines",
]
_CB_EXAMPLE_KEYS = [
    # ── 中文对话类 ──
    "示例", "语料", "对话样例", "示范", "样例", "对话", "参考对话",
    "说话风格", "风格加强", "直播间风格", "线上风格", "线上人设",
    "扮演示范", "回复示例", "语言示例",
    # 英文 ──
    "example", "dialogue sample", "dialogue", "sample", "style example",
]
_CB_POST_HISTORY_KEYS = [
    # ── 中文规则类 ──
    "回复规则", "输出规则", "禁止", "约束", "要求", "注意", "限制", "规范",
    "扮演规则", "扮演规范", "重要", "规则", "格式要求", "生成规则",
    "指导", "线上规则", "线下规则", "线上线下", "输出规范",
    "写给", "ai说明", "特殊规则",
    # 英文 ──
    "constraint", "must", "remember", "format", "instruction",
    "post history", "after history",
]
# 变量/状态类 entry 一般是纯系统数据，不注入 prompt
_CB_SKIP_PATTERNS = [
    # ── EJS / 格式模板 ──
    "[initvar]", "[mvu_update]", "[ejs]",
    "变量初始化", "变量更新", "变量列表",
    "变量输出", "status_current", "format_message",
    "控制器", "format_message_variable",
    # ── 动态状态块 ──
    "statusblock", "status_block", "状态栏模板", "状态栏格式",
    "output_format", "output format", "输出格式模板",
    # ── 状态栏/政务系统/互动触发类 entry（仅供运行时响应，不注入背景）──
    "状态栏", "政务系统", "打工成果", "鱼雁小笺", "威望与势力",
    "章节管理器", "血液规则", "证据搜查", "审判规则",
    # ── 脚本/扩展 ──
    "regex_script", "tavern_helper_script",
    "injection_point", "injection point",
    # ── 纯技术 entry（内容不该注入模型）──
    "wi_entry", "worldinfo_entry", "lorebook_entry",
]
# content 内 XML 标签/节名关键词 → 分层
_CONTENT_PROFILE_TAGS = [
    "character_", "npc_", "角色档案", "基本信息", "角色总览", "人物",
    "name:", "age:", "appearance:", "identity:", "身份:",
]
_CONTENT_SCENARIO_TAGS = [
    "storyline_", "story", "主线", "剧情", "scenario", "plot", "背景故事",
    "timeline_anchor", "stage", "开场",
]
_CONTENT_WORLD_TAGS = [
    "worldview_", "world", "世界观", "设定", "环境",
    "大背景", "文化", "黑社会",
]
_CONTENT_PERSONALITY_TAGS = [
    "nsfw_", "guide_", "演绎", "独立人格", "缺点", "性格",
    "说话", "语言特征", "communication style", "dialogue_",
]
_CONTENT_POST_HISTORY_TAGS = [
    "扮演规则", "输出规范", "禁止", "约束", "格式要求", "生成规则",
    "特殊规则", "rule:", "instruction:",
]


def _infer_layer_from_content(content_lower: str) -> str | None:
    """当 comment 不能明确分类时，根据 content 开头的 XML 标签/节名推断层位。"""
    # 取内容开头 120 字符的 XML 标签名
    tag_match = re.search(r"<([a-z_\u4e00-\u9fa5][a-z0-9_\u4e00-\u9fa5]{0,40})>", content_lower[:120])
    tag = tag_match.group(1).lower() if tag_match else ""
    sample = content_lower[:300]

    # post_history 优先（避免规则类内容落入 world_rules）
    for kw in _CONTENT_POST_HISTORY_TAGS:
        if kw in tag or kw in sample[:120]:
            return "post_history_rules"
    for kw in _CONTENT_PROFILE_TAGS:
        if kw in tag or kw in sample[:80]:
            return "profile"
    for kw in _CONTENT_SCENARIO_TAGS:
        if kw in tag or kw in sample[:80]:
            return "scenario"
    for kw in _CONTENT_WORLD_TAGS:
        if kw in tag or kw in sample[:80]:
            return "world_rules"
    for kw in _CONTENT_PERSONALITY_TAGS:
        if kw in tag or kw in sample[:80]:
            return "personality"
    return None


def _cb_comment_match(comment_lower: str, keywords: list[str]) -> bool:
    return any(kw in comment_lower for kw in keywords)


def extract_character_book_layers(value: Any) -> dict[str, Any]:
    """把 character_book 的 entries 按 ST 规范正确分流。

    核心逻辑（与 SillyTavern 对齐）：
    - constant=True 或无 keys：常驻词条，按 position 分入 world_info_before / world_info_after
    - constant=False 且有 keys：条件触发词条，存入 conditional_entries 列表，运行时按关键词扫描注入
    - 所有词条按 insertion_order 排序（数字越小越靠前）
    - 跳过变量/系统类词条（会让模型困惑）
    - 兼容旧行为：仍按 comment 关键词对常驻词条分流到 profile/personality 等语义层

    返回结构：
    {
        # 语义层（常驻，合并文本）
        "profile": str,
        "personality": str,
        "scenario": str,
        "world_rules": str,
        "examples": str,
        "post_history_rules": str,
        # World Info 位置层（常驻，合并文本，按 position 区分）
        "world_info_before": str,   # position="before_char"
        "world_info_after": str,    # position="after_char"
        # 条件触发词条列表（运行时按关键词动态注入）
        "conditional_entries": list[dict],  # 每条格式见下
    }

    conditional_entries 每条格式：
    {
        "keys": list[str],          # 触发关键词列表
        "content": str,             # 词条正文
        "comment": str,             # 词条名/备注
        "position": str,            # "before_char" | "after_char"
        "insertion_order": int,     # 排序权重（越小越靠前注入）
        "case_sensitive": bool,     # 关键词是否区分大小写
        "secondary_keys": list[str],# 二级关键词（AND 逻辑）
        "logic": str,               # "AND" | "OR"（primary keys 内部逻辑）
    }
    """
    empty: dict[str, Any] = {
        "profile": "",
        "personality": "",
        "scenario": "",
        "world_rules": "",
        "examples": "",
        "post_history_rules": "",
        "world_info_before": "",
        "world_info_after": "",
        "conditional_entries": [],
    }

    if not value or not isinstance(value, dict):
        return empty

    entries = value.get("entries")
    if not isinstance(entries, list) or not entries:
        return empty

    # ── 先按 insertion_order 排序（缺失时默认 0，数字小 = 靠前）──────────
    def _sort_key(item: Any) -> int:
        if not isinstance(item, dict):
            return 0
        v = item.get("insertion_order") or item.get("order") or 0
        return int(v) if isinstance(v, (int, float)) else 0

    sorted_entries = sorted(
        [e for e in entries if isinstance(e, dict)],
        key=_sort_key,
    )

    buckets: dict[str, list[str]] = {k: [] for k in [
        "profile", "personality", "scenario",
        "world_rules", "examples", "post_history_rules",
        "world_info_before", "world_info_after",
    ]}
    conditional_entries: list[dict] = []

    for item in sorted_entries:
        # ── 提取基本字段 ───────────────────────────────────────────────────
        comment = normalize_text(item.get("comment") or item.get("name") or "")
        content_raw = normalize_text(item.get("content") or item.get("entry") or "")
        if not content_raw:
            continue

        # 跳过纯系统/变量类 entry（这些进 prompt 会让模型很困惑）
        comment_lower = comment.lower()
        if any(skip in comment_lower for skip in _CB_SKIP_PATTERNS):
            continue
        if any(skip in content_raw[:80].lower() for skip in ["{{format_message", "format_message_variable"]):
            continue

        # ── 解析 ST 规范字段 ───────────────────────────────────────────────
        # constant: True=常驻，False/缺失=条件触发
        constant = item.get("constant", True)  # 默认常驻（兼容旧卡没有 constant 字段）
        # keys: 触发关键词列表（ST 里也叫 keys / primary_keys）
        raw_keys = item.get("keys") or item.get("primary_keys") or []
        keys: list[str] = [str(k).strip() for k in (raw_keys if isinstance(raw_keys, list) else []) if str(k).strip()]
        # secondary_keys: 二级关键词（AND 条件）
        raw_sec = item.get("secondary_keys") or item.get("secondary_key") or []
        secondary_keys: list[str] = [str(k).strip() for k in (raw_sec if isinstance(raw_sec, list) else []) if str(k).strip()]
        # position: before_char / after_char / before_depth / after_depth
        position = str(item.get("position") or "before_char")
        if position not in ("before_char", "after_char"):
            # before_depth / after_depth → 统一映射为 before/after
            position = "before_char" if "before" in position else "after_char"
        # case_sensitive
        case_sensitive = bool(item.get("case_sensitive", False))
        # logic（keys 内部：AND / OR）
        logic = str(item.get("logic") or "OR").upper()
        if logic not in ("AND", "OR"):
            logic = "OR"
        # insertion_order（已用于排序，但也存下来方便后续按权重二次排序）
        insertion_order = _sort_key(item)

        content = collapse_blank_lines(strip_xml_wrappers(remove_html_tags(content_raw)))

        # ── 条件触发词条：constant=False 且有 keys → 存入 conditional_entries ──
        if not constant and keys:
            conditional_entries.append({
                "keys": keys,
                "content": content,
                "comment": comment,
                "position": position,
                "insertion_order": insertion_order,
                "case_sensitive": case_sensitive,
                "secondary_keys": secondary_keys,
                "logic": logic,
            })
            continue  # 不进常驻层

        # ── 常驻词条：按 position 写入 world_info_before / after ───────────
        pos_bucket = "world_info_before" if position == "before_char" else "world_info_after"
        buckets[pos_bucket].append(f"[{comment}]\n{content}" if comment else content)

        # ── 同时按 comment 关键词分流到语义层（保留旧行为，供 prompt 组装用）──
        tagged = False
        if _cb_comment_match(comment_lower, [k.lower() for k in _CB_PROFILE_KEYS]):
            buckets["profile"].append(f"[{comment}]\n{content}" if comment else content)
            tagged = True
        if _cb_comment_match(comment_lower, [k.lower() for k in _CB_PERSONALITY_KEYS]):
            buckets["personality"].append(f"[{comment}]\n{content}" if comment else content)
            tagged = True
        if _cb_comment_match(comment_lower, [k.lower() for k in _CB_SCENARIO_KEYS]):
            buckets["scenario"].append(f"[{comment}]\n{content}" if comment else content)
            tagged = True
        if _cb_comment_match(comment_lower, [k.lower() for k in _CB_WORLD_RULES_KEYS]):
            buckets["world_rules"].append(f"[{comment}]\n{content}" if comment else content)
            tagged = True
        if _cb_comment_match(comment_lower, [k.lower() for k in _CB_EXAMPLE_KEYS]):
            buckets["examples"].append(f"[{comment}]\n{content}" if comment else content)
            tagged = True
        if _cb_comment_match(comment_lower, [k.lower() for k in _CB_POST_HISTORY_KEYS]):
            buckets["post_history_rules"].append(f"[{comment}]\n{content}" if comment else content)
            tagged = True

        if not tagged:
            # 二级策略：comment 是人名/无法分类时，看 content 内部的 XML 标签/节名
            inferred = _infer_layer_from_content(content_raw.lower())
            if inferred:
                buckets[inferred].append(f"[{comment}]\n{content}" if comment else content)
                tagged = True

        # 仍没命中的常驻词条放入 world_rules 做兜底
        if not tagged:
            buckets["world_rules"].append(f"[{comment}]\n{content}" if comment else content)

    result: dict[str, Any] = {k: "\n\n".join(parts).strip() for k, parts in buckets.items()}
    result["conditional_entries"] = conditional_entries
    return result


def derive_opening_message(card: dict[str, Any]) -> str:
    """提取开场白，保留完整原文（不截断，开场白需要完整呈现给用户）。"""
    first_mes = remove_html_tags(strip_xml_wrappers(card.get("first_mes") or "")).strip()
    if first_mes:
        return first_mes

    alternates = [remove_html_tags(strip_xml_wrappers(item)).strip() for item in ensure_list(card.get("alternate_greetings"))]
    alternates = [text for text in alternates if text]
    if alternates:
        return alternates[0]

    return ""


def build_structured_asset(raw_card: dict[str, Any], source_meta: dict[str, Any]) -> dict[str, Any]:
    card = normalize_raw_card(raw_card)
    asset_type = detect_card_type(card)
    display_name = normalize_text(card.get("name")) or source_meta.get("canonical_name") or "未命名卡片"
    description = normalize_text(card.get("description"))
    description_yaml = extract_yaml_block(description)
    description_sections = split_structured_sections(description_yaml or description)
    personality = collapse_blank_lines(strip_xml_wrappers(card.get("personality") or ""))
    scenario = collapse_blank_lines(strip_xml_wrappers(card.get("scenario") or ""))
    mes_example = collapse_blank_lines(remove_html_tags(card.get("mes_example") or ""))
    creator_notes = collapse_blank_lines(remove_html_tags(card.get("creator_notes") or ""))
    first_mes = collapse_blank_lines(remove_html_tags(strip_xml_wrappers(card.get("first_mes") or "")))
    alternates = [collapse_blank_lines(remove_html_tags(strip_xml_wrappers(item))) for item in ensure_list(card.get("alternate_greetings"))]
    alternates = [item for item in alternates if item]
    alternate_sections = [split_structured_sections(item) for item in alternates[:3]]
    # character_book 精简摘要（给 world_rules 层兜底），同时做分层提取
    character_book_text = stringify_character_book(card.get("character_book"))
    cb_layers = extract_character_book_layers(card.get("character_book"))
    post_history = collapse_blank_lines(remove_html_tags(card.get("post_history_instructions") or ""))
    system_prompt = collapse_blank_lines(remove_html_tags(card.get("system_prompt") or ""))
    extensions = card.get("extensions") if isinstance(card.get("extensions"), dict) else {}

    feature_layers = build_feature_layers(
        description=description,
        description_yaml=description_yaml,
        description_sections=description_sections,
        personality=personality,
        scenario=scenario,
        creator_notes=creator_notes,
        mes_example=mes_example,
        alternates=alternates,
        alternate_sections=alternate_sections,
        character_book_text=character_book_text,
        post_history=post_history,
        extensions=extensions,
        merge_text_parts=merge_text_parts,
        pick_root_text=pick_root_text,
        pick_section_text=pick_section_text,
        compact_json=compact_json,
    )

    # 把 character_book 的分层结果合并进来（优先补充 description/personality 为空的情况）
    # 使用 merge_text_parts 去重拼接，避免重复内容。
    profile_text = merge_text_parts(feature_layers["profile"], cb_layers["profile"])
    personality_text = merge_text_parts(feature_layers["personality"], cb_layers["personality"])
    scenario_text = merge_text_parts(feature_layers["scenario"], cb_layers["scenario"])
    world_rules_text = merge_text_parts(feature_layers["world_rules"], cb_layers["world_rules"])
    example_text = merge_text_parts(feature_layers["examples"], cb_layers["examples"])
    post_history_text = merge_text_parts(feature_layers["post_history_rules"], cb_layers["post_history_rules"])
    opening_message = derive_opening_message(card)

    # subtitle / summary：优先用简介类文字，而不是人设档案原文
    # 优先级：creator_notes（创作者简介）> description 根段落 > first_mes 第一句话 > profile_text 前段
    def _first_readable_line(text: str, min_len: int = 8) -> str:
        """从文本里找第一行「可读中文/英文」自然语言行，跳过YAML/标题/代码块等。"""
        skip_prefixes = ("#", "```", "<", "{", "[", "!", "http", "---", "===", "//")
        skip_keywords = ("yaml", "name:", "gender:", "age:", "char:", "basic", "info", "setup", "discord", "qq群", "请勿", "禁止")
        for line in text.split("\n"):
            s = line.strip()
            if len(s) < min_len:
                continue
            low = s.lower()
            if any(s.startswith(p) for p in skip_prefixes):
                continue
            if any(kw in low for kw in skip_keywords):
                continue
            # 跳过含URL的行
            if "http" in s or "discord" in s.lower() or ".com" in s:
                continue
            # 跳过 YAML key 行（英文冒号或中文冒号后跟短key）
            for sep in (":", "："):
                if sep in s:
                    key_part = s.split(sep)[0].strip()
                    if len(key_part) < 20 and not any("\u4e00" <= c <= "\u9fff" for c in key_part[:6]):
                        # key中没有中文且很短，大概率是 YAML key
                        break
                    if len(key_part) < 20 and key_part.replace(" ", "").isalpha():
                        break
            else:
                return shorten_text(s, 80)
        return ""

    def _pick_summary() -> str:
        # 1. creator_notes 通常是作者写的简介，适合展示（排除以<开头的HTML和URL行）
        if creator_notes and not creator_notes.startswith("<"):
            first_line = creator_notes.strip().split("\n")[0]
            if len(first_line) > 8 and "http" not in first_line and "discord" not in first_line.lower():
                return shorten_text(first_line, 80)
        # 2. description 里的 persona/简介段（YAML 里最有代表性的自然语言字段）
        persona_match = None
        in_persona = False
        for line in description.split("\n"):
            s = line.strip()
            if s.startswith("persona:") or s.startswith("简介:") or s.startswith("简介："):
                in_persona = True
                continue
            if in_persona and s and not s.startswith(" ") and ":" in s:
                # 下一个 YAML key，停止
                break
            if in_persona and len(s) > 15 and any("\u4e00" <= c <= "\u9fff" for c in s):
                persona_match = shorten_text(s.lstrip("> "), 80)
                break
        if persona_match:
            return persona_match
        # 3. first_mes 的第一行可读自然语言（场景感强，最直观）
        if first_mes:
            line = _first_readable_line(first_mes, min_len=10)
            if line:
                return line
        # 4. description 里找可读自然语言行
        if description:
            line = _first_readable_line(description, min_len=10)
            if line:
                return line
        # 5. scenario 第一句
        if scenario_text:
            return shorten_text(scenario_text.split("\n")[0], 80)
        # 6. profile_text 前段（兜底）
        if profile_text:
            return shorten_text(profile_text, 60)
        return f"{display_name} 资产已导入"

    summary = _pick_summary()

    structured_outline = {
        "profile": profile_text,
        "personality": personality_text,
        "scenario": scenario_text,
        "world_rules": world_rules_text,
        "examples": example_text,
        "opening_message": opening_message,
        "post_history_rules": post_history_text,
    }

    # ── depth_prompt 支持（借鉴 SillyTavern v2 卡规范）──────────────────
    # 格式：extensions.depth_prompt = {prompt: str, depth: int, role: "system"|"user"|"assistant"}
    # 含义：把 prompt 插入「从聊天历史末尾倒数第 depth 条」的位置，比固定在 system prompt 顶部更自然
    depth_prompt_hint: dict | None = None
    if isinstance(extensions, dict):
        dp = extensions.get("depth_prompt")
        if isinstance(dp, dict):
            dp_text = normalize_text(dp.get("prompt") or "")
            dp_depth = dp.get("depth")
            dp_role = dp.get("role") or "system"
            # 只有 prompt 非空且 depth 是合法正整数时才保存
            if dp_text and isinstance(dp_depth, int) and dp_depth > 0:
                depth_prompt_hint = {
                    "prompt": dp_text,
                    "depth": dp_depth,
                    "role": dp_role if dp_role in ("system", "user", "assistant") else "system",
                }

    runtime_layers = {
        "asset_type": asset_type,
        "primary_system_prompt": system_prompt or build_default_system_prompt(asset_type, display_name),
        "base_profile": profile_text,
        "personality": personality_text,
        "scenario": scenario_text,
        "world_rules": world_rules_text,
        "examples": example_text,
        "post_history_rules": post_history_text,
        "alternate_greetings": alternates[:6],
        "opening_message": opening_message,
        "first_message": first_mes,
        "structured_outline": structured_outline,
        # ── World Info 位置层（常驻，按 ST position 字段区分）────────────────
        # world_info_before：注入在角色设定之前（优先级最高，世界观/背景）
        # world_info_after：注入在角色设定之后（补充规则、随机事件等）
        "world_info_before": cb_layers.get("world_info_before", ""),
        "world_info_after": cb_layers.get("world_info_after", ""),
        # ── 条件触发词条（运行时按关键词动态注入，不默认进 prompt）──────────
        # 格式：list[{keys, content, comment, position, insertion_order, ...}]
        "conditional_entries": cb_layers.get("conditional_entries", []),
        "extension_hints": {
            "has_regex_scripts": bool(extensions.get("regex_scripts")) if isinstance(extensions, dict) else False,
            "has_tavern_helper": bool(extensions.get("tavern_helper")) if isinstance(extensions, dict) else False,
            "world_binding": normalize_text(extensions.get("world")) if isinstance(extensions, dict) else "",
            # depth_prompt：非 None 时 prompt_assembler 会在历史记录中按深度插入
            "depth_prompt": depth_prompt_hint,
        },
    }

    diagnostics: list[dict[str, Any]] = []
    if source_meta.get("fallback_errors"):
        diagnostics.append({"level": "warning", "message": "PNG 解析失败后已自动回退 JSON", "detail": source_meta["fallback_errors"]})
    if not runtime_layers["base_profile"]:
        diagnostics.append({"level": "warning", "message": "未提取到稳定的人设底稿，后续更多依赖开场和扩展字段"})
    if asset_type in {"scenario", "system", "world"}:
        diagnostics.append({"level": "info", "message": f"当前资产识别为 {asset_type}，运行时更偏世界/剧情驱动，而不是单一人物对话"})

    asset_id = "asset_" + sha1(f"{source_meta.get('canonical_name', display_name)}::{source_meta.get('source_path', '')}".encode("utf-8")).hexdigest()[:12]
    subtitle = summary
    opening_line = runtime_layers["opening_message"] or f"{display_name} 已就位。"

    return {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "display_name": display_name,
        "abbr": display_name[:1] or "角",
        "subtitle": subtitle,
        "summary": summary,
        "tags": collect_tags(card, asset_type),
        "opening_message": opening_line,
        "system_prompt": runtime_layers["primary_system_prompt"],
        "raw_card": raw_card,
        "normalized_card": card,
        "normalized_blocks": {
            "description": collapse_blank_lines(strip_xml_wrappers(description)),
            "description_yaml": description_yaml,
            "description_sections": description_sections,
            "personality": personality,
            "scenario": scenario,
            "first_mes": first_mes,
            "mes_example": mes_example,
            "creator_notes": creator_notes,
            "alternate_greetings": alternates,
            "character_book": character_book_text,
            "post_history_instructions": post_history,
            "extensions": extensions,
        },
        "runtime_layers": runtime_layers,
        "source_meta": source_meta,
        "diagnostics": diagnostics,
    }


# ============================================================
# 去重与导入记录
# ============================================================
def normalize_variant_name(name: str) -> str:
    """把卡名清洗成适合去重比较的标准名。"""
    value = normalize_text(name).lower()
    value = re.sub(r"[_\-]+", " ", value)
    value = re.sub(r"\(.*?\)|（.*?）|\[.*?\]|【.*?】", " ", value)
    value = re.sub(r"\b(data|json|png|ver|version|beta|正式版|完整版|修复版|优化版|0\.\d+|v\d+(?:\.\d+)*)\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


ASSET_TYPE_PRIORITY = {
    "character": 50,
    "hybrid": 40,
    "system": 30,
    "world": 20,
    "scenario": 10,
}


def score_import_record(record: dict[str, Any]) -> tuple[int, int, int, int, str]:
    source_kind = record.get("source_kind", "png")
    embedded_format = normalize_text(record.get("embedded_format") or "")
    source_path = normalize_text(record.get("source_path") or "")
    asset_type = record.get("asset_type", "hybrid")
    subtitle = normalize_text(record.get("subtitle") or "")

    source_score = 2 if source_kind == "png" else 1
    format_score = 2 if embedded_format == "ccv3" else 1 if embedded_format == "chara" else 0
    asset_score = ASSET_TYPE_PRIORITY.get(asset_type, 0)
    title_bonus = 1 if any(flag in source_path for flag in ["正式", "complete", "final"]) or "正式" in subtitle else 0
    return (asset_score, source_score, format_score, title_bonus, source_path)


def build_import_record(source: dict[str, Any], sort_order: int) -> dict[str, Any]:
    raw_card, source_meta = load_card_source(source)
    structured = build_structured_asset(raw_card, source_meta)
    avatar_path = source_meta.get("avatar_path") or source_meta.get("png_path") or ""
    stable_key = normalize_variant_name(structured["display_name"] or source.get("canonical_name") or "") or source.get("canonical_name") or structured["display_name"]
    return {
        "id": "card_" + sha1(stable_key.encode("utf-8")).hexdigest()[:12],
        "name": structured["display_name"],
        "canonical_name": normalize_variant_name(structured["display_name"] or source.get("canonical_name") or ""),
        "abbr": structured["abbr"],
        "subtitle": structured["subtitle"],
        "avatar_path": avatar_path,
        "cover_path": avatar_path,
        "description": structured["summary"],
        "tags": structured["tags"],
        "opening_message": structured["opening_message"],
        "system_prompt": structured["system_prompt"],
        "sort_order": sort_order,
        "mock_reply_style": [
            "我在。你继续说。",
            "别急，这一段我接住。",
            "嗯，我知道你现在想要的是更真实的回应。",
            "继续，我会顺着这段关系往下接。",
        ],
        "asset_type": structured["asset_type"],
        "source_kind": source_meta.get("source_kind", "json"),
        "source_path": source_meta.get("source_path", ""),
        "embedded_format": source_meta.get("embedded_format", "json"),
        "raw_card_json": json.dumps(raw_card, ensure_ascii=False),
        "structured_asset_json": json.dumps(structured, ensure_ascii=False),
        "runtime_cache_json": json.dumps(structured["runtime_layers"], ensure_ascii=False),
        "import_diagnostics": json.dumps(structured["diagnostics"], ensure_ascii=False),
    }


def merge_variant_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = normalize_variant_name(record.get("canonical_name") or record.get("name") or "") or record.get("id", "")
        grouped.setdefault(key, []).append(record)

    merged_records: list[dict[str, Any]] = []
    for group_key, variants in grouped.items():
        if len(variants) == 1:
            record = dict(variants[0])
            record.pop("canonical_name", None)
            merged_records.append(record)
            continue

        ranked = sorted(variants, key=score_import_record, reverse=True)
        primary = dict(ranked[0])
        variant_sources = [
            {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "asset_type": item.get("asset_type", ""),
                "source_kind": item.get("source_kind", ""),
                "source_path": item.get("source_path", ""),
                "embedded_format": item.get("embedded_format", ""),
            }
            for item in ranked
        ]
        diagnostics = []
        try:
            diagnostics = json.loads(primary.get("import_diagnostics") or "[]")
        except json.JSONDecodeError:
            diagnostics = []
        diagnostics.append(
            {
                "level": "info",
                "message": f"已合并 {len(ranked)} 个同名/近似同名变体，当前保留更优主资产",
                "group_key": group_key,
                "variants": variant_sources,
            }
        )
        primary["import_diagnostics"] = json.dumps(diagnostics, ensure_ascii=False)
        primary.pop("canonical_name", None)
        merged_records.append(primary)

    return sorted(merged_records, key=lambda item: (int(item.get("sort_order", 0)), item.get("name", "").lower()))


def load_import_records(card_dir: Path, start_sort_order: int = 100) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, source in enumerate(discover_card_sources(card_dir), start=0):
        try:
            records.append(build_import_record(source, sort_order=start_sort_order + index))
        except Exception as exc:  # noqa: BLE001
            fallback_id = "card_" + sha1((normalize_variant_name(source["canonical_name"]) or source["canonical_name"]).encode("utf-8")).hexdigest()[:12]
            records.append(
                {
                    "id": fallback_id,
                    "name": source["canonical_name"],
                    "canonical_name": normalize_variant_name(source["canonical_name"]),
                    "abbr": source["canonical_name"][:1] or "卡",
                    "subtitle": f"导入失败：{exc}",
                    "avatar_path": str(source.get("png_path") or ""),
                    "cover_path": str(source.get("png_path") or ""),
                    "description": f"该卡目前导入失败，原因：{exc}",
                    "tags": ["import_error"],
                    "opening_message": f"{source['canonical_name']} 导入失败，需进一步排查。",
                    "system_prompt": build_default_system_prompt("hybrid", source["canonical_name"]),
                    "sort_order": start_sort_order + index,
                    "mock_reply_style": ["这张卡暂时没导入成功。"],
                    "asset_type": "hybrid",
                    "source_kind": source["primary_path"].suffix.lower().lstrip("."),
                    "source_path": str(source["primary_path"]),
                    "embedded_format": source["primary_path"].suffix.lower().lstrip("."),
                    "raw_card_json": "",
                    "structured_asset_json": "",
                    "runtime_cache_json": "",
                    "import_diagnostics": json.dumps([{"level": "error", "message": str(exc)}], ensure_ascii=False),
                }
            )
    return merge_variant_records(records)
