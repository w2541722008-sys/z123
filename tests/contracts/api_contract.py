#!/usr/bin/env python3
"""
API 契约测试 - 验证前后端接口一致性

检查项：
1. 响应格式符合前端预期
2. 必需字段不缺失
3. 字段类型正确
4. 错误码符合约定
"""

import sys
import json
from typing import Any, Dict, List

# 前端期望的 API 响应格式（从前端代码提取）
API_CONTRACTS = {
    "GET /api/characters": {
        "success_fields": ["id", "name", "avatar_url", "subtitle", "tags"],
        "field_types": {
            "id": int,
            "name": str,
            "avatar_url": str,
            "is_visible": int,
            "home_priority": int,
        },
    },
    "GET /api/characters/{id}": {
        "success_fields": ["id", "name", "opening_message", "system_prompt"],
        "field_types": {
            "id": int,
            "name": str,
            "opening_message": str,
            "affection_enabled": int,
        },
    },
    "POST /api/chat/send": {
        "success_fields": ["content", "role"],
        "field_types": {"content": str, "role": str},
    },
    "GET /api/chat/history": {
        "success_fields": [],  # 数组响应
        "array_item_fields": ["id", "content", "role", "created_at"],
    },
    "GET /api/admin/characters": {
        "success_fields": ["id", "name", "card_type", "created_at"],
        "field_types": {
            "id": int,
            "card_type": str,
            "affection_enabled": int,
        },
    },
}


def validate_response(endpoint: str, response: Dict[str, Any]) -> List[str]:
    """验证响应格式"""
    errors = []
    contract = API_CONTRACTS.get(endpoint)
    if not contract:
        return [f"⚠️  未定义契约: {endpoint}"]

    # 检查必需字段
    for field in contract.get("success_fields", []):
        if field not in response:
            errors.append(f"❌ 缺少字段: {field}")

    # 检查字段类型
    for field, expected_type in contract.get("field_types", {}).items():
        if field in response:
            actual_value = response[field]
            # 允许 None 值
            if actual_value is not None and not isinstance(actual_value, expected_type):
                errors.append(
                    f"❌ 字段类型错误: {field} 期望 {expected_type.__name__}，实际 {type(actual_value).__name__}"
                )

    # 检查数组项字段
    if "array_item_fields" in contract and isinstance(response, list):
        if len(response) > 0:
            item = response[0]
            for field in contract["array_item_fields"]:
                if field not in item:
                    errors.append(f"❌ 数组项缺少字段: {field}")

    return errors


def main():
    """
    使用方式：
    1. 启动开发服务器
    2. 运行此脚本，自动调用 API 并验证响应

    或者手动传入响应 JSON：
    echo '{"id":1,"name":"test"}' | python3 tests/api_contract.py "GET /api/characters/{id}"
    """
    if len(sys.argv) < 2:
        print("用法: python3 api_contract.py <endpoint>")
        print("示例: echo '{...}' | python3 api_contract.py 'GET /api/characters'")
        sys.exit(1)

    endpoint = sys.argv[1]
    try:
        response = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("❌ 无效的 JSON 输入")
        sys.exit(1)

    errors = validate_response(endpoint, response)
    if errors:
        print(f"\n❌ {endpoint} 契约验证失败:\n")
        for error in errors:
            print(f"  {error}")
        sys.exit(1)
    else:
        print(f"✅ {endpoint} 契约验证通过")
        sys.exit(0)


if __name__ == "__main__":
    main()
