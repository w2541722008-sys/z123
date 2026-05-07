#!/usr/bin/env python3
"""
暗夜裁决者角色卡一键导入脚本

从 dark_adjudicator_data.json 读取数据，通过管理后台API创建角色卡全部内容。

依赖：pip install requests
"""

import json
import os
import sys

try:
    import requests
except ImportError:
    print("❌ 缺少 requests 库，请先安装：pip install requests")
    sys.exit(1)

# ============================================================
# 配置
# ============================================================
BASE_URL = "https://lunawhisp.com/api"
CHARACTER_ID = "dark_adjudicator"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

if not ADMIN_EMAIL or not ADMIN_PASSWORD:
    print("❌ 请设置环境变量：")
    print("   export ADMIN_EMAIL='你的管理员邮箱'")
    print("   export ADMIN_PASSWORD='你的管理员密码'")
    sys.exit(1)

# 加载数据
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(SCRIPT_DIR, "dark_adjudicator_data.json")

with open(DATA_PATH, "r", encoding="utf-8") as f:
    DATA = json.load(f)

# ============================================================
# 登录
# ============================================================
session = requests.Session()

print("=" * 50)
print("🗡️  暗夜裁决者 · 角色卡导入")
print("=" * 50)

print("\n📌 步骤 1: 登录管理后台")
resp = session.post(f"{BASE_URL}/auth/login", json={
    "email": ADMIN_EMAIL,
    "password": ADMIN_PASSWORD,
})
if resp.status_code != 200:
    print(f"❌ 登录失败: {resp.status_code} {resp.text}")
    sys.exit(1)
print("✅ 登录成功")

me = session.get(f"{BASE_URL}/auth/me").json()
if not me.get("is_admin"):
    print(f"❌ 当前账号 {me.get('email')} 不是管理员")
    sys.exit(1)

# ============================================================
# 检查角色是否已存在
# ============================================================
print("\n📌 步骤 2: 检查角色是否已存在")
resp = session.get(f"{BASE_URL}/admin/character/{CHARACTER_ID}")
if resp.status_code == 200:
    print(f"⚠️  角色 '{CHARACTER_ID}' 已存在，先删除旧数据...")
    del_resp = session.delete(f"{BASE_URL}/admin/character/{CHARACTER_ID}")
    if del_resp.status_code == 200:
        print("✅ 旧角色已删除")
    else:
        print(f"❌ 删除失败: {del_resp.status_code} {del_resp.text}")
        sys.exit(1)
else:
    print("✅ 角色不存在，可以创建")

# ============================================================
# 创建角色核心
# ============================================================
print("\n📌 步骤 3: 创建角色核心")

char = DATA["character"]
resp = session.post(f"{BASE_URL}/admin/characters", json={
    "id": char["id"],
    "name": char["name"],
    "abbr": char["abbr"],
    "subtitle": char["subtitle"],
    "description": char["description"],
    "opening_message": DATA["opening_message"],
    "system_prompt": DATA["runtime_layers"]["primary_system_prompt"],
    "tags": json.dumps(char["tags"], ensure_ascii=False),
    "card_type": char["card_type"],
    "required_plan": char["required_plan"],
    "home_priority": char["home_priority"],
    "is_visible": char["is_visible"],
})
if resp.status_code != 200:
    print(f"❌ 创建角色失败: {resp.status_code} {resp.text}")
    sys.exit(1)
print(f"✅ 角色核心创建成功: {resp.json()}")

# ============================================================
# 更新 runtime_layers + 扩展字段
# ============================================================
print("\n📌 步骤 4: 更新 Runtime Layers + 扩展字段")

rl = DATA["runtime_layers"]
rl_updates = {f"rl__{k}": v for k, v in rl.items()}

resp = session.post(f"{BASE_URL}/admin/character/{CHARACTER_ID}", json={"updates": rl_updates})
if resp.status_code != 200:
    print(f"❌ 更新runtime_layers失败: {resp.status_code} {resp.text}")
else:
    print("✅ Runtime Layers 更新成功")

