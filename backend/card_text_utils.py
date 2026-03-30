from __future__ import annotations

import json
import re
from typing import Any


def normalize_text(text: Any) -> str:
    """把任意输入清洗成适合后续处理的普通字符串。"""
    if text is None:
        return ""
    if isinstance(text, str):
        value = text
    else:
        value = json.dumps(text, ensure_ascii=False)

    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u3000", " ")
    return value.strip()


def collapse_blank_lines(text: str) -> str:
    """把多余空行压缩掉，避免 prompt 太空。"""
    return re.sub(r"\n{3,}", "\n\n", normalize_text(text))


def strip_xml_wrappers(text: str) -> str:
    """去掉角色卡里常见的 XML 包装标签，保留标签内的文本内容。

    SillyTavern 卡片里经常用 <personality>...</personality>、<description>...</description>
    等标签包裹内容。这些标签应该被去掉，只保留标签里的文本，否则会让模型看到字面 XML。

    保留有语义的少数标签（如代码块 <code>），但外层容器类标签全部清洗。
    """
    cleaned = normalize_text(text)
    # 常见容器/包装类标签（开闭标签均清除，保留内容）
    _XML_CONTAINER_TAGS = (
        r"info|character|content|summary|update|state|status|rules?"
        r"|description|personality|scenario|background|profile"
        r"|world|setting|lore|lorebook|lorentry|world_info"
        r"|example|mes_example|dialogue|sample"
        r"|thinking|think|thought|reasoning"
        r"|system|prompt|instruction|output"
        r"|section|block|segment|entry|item"
        r"|context|memory|history|note"
        r"|name|gender|age|height|weight|appearance|body"
        r"|relationship|relation|friend|enemy|lover"
        r"|goal|motivation|trait|quirk|habit|flaw"
        r"|opening|greeting|first_mes|first_message"
        r"|post_history|post_history_instructions"
    )
    cleaned = re.sub(
        rf"</?\s*(?:{_XML_CONTAINER_TAGS})\s*(?:\s+[^>]*)?\s*>\s*",
        "",
        cleaned,
        flags=re.I,
    )
    return cleaned.strip()


def remove_html_tags(text: str) -> str:
    """把纯展示型 HTML 剥掉，避免污染模型输入。"""
    cleaned = normalize_text(text)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.I)
    cleaned = re.sub(r"</p>|</div>|</li>|</section>|</article>|</header>", "\n", cleaned, flags=re.I)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return collapse_blank_lines(cleaned)


def shorten_text(text: str, limit: int = 220) -> str:
    """用于简介位，避免把长文整个塞到列表接口。"""
    compact = collapse_blank_lines(remove_html_tags(strip_xml_wrappers(text)))
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def ensure_list(value: Any) -> list[str]:
    """把单值/数组统一转成字符串数组。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [normalize_text(item) for item in value if normalize_text(item)]
    text = normalize_text(value)
    return [text] if text else []


def compact_json(value: Any, limit: int = 2000) -> str:
    """把复杂对象压成适中的 JSON 文本，防止塞太大。"""
    if value in (None, "", [], {}):
        return ""
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def merge_text_parts(*parts: Any) -> str:
    """把多个文本块拼成去重后的整洁文本。"""
    lines: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = collapse_blank_lines(remove_html_tags(strip_xml_wrappers(part or "")))
        if not text:
            continue
        for line in text.split("\n"):
            clean_line = line.strip()
            if not clean_line or clean_line in seen:
                continue
            seen.add(clean_line)
            lines.append(clean_line)
    return "\n".join(lines).strip()


def pick_root_text(sections: dict[str, str]) -> str:
    """取未命名根段落，常用于 description 兜底。"""
    return collapse_blank_lines(sections.get("__root__", "")).strip()


def split_structured_sections(text: str) -> dict[str, str]:
    """把 YAML 风格/标题风格长文切成 section，便于后续映射到不同 prompt 层。"""
    source = collapse_blank_lines(strip_xml_wrappers(text))
    if not source:
        return {}

    sections: dict[str, list[str]] = {}
    current_key = "__root__"
    sections[current_key] = []

    for raw_line in source.split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if sections[current_key] and sections[current_key][-1] != "":
                sections[current_key].append("")
            continue

        markdown_match = re.match(r"^(#{1,6}|[-*]{1,3})?\s*([\u4e00-\u9fa5A-Za-z0-9_/（）()【】\- ]{2,30})\s*[:：]\s*$", stripped)
        bracket_match = re.match(r"^[【\[](.*?)[】\]]\s*$", stripped)
        yaml_match = re.match(r"^([A-Za-z_][A-Za-z0-9_\- ]{1,40}|[\u4e00-\u9fa5A-Za-z0-9_\- ]{2,30})\s*:\s*$", stripped)
        if bracket_match:
            current_key = bracket_match.group(1).strip().lower()
            sections.setdefault(current_key, [])
            continue
        if markdown_match:
            current_key = markdown_match.group(2).strip().lower()
            sections.setdefault(current_key, [])
            continue
        if yaml_match and not re.search(r"https?://", stripped):
            current_key = yaml_match.group(1).strip().lower()
            sections.setdefault(current_key, [])
            continue

        sections.setdefault(current_key, []).append(stripped)

    return {
        key: collapse_blank_lines("\n".join(value)).strip()
        for key, value in sections.items()
        if collapse_blank_lines("\n".join(value)).strip()
    }


def pick_section_text(sections: dict[str, str], keywords: list[str]) -> str:
    """按关键词从拆分后的 section 中捞最匹配的一组内容。"""
    matches: list[str] = []
    seen: set[str] = set()
    for key, value in sections.items():
        lowered = key.lower()
        if any(keyword in lowered for keyword in keywords):
            normalized = collapse_blank_lines(value)
            if normalized and normalized not in seen:
                seen.add(normalized)
                matches.append(normalized)
    return "\n\n".join(matches).strip()


def expand_macros(text: str, char_name: str = "", user_name: str = "") -> str:
    """替换 SillyTavern 风格的模板变量（{{char}} / {{user}} 等）。

    酒馆角色卡里大量使用这类变量指代角色名和用户名，
    如果不替换直接送入模型，模型会看到字面 {{char}}，导致人设描述异常。
    """
    if not text:
        return text
    result = text
    if char_name:
        # {{char}} / {{Char}} / {{CHAR}} 均替换
        result = re.sub(r"\{\{\s*char\s*\}\}", char_name, result, flags=re.I)
    if user_name:
        # {{user}} / {{User}} / {{USER}} 均替换
        result = re.sub(r"\{\{\s*user\s*\}\}", user_name, result, flags=re.I)
    # 其余未知宏（{{xxx}}）用 <角色> / <用户> 占位，避免原文暴露
    if not char_name:
        result = re.sub(r"\{\{\s*char\s*\}\}", "<角色>", result, flags=re.I)
    if not user_name:
        result = re.sub(r"\{\{\s*user\s*\}\}", "<用户>", result, flags=re.I)
    return result


def extract_yaml_block(text: str) -> str:
    """尽量从 description 里提取 ```yaml``` 代码块，没有就回退到原文。"""
    source = normalize_text(text)
    if not source:
        return ""

    fenced = re.search(r"```ya?ml\s*(.*?)```", source, flags=re.I | re.S)
    if fenced:
        return collapse_blank_lines(strip_xml_wrappers(fenced.group(1)))

    stripped = strip_xml_wrappers(source)
    if ":" in stripped and stripped.count("\n") >= 3:
        return collapse_blank_lines(stripped)
    return ""
