"""
JSON 工具函数
提取重复的 JSON 解析逻辑，统一管理

本模块提供的函数兼容以下输入类型：
- None
- 原生 Python list/dict（psycopg2 自动解析的结果）
- JSON 字符串

所有函数均支持 fallback 参数，确保现有代码无需改动即可迁移
"""
import json
from typing import Any, Dict, List, Optional


def parse_json_list(text: Any, fallback: Optional[List[Any]] = None) -> List[Any]:
    """
    安全解析 JSON 数组。
    
    兼容多种输入类型：
    - None → fallback
    - list → list（直接返回）
    - str → json.loads(text)
    - 其他 → fallback
    
    使用场景：
    - psycopg2 从数据库返回的 json 类型列可能已经是 list/dict
    - 用户输入的字符串需要 JSON 解析
    - 需要统一处理所有可能的输入形式
    
    Args:
        text: 待解析的数据（字符串、list、dict 或 None）
        fallback: 解析失败时的默认值（默认 []）
    
    Returns:
        解析后的列表，若无法解析则返回 fallback
    
    Examples:
        >>> parse_json_list(None)
        []
        >>> parse_json_list([1, 2, 3])
        [1, 2, 3]
        >>> parse_json_list('[1, 2, 3]')
        [1, 2, 3]
        >>> parse_json_list('invalid', fallback=['default'])
        ['default']
    """
    fallback = fallback or []
    
    # psycopg2 对 json/jsonb 类型会自动解析为 Python 对象，直接判断类型即可
    if isinstance(text, list):
        return text
    if isinstance(text, dict):
        return list(fallback)
    
    raw = (text or "").strip() if isinstance(text, str) else ""
    if not raw:
        return list(fallback)
    
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return list(fallback)
    
    return value if isinstance(value, list) else list(fallback)


def parse_json_object(text: Any, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    安全解析 JSON 对象。
    
    兼容多种输入类型：
    - None → fallback
    - dict → dict（直接返回）
    - str → json.loads(text)
    - 其他 → fallback
    
    使用场景：
    - psycopg2 从数据库返回的 jsonb 类型列可能已经是 dict
    - 用户输入的字符串需要 JSON 解析
    - 需要统一处理所有可能的输入形式
    
    Args:
        text: 待解析的数据（字符串、dict、list 或 None）
        fallback: 解析失败时的默认值（默认 {}）
    
    Returns:
        解析后的字典，若无法解析则返回 fallback
    
    Examples:
        >>> parse_json_object(None)
        {}
        >>> parse_json_object({'a': 1})
        {'a': 1}
        >>> parse_json_object('{"a": 1}')
        {'a': 1}
        >>> parse_json_object('invalid', fallback={'default': True})
        {'default': True}
    """
    fallback = fallback or {}
    
    # psycopg2 对 json/jsonb 类型会自动解析为 Python 对象，直接判断类型即可
    if isinstance(text, dict):
        return text
    if isinstance(text, list):
        return dict(fallback)
    
    raw = (text or "").strip() if isinstance(text, str) else ""
    if not raw:
        return dict(fallback)
    
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return dict(fallback)
    
    return value if isinstance(value, dict) else dict(fallback)


def to_json_string(data: Any, default_on_error: str = '{}') -> str:
    """
    将任意数据转换为 JSON 字符串
    
    Args:
        data: 待转换的数据
        default_on_error: 转换失败时的默认值
    
    Returns:
        JSON 字符串，若转换失败则返回 default_on_error
    
    Examples:
        >>> to_json_string({'a': 1})
        '{"a": 1}'
        >>> to_json_string([1, 2, 3])
        '[1, 2, 3]'
    """
    try:
        return json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        return default_on_error