resp = session.post(f"{BASE_URL}/admin/character/{CHARACTER_ID}", json={"updates": {
    "affection_enabled": 1,
    "affection_rules_json": json.dumps(DATA["affection_rules"], ensure_ascii=False),
    "phase_behaviors_json": json.dumps(DATA["phase_behaviors"], ensure_ascii=False),
}})
if resp.status_code != 200:
    print(f"❌ 更新扩展字段失败: {resp.status_code} {resp.text}")
else:
    print("✅ 好感度规则 & 阶段行为 更新成功")

# ============================================================
# 创建剧情线
# ============================================================
print("\n📌 步骤 5: 创建剧情线")

storyline_ids = {}
for sl in DATA["storylines"]:
    resp = session.post(f"{BASE_URL}/admin/character/{CHARACTER_ID}/storylines", json=sl)
    if resp.status_code == 200:
        sid = resp.json()["id"]
        storyline_ids[sl["name"]] = sid
        print(f"  ✅ {sl['name']} (id={sid})")
    else:
        print(f"  ❌ {sl['name']}: {resp.status_code} {resp.text}")

# ============================================================
# 创建记忆分类
# ============================================================
print("\n📌 步骤 6: 创建记忆分类")

category_ids = {}
for cat in DATA["memory_categories"]:
    resp = session.post(f"{BASE_URL}/admin/character/{CHARACTER_ID}/memory-categories", json=cat)
    if resp.status_code == 200:
        cid = resp.json()["id"]
        category_ids[cat["name"]] = cid
        print(f"  ✅ {cat['name']} (id={cid})")
    else:
        print(f"  ❌ {cat['name']}: {resp.status_code} {resp.text}")

# ============================================================
# 创建记忆条目
# ============================================================
print("\n📌 步骤 7: 创建记忆条目")

memory_ids = []
for i, mem in enumerate(DATA["memories"]):
    cat_name = mem["category"]
    payload = {
        "keywords": mem["keywords"],
        "trigger_logic": mem["trigger_logic"],
        "content": mem["content"],
        "category_id": category_ids.get(cat_name),
        "position": mem["position"],
        "priority": mem["priority"],
        "is_active": mem["is_active"],
        "comment": mem["comment"],
        "selective": mem["selective"],
        "constant": mem["constant"],
        "sticky": mem["sticky"],
        "cooldown": mem["cooldown"],
    }
    resp = session.post(f"{BASE_URL}/admin/character/{CHARACTER_ID}/memories", json=payload)
    if resp.status_code == 200:
        mid = resp.json()["id"]
        memory_ids.append(mid)
        tag = "常驻" if mem["is_active"] else "解锁"
        print(f"  ✅ M{i} {tag} (id={mid}) {mem['comment']}")
    else:
        memory_ids.append(None)
        print(f"  ❌ M{i}: {resp.status_code} {resp.text}")

# ============================================================
# 创建开场白
# ============================================================
print("\n📌 步骤 8: 创建开场白")

greeting_ids = []
for i, g in enumerate(DATA["greetings"]):
    payload = {
        "story_phase": g["story_phase"],
        "mood": g["mood"],
        "content": g["content"],
        "storyline_id": storyline_ids.get(g["storyline"]) if g.get("storyline") else None,
        "priority": g["priority"],
        "is_active": g["is_active"],
    }
    resp = session.post(f"{BASE_URL}/admin/character/{CHARACTER_ID}/greetings", json=payload)
    if resp.status_code == 200:
        gid = resp.json()["id"]
        greeting_ids.append(gid)
        sl_tag = f"+{g['storyline']}" if g.get("storyline") else ""
        print(f"  ✅ G{i+1} {g['story_phase']}+{g['mood']}{sl_tag} (id={gid})")
    else:
        greeting_ids.append(None)
        print(f"  ❌ G{i+1}: {resp.status_code} {resp.text}")

# ============================================================
# 创建后置规则
# ============================================================
print("\n📌 步骤 9: 创建后置规则")

