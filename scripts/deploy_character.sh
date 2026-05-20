#!/bin/bash
# 部署白小棠角色卡到生产环境（支持安全重复运行：先删后建，不产生重复数据）

echo "🚀 部署白小棠角色卡到生产环境"
echo "================================"
echo ""
echo "管理员邮箱: 773682014@qq.com"
read -sp "请输入管理员密码: " ADMIN_PASSWORD
echo ""
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 << PYTHON_EOF
import json
import os
import requests
import sys
import time

SCRIPT_DIR = "$SCRIPT_DIR"
BASE_URL = "https://lunawhisp.com/api"
ADMIN_EMAIL = "773682014@qq.com"
ADMIN_PASSWORD = "$ADMIN_PASSWORD"

def api_delete(url):
    """DELETE 请求，忽略 404"""
    resp = requests.delete(url, headers=headers)
    if resp.status_code not in (200, 404):
        print(f"   ⚠️  删除失败 {url}: {resp.status_code} {resp.text[:100]}")
    return resp

print("🔑 正在登录...")
resp = requests.post(f"{BASE_URL}/auth/login", json={
    "email": ADMIN_EMAIL,
    "password": ADMIN_PASSWORD
})

if resp.status_code != 200:
    print(f"❌ 登录失败: {resp.text}")
    sys.exit(1)

token = resp.json()['token']
print("✅ 登录成功！\n")

headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# 读取本地数据
with open(os.path.join(SCRIPT_DIR, 'bai_xiaotang_character_data.json'), 'r', encoding='utf-8') as f:
    data = json.load(f)
with open(os.path.join(SCRIPT_DIR, 'bai_xiaotang_advanced_config.json'), 'r', encoding='utf-8') as f:
    advanced = json.load(f)

char_id = data['id']

# ── 创建或更新角色主体 ──
print(f"📝 创建/更新角色: {data['name']}...")
resp = requests.post(f"{BASE_URL}/admin/characters", json={
    "id": data["id"], "name": data["name"], "abbr": data["abbr"],
    "subtitle": data["subtitle"], "avatar_url": data.get("avatar_url", ""),
    "cover_url": data.get("cover_url", ""), "description": data["description"],
    "system_prompt": data["system_prompt"], "opening_message": data["opening_message"],
    "tags": json.dumps(data["tags"], ensure_ascii=False),
    "card_type": data["card_type"], "required_plan": data["required_plan"],
    "home_priority": data["home_priority"], "is_visible": data["is_visible"]
}, headers=headers)

if resp.status_code == 200:
    print("✅ 角色创建成功")
elif resp.status_code == 409:
    print("⚠️  角色已存在，更新核心配置...")
else:
    print(f"❌ 创建失败: {resp.text}")
    sys.exit(1)

# 更新核心配置（affection_rules、phase_behaviors、life_profile、system_prompt 等）
print("📦 更新核心配置...")
resp = requests.post(f"{BASE_URL}/admin/character/{char_id}", json={
    "updates": {
        "system_prompt": data["system_prompt"],
        "opening_message": data["opening_message"],
        "description": data["description"],
        "affection_enabled": data["affection_enabled"],
        "affection_rules_json": json.dumps(data["affection_rules_json"], ensure_ascii=False),
        "phase_behaviors_json": json.dumps(data.get("phase_behaviors_json", {}), ensure_ascii=False),
        "life_profile_json": json.dumps(data["life_profile_json"], ensure_ascii=False)
    }
}, headers=headers)
if resp.status_code == 200:
    print("✅ 核心配置更新成功")
else:
    print(f"⚠️  核心配置更新返回 {resp.status_code}: {resp.text[:200]}")

