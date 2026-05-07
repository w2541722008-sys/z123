#!/usr/bin/env python3
"""
创建白小棠角色卡的脚本
使用方法：python3 create_bai_xiaotang.py <admin_token>
"""

import json
import sys
import requests

if len(sys.argv) < 2:
    print("使用方法: python3 create_bai_xiaotang.py <admin_token>")
    print("请先登录管理后台获取 token")
    sys.exit(1)

ADMIN_TOKEN = sys.argv[1]
BASE_URL = "http://localhost:8000/api"

headers = {
    "Authorization": f"Bearer {ADMIN_TOKEN}",
    "Content-Type": "application/json"
}

# 读取角色数据
with open('bai_xiaotang_character_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 1. 创建角色
print("正在创建角色...")
create_payload = {
    "id": data["id"],
    "name": data["name"],
    "abbr": data["abbr"],
    "subtitle": data["subtitle"],
    "avatar_url": data.get("avatar_url", ""),
    "cover_url": data.get("cover_url", ""),
    "description": data["description"],
    "system_prompt": data["system_prompt"],
    "opening_message": data["opening_message"],
    "tags": json.dumps(data["tags"], ensure_ascii=False),
    "card_type": data["card_type"],
    "required_plan": data["required_plan"],
    "home_priority": data["home_priority"],
    "is_visible": data["is_visible"]
}

resp = requests.post(f"{BASE_URL}/admin/characters", json=create_payload, headers=headers)
if resp.status_code == 200:
    print(f"✅ 角色创建成功: {data['name']}")
elif resp.status_code == 409:
    print(f"⚠️  角色已存在: {data['id']}")
else:
    print(f"❌ 创建失败: {resp.status_code} - {resp.text}")
    sys.exit(1)

# 2. 更新好感度规则和人生档案
print("正在更新高级配置...")
update_payload = {
    "updates": {
        "affection_enabled": data["affection_enabled"],
        "affection_rules_json": json.dumps(data["affection_rules_json"], ensure_ascii=False),
        "phase_behaviors_json": json.dumps(data.get("phase_behaviors_json", {}), ensure_ascii=False),
        "life_profile_json": json.dumps(data["life_profile_json"], ensure_ascii=False)
    }
}

resp = requests.post(f"{BASE_URL}/admin/character/{data['id']}", json=update_payload, headers=headers)
if resp.status_code == 200:
    print("✅ 高级配置更新成功")
else:
    print(f"⚠️  高级配置更新失败: {resp.status_code} - {resp.text}")

# 3. 创建记忆条目
print("\n正在创建记忆条目...")
with open('bai_xiaotang_advanced_config.json', 'r', encoding='utf-8') as f:
    advanced = json.load(f)

for idx, entry in enumerate(advanced["memory_entries"], 1):
    resp = requests.post(
        f"{BASE_URL}/admin/character/{data['id']}/memory",
        json=entry,
        headers=headers
    )
    if resp.status_code == 200:
        print(f"  ✅ 记忆条目 {idx}/{len(advanced['memory_entries'])}: {entry['comment']}")
    else:
        print(f"  ❌ 记忆条目 {idx} 失败: {resp.text}")

# 4. 创建开场白变体
print("\n正在创建开场白变体...")
for idx, greeting in enumerate(advanced["greetings"], 1):
    resp = requests.post(
        f"{BASE_URL}/admin/character/{data['id']}/greetings",
        json=greeting,
        headers=headers
    )
    if resp.status_code == 200:
        print(f"  ✅ 开场白 {idx}/{len(advanced['greetings'])}: {greeting['comment']}")
    else:
        print(f"  ❌ 开场白 {idx} 失败: {resp.text}")

# 5. 创建剧情线
print("\n正在创建剧情线...")
for idx, storyline in enumerate(advanced["storylines"], 1):
    resp = requests.post(
        f"{BASE_URL}/admin/character/{data['id']}/storylines",
        json=storyline,
        headers=headers
    )
    if resp.status_code == 200:
        print(f"  ✅ 剧情线 {idx}/{len(advanced['storylines'])}: {storyline['title']}")
    else:
        print(f"  ❌ 剧情线 {idx} 失败: {resp.text}")

# 6. 创建剧情事件
print("\n正在创建剧情事件...")
for idx, event in enumerate(advanced["story_events"], 1):
    resp = requests.post(
        f"{BASE_URL}/admin/character/{data['id']}/story-events",
        json=event,
        headers=headers
    )
    if resp.status_code == 200:
        print(f"  ✅ 剧情事件 {idx}/{len(advanced['story_events'])}: {event['title']}")
    else:
        print(f"  ❌ 剧情事件 {idx} 失败: {resp.text}")

# 7. 创建后置规则
print("\n正在创建后置规则...")
for idx, rule in enumerate(advanced["post_rules"], 1):
    resp = requests.post(
        f"{BASE_URL}/admin/character/{data['id']}/post-rules",
        json=rule,
        headers=headers
    )
    if resp.status_code == 200:
        print(f"  ✅ 后置规则 {idx}/{len(advanced['post_rules'])}: {rule['name']}")
    else:
        print(f"  ❌ 后置规则 {idx} 失败: {resp.text}")

print("\n" + "="*50)
print("🎉 白小棠角色卡创建完成！")
print("="*50)
print(f"\n角色ID: {data['id']}")
print(f"角色名: {data['name']}")
print(f"记忆条目: {len(advanced['memory_entries'])} 个")
print(f"开场白: {len(advanced['greetings'])} 个")
print(f"剧情线: {len(advanced['storylines'])} 条")
print(f"剧情事件: {len(advanced['story_events'])} 个")
print(f"后置规则: {len(advanced['post_rules'])} 条")
print("\n现在可以在前端访问这个角色了！")