for i, rule in enumerate(DATA["post_rules"]):
    payload = {
        "name": rule["name"],
        "content": rule["content"],
        "storyline_id": storyline_ids.get(rule["storyline"]) if rule.get("storyline") else None,
        "story_phase": rule["story_phase"],
        "priority": rule["priority"],
        "is_active": rule["is_active"],
    }
    resp = session.post(f"{BASE_URL}/admin/character/{CHARACTER_ID}/post-rules", json=payload)
    if resp.status_code == 200:
        print(f"  ✅ R{i+1} {rule['name']} (id={resp.json().get('id')})")
    else:
        print(f"  ❌ R{i+1} {rule['name']}: {resp.status_code} {resp.text}")

# ============================================================
# 创建剧情事件
# ============================================================
print("\n📌 步骤 10: 创建剧情事件")

for i, evt in enumerate(DATA["story_events"]):
    # 根据 index 解析实际的 memory/greeting ID
    unlocked_mem = ",".join(
        str(memory_ids[idx]) for idx in evt["unlocked_memory_indices"]
        if idx < len(memory_ids) and memory_ids[idx]
    )
    unlocked_grt = ",".join(
        str(greeting_ids[idx]) for idx in evt["unlocked_greeting_indices"]
        if idx < len(greeting_ids) and greeting_ids[idx]
    )
    payload = {
        "title": evt["title"],
        "description": evt["description"],
        "trigger_score": evt["trigger_score"],
        "trigger_custom_key": evt["trigger_custom_key"],
        "unlocked_memory_ids": unlocked_mem,
        "unlocked_greeting_ids": unlocked_grt,
        "unlocked_storyline_id": storyline_ids.get(evt["unlocked_storyline"]),
        "event_content": evt["event_content"],
        "sort_order": evt["sort_order"],
        "is_active": evt["is_active"],
    }
    resp = session.post(f"{BASE_URL}/admin/character/{CHARACTER_ID}/story-events", json=payload)
    if resp.status_code == 200:
        print(f"  ✅ E{i+1} {evt['title']} (id={resp.json().get('id')})")
    else:
        print(f"  ❌ E{i+1} {evt['title']}: {resp.status_code} {resp.text}")

# ============================================================
# 验证
# ============================================================
print("\n📌 步骤 11: 验证数据完整性")

resp = session.get(f"{BASE_URL}/admin/character/{CHARACTER_ID}")
if resp.status_code == 200:
    char_data = resp.json()
    print(f"  ✅ 角色名: {char_data['name']}")
    print(f"  ✅ card_type: {char_data['card_type']}")
    print(f"  ✅ affection_enabled: {char_data['affection_enabled']}")
    ar = json.loads(char_data.get("affection_rules_json", "{}"))
    print(f"  ✅ daily_cap: {ar.get('daily_cap', '未设置')}")
    print(f"  ✅ allow_regression: {ar.get('allow_regression', '未设置')}")
else:
    print(f"  ❌ 验证失败: {resp.status_code}")

checks = {
    "storylines": (f"/admin/character/{CHARACTER_ID}/storylines", 4),
    "greetings": (f"/admin/character/{CHARACTER_ID}/greetings", 9),
    "post-rules": (f"/admin/character/{CHARACTER_ID}/post-rules", 9),
    "story-events": (f"/admin/character/{CHARACTER_ID}/story-events", 3),
    "memories": (f"/admin/character/{CHARACTER_ID}/memories", 11),
    "memory-categories": (f"/admin/character/{CHARACTER_ID}/memory-categories", 4),
}

for name, (path, expected) in checks.items():
    resp = session.get(f"{BASE_URL}{path}")
    if resp.status_code == 200:
        count = len(resp.json())
        status = "✅" if count == expected else "⚠️"
        print(f"  {status} {name}: {count}/{expected}")
    else:
        print(f"  ❌ {name}: 获取失败 {resp.status_code}")

print("\n" + "=" * 50)
print("🎉 暗夜裁决者角色卡导入完成！")
print("=" * 50)
