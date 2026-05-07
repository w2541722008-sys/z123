#!/bin/bash
# 部署白小棠角色卡到生产环境

echo "🚀 部署白小棠角色卡到生产环境"
echo "================================"
echo ""
echo "管理员邮箱: 773682014@qq.com"
read -sp "请输入管理员密码: " ADMIN_PASSWORD
echo ""
echo ""

python3 << PYTHON_EOF
import json
import requests
import sys

BASE_URL = "https://lunawhisp.com/api"
ADMIN_EMAIL = "773682014@qq.com"
ADMIN_PASSWORD = "$ADMIN_PASSWORD"

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

# 读取数据
with open('bai_xiaotang_character_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
with open('bai_xiaotang_advanced_config.json', 'r', encoding='utf-8') as f:
    advanced = json.load(f)

# 创建角色
print(f"📝 创建角色: {data['name']}...")
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
    print("⚠️  角色已存在，继续更新配置")
else:
    print(f"❌ 创建失败: {resp.text}")
    sys.exit(1)

# 更新配置
print("📦 更新高级配置...")
requests.post(f"{BASE_URL}/admin/character/{data['id']}", json={
    "updates": {
        "affection_enabled": data["affection_enabled"],
        "affection_rules_json": json.dumps(data["affection_rules_json"], ensure_ascii=False),
        "phase_behaviors_json": json.dumps(data.get("phase_behaviors_json", {}), ensure_ascii=False),
        "life_profile_json": json.dumps(data["life_profile_json"], ensure_ascii=False)
    }
}, headers=headers)

# 创建记忆条目
print(f"📚 创建 {len(advanced['memory_entries'])} 个记忆条目...")
for entry in advanced["memory_entries"]:
    requests.post(f"{BASE_URL}/admin/character/{data['id']}/memory", json=entry, headers=headers)

# 创建开场白
print(f"💬 创建 {len(advanced['greetings'])} 个开场白...")
for greeting in advanced["greetings"]:
    requests.post(f"{BASE_URL}/admin/character/{data['id']}/greetings", json=greeting, headers=headers)

# 创建剧情线
print(f"📖 创建 {len(advanced['storylines'])} 条剧情线...")
for storyline in advanced["storylines"]:
    requests.post(f"{BASE_URL}/admin/character/{data['id']}/storylines", json=storyline, headers=headers)

# 创建剧情事件
print(f"🎬 创建 {len(advanced['story_events'])} 个剧情事件...")
for event in advanced["story_events"]:
    requests.post(f"{BASE_URL}/admin/character/{data['id']}/story-events", json=event, headers=headers)

# 创建后置规则
print(f"📋 创建 {len(advanced['post_rules'])} 条后置规则...")
for rule in advanced["post_rules"]:
    requests.post(f"{BASE_URL}/admin/character/{data['id']}/post-rules", json=rule, headers=headers)

print("\n" + "="*60)
print("🎉 白小棠角色卡部署完成！")
print("="*60)
print(f"\n🌐 访问: https://lunawhisp.com/")
print(f"👤 角色: {data['name']} ({data['id']})")

PYTHON_EOF
