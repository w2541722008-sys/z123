#!/usr/bin/env python3
"""
云服务器上创建白小棠角色卡
直接连接数据库创建，无需 API token
"""

import json
import psycopg2
from psycopg2.extras import RealDictCursor
import os

# 读取环境变量
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "aifriend")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

print("🚀 开始创建白小棠角色卡...")

# 连接数据库
try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        cursor_factory=RealDictCursor
    )
    print("✅ 数据库连接成功")
except Exception as e:
    print(f"❌ 数据库连接失败: {e}")
    exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 读取角色数据
with open(os.path.join(SCRIPT_DIR, 'bai_xiaotang_character_data.json'), 'r', encoding='utf-8') as f:
    data = json.load(f)

char_id = data['id']
cur = conn.cursor()

# 检查是否已存在
cur.execute("SELECT id FROM characters WHERE id = %s", (char_id,))
if cur.fetchone():
    print(f"⚠️  角色 {char_id} 已存在，跳过创建")
    conn.close()
    exit(0)

print(f"📝 创建角色: {data['name']}")

# 插入角色
try:
    cur.execute("""
        INSERT INTO characters (
            id, name, abbr, subtitle, avatar_url, cover_url, description,
            system_prompt, opening_message, tags,
            card_type, required_plan, home_priority, is_visible, sort_order,
            alternate_greetings, asset_type, source_kind, source_path,
            embedded_format, structured_asset_json, runtime_cache_json,
            mock_reply_style, affection_enabled, import_locked, affection_rules_json,
            phase_behaviors_json, life_profile_json
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s::jsonb,
            %s, %s, %s, %s, %s,
            %s::jsonb, %s, %s, %s,
            %s, %s::jsonb, %s::jsonb,
            %s::jsonb, %s, %s, %s::jsonb,
            %s::jsonb, %s::jsonb
        )
    """, (
        data['id'], data['name'], data['abbr'], data['subtitle'],
        data.get('avatar_url', ''), data.get('cover_url', ''), data['description'],
        data['system_prompt'], data['opening_message'], json.dumps(data['tags'], ensure_ascii=False),
        data['card_type'], data['required_plan'], data['home_priority'], data['is_visible'], data['sort_order'],
        '[]', 'character', 'manual', '',
        'json', '{}', '{}',
        '[]', data['affection_enabled'], 0, json.dumps(data['affection_rules_json'], ensure_ascii=False),
        json.dumps(data.get('phase_behaviors_json', {}), ensure_ascii=False),
        json.dumps(data['life_profile_json'], ensure_ascii=False)
    ))

    conn.commit()
    print(f"✅ 角色创建成功: {data['name']} (ID: {char_id})")

except Exception as e:
    conn.rollback()
    print(f"❌ 创建失败: {e}")
    cur.close()
    conn.close()
    exit(1)

# 创建高级配置
print("\n📦 创建高级配置...")
with open(os.path.join(SCRIPT_DIR, 'bai_xiaotang_advanced_config.json'), 'r', encoding='utf-8') as f:
    advanced = json.load(f)

# 1. 创建记忆条目
print(f"  → 创建 {len(advanced['memory_entries'])} 个记忆条目...")
for entry in advanced['memory_entries']:
    try:
        cur.execute("""
            INSERT INTO character_memories (
                character_id, keywords, trigger_logic, content, position,
                priority, is_active, comment, selective, constant, sticky, cooldown,
                story_phase
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            char_id, entry['keywords'], entry['trigger_logic'], entry['content'], entry['position'],
            entry['priority'], entry['is_active'], entry.get('comment', ''),
            entry.get('selective', 1), entry.get('constant', 0), entry.get('sticky', 0), entry.get('cooldown', 0),
            entry.get('story_phase', None)
        ))
    except Exception as e:
        print(f"    ⚠️  记忆条目创建失败: {e}")

# 2. 创建开场白
print(f"  → 创建 {len(advanced['greetings'])} 个开场白...")
for greeting in advanced['greetings']:
    try:
        cur.execute("""
            INSERT INTO character_greetings (
                character_id, content, story_phase, mood, priority, is_active, comment
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            char_id, greeting['content'], greeting['story_phase'], greeting['mood'],
            greeting['priority'], greeting['is_active'], greeting.get('comment', '')
        ))
    except Exception as e:
        print(f"    ⚠️  开场白创建失败: {e}")

# 3. 创建剧情线
print(f"  → 创建 {len(advanced['storylines'])} 条剧情线...")
for storyline in advanced['storylines']:
    try:
        cur.execute("""
            INSERT INTO character_storylines (
                character_id, storyline_id, title, name, description,
                unlock_score, unlock_condition, stages, is_default, is_active, sort_order
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
        """, (
            char_id, storyline['storyline_id'], storyline['title'], storyline['name'],
            storyline['description'], storyline['unlock_score'], storyline.get('unlock_condition'),
            json.dumps(storyline['stages'], ensure_ascii=False),
            storyline['is_default'], storyline['is_active'], storyline['sort_order']
        ))
    except Exception as e:
        print(f"    ⚠️  剧情线创建失败: {e}")

# 4. 创建剧情事件
print(f"  → 创建 {len(advanced['story_events'])} 个剧情事件...")
for event in advanced['story_events']:
    try:
        cur.execute("""
            INSERT INTO character_story_events (
                character_id, title, description, trigger_score, trigger_custom_key,
                unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id,
                event_content, sort_order, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            char_id, event['title'], event['description'], event['trigger_score'],
            event.get('trigger_custom_key', ''), event.get('unlocked_memory_ids', ''),
            event.get('unlocked_greeting_ids', ''), event.get('unlocked_storyline_id'),
            event['event_content'], event['sort_order'], event['is_active']
        ))
    except Exception as e:
        print(f"    ⚠️  剧情事件创建失败: {e}")

# 5. 创建后置规则
print(f"  → 创建 {len(advanced['post_rules'])} 条后置规则...")
for rule in advanced['post_rules']:
    try:
        cur.execute("""
            INSERT INTO character_post_rules (
                character_id, name, content, priority, is_active
            ) VALUES (%s, %s, %s, %s, %s)
        """, (
            char_id, rule['name'], rule['content'], rule['priority'], rule['is_active']
        ))
    except Exception as e:
        print(f"    ⚠️  后置规则创建失败: {e}")

conn.commit()
cur.close()
conn.close()

print("\n" + "="*60)
print("🎉 白小棠角色卡创建完成！")
print("="*60)
print(f"\n角色ID: {char_id}")
print(f"角色名: {data['name']}")
print(f"记忆条目: {len(advanced['memory_entries'])} 个")
print(f"开场白: {len(advanced['greetings'])} 个")
print(f"剧情线: {len(advanced['storylines'])} 条")
print(f"剧情事件: {len(advanced['story_events'])} 个")
print(f"后置规则: {len(advanced['post_rules'])} 条")
print("\n✅ 现在可以在前端访问这个角色了！")
print("🌐 访问: https://lunawhisp.com/")