# ── 辅助函数：清空并重建子资源 ──
def rebuild_resources(resource_name, list_path, delete_path_template, new_items):
    """GET 现有列表 → 逐条 DELETE → 逐条 POST 新数据"""
    print(f"\n🔄 同步{resource_name}（现有 → 删除 → 新建）...")

    # 1. 获取现有列表
    list_url = f"{BASE_URL}{list_path.format(char_id=char_id)}"
    resp = requests.get(list_url, headers=headers)
    existing = []
    if resp.status_code == 200:
        data_list = resp.json()
        if isinstance(data_list, dict):
            # 可能包裹在 data 或 items 字段中
            existing = data_list.get("data") or data_list.get("items") or []
            if not existing and isinstance(data_list, list):
                existing = data_list
        elif isinstance(data_list, list):
            existing = data_list

    # 2. 逐条删除现有数据
    deleted = 0
    for item in existing:
        item_id = item.get("id") or item.get(f"{resource_name.rstrip('s')}_id")
        if item_id:
            delete_url = BASE_URL + delete_path_template.format(char_id=char_id, id=item_id)
            api_delete(delete_url)
            deleted += 1
    if deleted > 0:
        print(f"   🗑️  删除 {deleted} 条旧{resource_name}")
    else:
        print(f"   📭 无旧{resource_name}需要删除")

    # 3. 逐条创建新数据
    created = 0
    for item in new_items:
        create_url = f"{BASE_URL}{list_path.format(char_id=char_id)}"
        resp = requests.post(create_url, json=item, headers=headers)
        if resp.status_code == 200:
            created += 1
        else:
            print(f"   ⚠️  创建{resource_name}失败: {resp.status_code} {resp.text[:100]}")
    print(f"   ✅ 创建 {created}/{len(new_items)} 条新{resource_name}")

# ── 同步各子资源 ──
rebuild_resources(
    "记忆条目",
    "/admin/character/{char_id}/memories",
    "/admin/character/{char_id}/memories/{id}",
    advanced["memory_entries"]
)

rebuild_resources(
    "开场白",
    "/admin/character/{char_id}/greetings",
    "/admin/character/{char_id}/greetings/{id}",
    advanced["greetings"]
)

rebuild_resources(
    "剧情线",
    "/admin/character/{char_id}/storylines",
    "/admin/character/{char_id}/storylines/{id}",
    advanced["storylines"]
)

# ── 剧情事件特殊处理：需要获取剧情线 DB ID 做 unlocked_storyline_id 映射 ──
print("\n🔄 同步剧情事件...")

# 获取新创建的剧情线 ID 映射
resp = requests.get(f"{BASE_URL}/admin/character/{char_id}/storylines", headers=headers)
sl_data = resp.json()
if isinstance(sl_data, dict):
    sl_data = sl_data.get("data") or sl_data.get("items") or []
sl_map = {s['storyline_id']: s['id'] for s in sl_data if s.get('storyline_id')}
# 取第一个剧情线作为默认（用于无解锁目标的普通事件）
default_sl_id = list(sl_map.values())[0] if sl_map else None

# 删除旧事件
list_url = f"{BASE_URL}/admin/character/{char_id}/story-events"
resp = requests.get(list_url, headers=headers)
existing = resp.json()
if isinstance(existing, dict):
    existing = existing.get("data") or existing.get("items") or []
elif isinstance(existing, list):
    existing = existing
for item in existing:
    eid = item.get("id")
    if eid:
        api_delete(f"{BASE_URL}{'/admin/character/{char_id}/story-events/{id}'.format(char_id=char_id, id=eid)}", headers)
        time.sleep(0.12)
print(f"   🗑️  删除 {len(existing)} 条旧剧情事件")

# 创建新事件（生产环境要求 unlocked_storyline_id 非空，需做映射兜底）
created = 0
for event in advanced["story_events"]:
    payload = dict(event)
    raw_sl = payload.get("unlocked_storyline_id")
    if raw_sl:
        mapped = sl_map.get(raw_sl, default_sl_id)
        payload["unlocked_storyline_id"] = mapped
    else:
        payload["unlocked_storyline_id"] = default_sl_id

    for attempt in range(3):
        resp = requests.post(list_url, json=payload, headers=headers)
        if resp.status_code == 200:
            created += 1
            break
        elif resp.status_code == 429:
            time.sleep(1)
        else:
            print(f"   ⚠️  事件 {event.get('title','?')} 失败: {resp.status_code}")
            break
    time.sleep(0.2)
print(f"   ✅ 创建 {created}/{len(advanced['story_events'])} 条新剧情事件")

rebuild_resources(
    "后置规则",
    "/admin/character/{char_id}/post-rules",
    "/admin/character/{char_id}/post-rules/{id}",
    advanced["post_rules"]
)

print("\n" + "="*60)
print("🎉 白小棠角色卡部署完成！")
print("="*60)
print(f"\n🌐 访问: https://lunawhisp.com/")
print(f"👤 角色: {data['name']} ({char_id})")
print(f"📊 记忆: {len(advanced['memory_entries'])}条 | 开场白: {len(advanced['greetings'])}条 | 剧情事件: {len(advanced['story_events'])}条")

PYTHON_EOF
