#!/usr/bin/env python3
"""
数据库迁移脚本：SQLite → Supabase (PostgreSQL)
用途：将本地 SQLite 数据库迁移到云端 Supabase
"""

import sqlite3
import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv
from datetime import datetime
import uuid

# 加载环境变量
load_dotenv()

# 数据库连接配置
SQLITE_DB = os.getenv("SQLITE_DB_PATH", "data/aifriend.db")
POSTGRES_URL = os.getenv("DATABASE_URL")

if not POSTGRES_URL:
    print("❌ 错误：未找到 DATABASE_URL 环境变量")
    print("请在 .env 文件中配置 Supabase 数据库连接字符串")
    exit(1)

def connect_sqlite():
    """连接 SQLite 数据库"""
    if not os.path.exists(SQLITE_DB):
        print(f"❌ 错误：SQLite 数据库文件不存在: {SQLITE_DB}")
        exit(1)
    return sqlite3.connect(SQLITE_DB)

def connect_postgres():
    """连接 PostgreSQL 数据库"""
    try:
        # 解析连接字符串，提取主机名并解析为 IPv4 地址
        import socket
        from urllib.parse import urlparse, parse_qs
        
        parsed = urlparse(POSTGRES_URL)
        hostname = parsed.hostname
        
        # 强制解析为 IPv4 地址
        try:
            ipv4_addr = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
            print(f"   🔍 解析主机名 {hostname} -> {ipv4_addr} (IPv4)")
            
            # 重建连接字符串，使用 IPv4 地址
            postgres_url_ipv4 = POSTGRES_URL.replace(hostname, ipv4_addr)
            return psycopg2.connect(postgres_url_ipv4)
        except socket.gaierror:
            # 如果无法解析，尝试直接连接
            print(f"   ⚠️  无法解析为 IPv4，尝试直接连接...")
            return psycopg2.connect(POSTGRES_URL)
            
    except Exception as e:
        print(f"❌ 错误：无法连接到 Supabase 数据库: {e}")
        print("\n💡 故障排除建议：")
        print("1. 检查 DATABASE_URL 是否正确")
        print("2. 检查服务器网络连接")
        print("3. 尝试在服务器上执行: ping -4 db.anqzfofujscudurgvjbk.supabase.co")
        exit(1)

def int_to_uuid(int_id):
    """将整数 ID 转换为 UUID"""
    # 使用命名空间 UUID 和整数 ID 生成确定性的 UUID
    namespace = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')  # DNS namespace
    return str(uuid.uuid5(namespace, str(int_id)))

def clean_timestamp(value, use_default=False):
    """清理时间戳值，将空字符串转换为 None 或默认值"""
    from datetime import datetime
    if value == "" or value is None:
        if use_default:
            return datetime.now().isoformat()
        return None
    return value

def int_to_bool(value):
    """将整数转换为布尔值"""
    if value is None:
        return False
    return bool(value)

def get_table_columns(conn, table_name):
    """获取表的列名"""
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cur.fetchall()]

def migrate_users(sqlite_conn, pg_conn):
    """迁移用户表"""
    print("\n📦 迁移用户表 (users)...")
    
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()
    
    # 获取 SQLite 表的实际列
    sqlite_columns = get_table_columns(sqlite_conn, 'users')
    print(f"   📋 SQLite users 表列: {', '.join(sqlite_columns)}")
    
    # 定义需要的列和默认值
    required_columns = {
        'id': None,
        'email': None,
        'password_hash': None,
        'nickname': None,
        'avatar_url': None,  # 可能不存在
        'plan_type': 'free',
        'plan_expires_at': None,
        'created_at': None,
        'updated_at': None
    }
    
    # 构建 SELECT 语句，只选择存在的列
    select_parts = []
    for col in required_columns.keys():
        if col in sqlite_columns:
            select_parts.append(col)
        else:
            # 使用默认值
            default_val = required_columns[col]
            if default_val is None:
                select_parts.append(f"NULL as {col}")
            else:
                select_parts.append(f"'{default_val}' as {col}")
    
    query = f"SELECT {', '.join(select_parts)} FROM users"
    sqlite_cur.execute(query)
    rows = sqlite_cur.fetchall()
    
    if not rows:
        print("   ⚠️  没有用户数据需要迁移")
        return
    
    # 插入到 PostgreSQL
    success_count = 0
    for row in rows:
        try:
            # 将整数 ID 转换为 UUID，清理时间戳
            row_list = list(row)
            if row_list[0] is not None and isinstance(row_list[0], int):
                row_list[0] = int_to_uuid(row_list[0])
            # 清理时间戳字段 (plan_expires_at, created_at, updated_at)
            row_list[6] = clean_timestamp(row_list[6])
            row_list[7] = clean_timestamp(row_list[7])
            row_list[8] = clean_timestamp(row_list[8])
            
            pg_cur.execute("""
                INSERT INTO users (id, email, password_hash, nickname, avatar_url, plan_type, plan_expires_at, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    email = EXCLUDED.email,
                    password_hash = EXCLUDED.password_hash,
                    nickname = EXCLUDED.nickname,
                    avatar_url = EXCLUDED.avatar_url,
                    plan_type = EXCLUDED.plan_type,
                    plan_expires_at = EXCLUDED.plan_expires_at,
                    updated_at = EXCLUDED.updated_at
            """, tuple(row_list))
            success_count += 1
        except Exception as e:
            print(f"   ⚠️  跳过用户 {row[1] if len(row) > 1 else 'unknown'}: {e}")
    
    pg_conn.commit()
    print(f"   ✅ 成功迁移 {success_count}/{len(rows)} 个用户")

def migrate_characters(sqlite_conn, pg_conn):
    """迁移角色表"""
    print("\n📦 迁移角色表 (characters)...")
    
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()
    
    # 获取 SQLite 表的实际列
    sqlite_columns = get_table_columns(sqlite_conn, 'characters')
    print(f"   📋 SQLite characters 表列: {', '.join(sqlite_columns)}")
    
    # 定义需要的列和默认值
    required_columns = {
        'id': None,
        'name': None,
        'subtitle': '',
        'avatar_url': None,
        'cover_url': None,
        'description': '',
        'tags': '',
        'opening_message': '',
        'system_prompt': '',
        'is_public': False,  # 可能不存在
        'sort_order': 0,
        'created_at': None,
        'updated_at': None
    }
    
    # 构建 SELECT 语句
    select_parts = []
    for col in required_columns.keys():
        if col in sqlite_columns:
            select_parts.append(col)
        else:
            default_val = required_columns[col]
            if default_val is None:
                select_parts.append(f"NULL as {col}")
            elif isinstance(default_val, bool):
                select_parts.append(f"{1 if default_val else 0} as {col}")
            elif isinstance(default_val, str):
                select_parts.append(f"'{default_val}' as {col}")
            else:
                select_parts.append(f"{default_val} as {col}")
    
    query = f"SELECT {', '.join(select_parts)} FROM characters"
    sqlite_cur.execute(query)
    rows = sqlite_cur.fetchall()
    
    if not rows:
        print("   ⚠️  没有角色数据需要迁移")
        return
    
    success_count = 0
    for row in rows:
        try:
            # 将整数 ID 转换为 UUID，布尔值转换，清理时间戳
            row_list = list(row)
            if row_list[0] is not None and isinstance(row_list[0], int):
                row_list[0] = int_to_uuid(row_list[0])
            # 转换 is_public 为布尔值
            row_list[9] = int_to_bool(row_list[9])
            # 清理时间戳字段 (created_at, updated_at) - 使用默认值因为这些字段是 NOT NULL
            row_list[11] = clean_timestamp(row_list[11], use_default=True)
            row_list[12] = clean_timestamp(row_list[12], use_default=True)
            
            pg_cur.execute("""
                INSERT INTO characters (id, name, subtitle, avatar_url, cover_url, description, tags,
                                       opening_message, system_prompt, is_public, sort_order, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    subtitle = EXCLUDED.subtitle,
                    avatar_url = EXCLUDED.avatar_url,
                    cover_url = EXCLUDED.cover_url,
                    description = EXCLUDED.description,
                    tags = EXCLUDED.tags,
                    opening_message = EXCLUDED.opening_message,
                    system_prompt = EXCLUDED.system_prompt,
                    is_public = EXCLUDED.is_public,
                    sort_order = EXCLUDED.sort_order,
                    updated_at = EXCLUDED.updated_at
            """, tuple(row_list))
            success_count += 1
        except Exception as e:
            print(f"   ⚠️  跳过角色 {row[1] if len(row) > 1 else 'unknown'}: {e}")
    
    pg_conn.commit()
    print(f"   ✅ 成功迁移 {success_count}/{len(rows)} 个角色")

def migrate_chat_messages(sqlite_conn, pg_conn):
    """迁移聊天消息表"""
    print("\n📦 迁移聊天消息表 (chat_messages)...")
    
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()
    
    try:
        # 获取 SQLite 表的实际列
        sqlite_columns = get_table_columns(sqlite_conn, 'chat_messages')
        print(f"   📋 SQLite chat_messages 表列: {', '.join(sqlite_columns)}")
        
        # 定义需要的列和默认值
        required_columns = {
            'id': None,
            'user_id': None,
            'character_id': None,
            'role': None,
            'content': None,
            'seq': 0,  # 可能不存在
            'token_count': 0,
            'is_summarized': False,
            'created_at': None
        }
        
        # 构建 SELECT 语句
        select_parts = []
        for col in required_columns.keys():
            if col in sqlite_columns:
                select_parts.append(col)
            else:
                default_val = required_columns[col]
                if default_val is None:
                    select_parts.append(f"NULL as {col}")
                elif isinstance(default_val, bool):
                    select_parts.append(f"{1 if default_val else 0} as {col}")
                else:
                    select_parts.append(f"{default_val} as {col}")
        
        query = f"SELECT {', '.join(select_parts)} FROM chat_messages"
        sqlite_cur.execute(query)
        rows = sqlite_cur.fetchall()
        
        if not rows:
            print("   ⚠️  没有聊天消息需要迁移")
            return
        
        success_count = 0
        for row in rows:
            try:
                # 转换所有 ID 字段为 UUID，布尔值，时间戳
                row_list = list(row)
                # id, user_id, character_id 都需要转换
                if row_list[0] is not None and isinstance(row_list[0], int):
                    row_list[0] = int_to_uuid(row_list[0])
                if row_list[1] is not None and isinstance(row_list[1], int):
                    row_list[1] = int_to_uuid(row_list[1])
                if row_list[2] is not None and isinstance(row_list[2], int):
                    row_list[2] = int_to_uuid(row_list[2])
                # 转换 is_summarized 为布尔值
                row_list[7] = int_to_bool(row_list[7])
                # 清理时间戳字段 (created_at)
                row_list[8] = clean_timestamp(row_list[8])
                
                pg_cur.execute("""
                    INSERT INTO chat_messages (id, user_id, character_id, role, content, seq, token_count, is_summarized, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                """, tuple(row_list))
                success_count += 1
            except Exception as e:
                print(f"   ⚠️  跳过消息: {e}")
        
        pg_conn.commit()
        print(f"   ✅ 成功迁移 {success_count}/{len(rows)} 条聊天消息")
    except sqlite3.OperationalError as e:
        print(f"   ⚠️  表不存在或查询失败: {e}")

def migrate_chat_summaries(sqlite_conn, pg_conn):
    """迁移聊天摘要表"""
    print("\n📦 迁移聊天摘要表 (chat_summaries)...")
    
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()
    
    try:
        sqlite_cur.execute("""
            SELECT id, user_id, character_id, summary, memory_version, last_message_id, 
                   last_summarized_at, created_at, updated_at
            FROM chat_summaries
        """)
        rows = sqlite_cur.fetchall()
        
        if not rows:
            print("   ⚠️  没有聊天摘要需要迁移")
            return
        
        success_count = 0
        for row in rows:
            try:
                # 转换所有 ID 字段为 UUID，清理时间戳
                row_list = list(row)
                # id, user_id, character_id, last_message_id 都需要转换
                if row_list[0] is not None and isinstance(row_list[0], int):
                    row_list[0] = int_to_uuid(row_list[0])
                if row_list[1] is not None and isinstance(row_list[1], int):
                    row_list[1] = int_to_uuid(row_list[1])
                if row_list[2] is not None and isinstance(row_list[2], int):
                    row_list[2] = int_to_uuid(row_list[2])
                if row_list[5] is not None and isinstance(row_list[5], int):
                    row_list[5] = int_to_uuid(row_list[5])
                # 清理时间戳字段 (last_summarized_at, created_at, updated_at)
                row_list[6] = clean_timestamp(row_list[6])
                row_list[7] = clean_timestamp(row_list[7])
                row_list[8] = clean_timestamp(row_list[8])
                
                pg_cur.execute("""
                    INSERT INTO chat_summaries (id, user_id, character_id, summary, memory_version, 
                                               last_message_id, last_summarized_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, character_id) DO UPDATE SET
                        summary = EXCLUDED.summary,
                        memory_version = EXCLUDED.memory_version,
                        last_message_id = EXCLUDED.last_message_id,
                        last_summarized_at = EXCLUDED.last_summarized_at,
                        updated_at = EXCLUDED.updated_at
                """, tuple(row_list))
                success_count += 1
            except Exception as e:
                print(f"   ⚠️  跳过摘要: {e}")
        
        pg_conn.commit()
        print(f"   ✅ 成功迁移 {success_count}/{len(rows)} 条聊天摘要")
    except sqlite3.OperationalError as e:
        print(f"   ⚠️  表不存在或查询失败: {e}")

def migrate_user_character_profiles(sqlite_conn, pg_conn):
    """迁移用户角色配置表"""
    print("\n📦 迁移用户角色配置表 (user_character_profiles)...")
    
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()
    
    try:
        sqlite_cur.execute("""
            SELECT id, user_id, character_id, user_name, user_persona, relationship_context, created_at, updated_at
            FROM user_character_profiles
        """)
        rows = sqlite_cur.fetchall()
        
        if not rows:
            print("   ⚠️  没有用户角色配置需要迁移")
            return
        
        success_count = 0
        for row in rows:
            try:
                # 转换所有 ID 字段为 UUID
                row_list = list(row)
                # id, user_id, character_id 都需要转换
                if row_list[0] is not None and isinstance(row_list[0], int):
                    row_list[0] = int_to_uuid(row_list[0])
                if row_list[1] is not None and isinstance(row_list[1], int):
                    row_list[1] = int_to_uuid(row_list[1])
                if row_list[2] is not None and isinstance(row_list[2], int):
                    row_list[2] = int_to_uuid(row_list[2])
                # 清理时间戳字段 (created_at, updated_at)
                row_list[6] = clean_timestamp(row_list[6])
                row_list[7] = clean_timestamp(row_list[7])
                
                pg_cur.execute("""
                    INSERT INTO user_character_profiles (id, user_id, character_id, user_name, user_persona, 
                                                        relationship_context, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, character_id) DO UPDATE SET
                        user_name = EXCLUDED.user_name,
                        user_persona = EXCLUDED.user_persona,
                        relationship_context = EXCLUDED.relationship_context,
                        updated_at = EXCLUDED.updated_at
                """, tuple(row_list))
                success_count += 1
            except Exception as e:
                print(f"   ⚠️  跳过配置: {e}")
        
        pg_conn.commit()
        print(f"   ✅ 成功迁移 {success_count}/{len(rows)} 条用户角色配置")
    except sqlite3.OperationalError:
        print("   ⚠️  表不存在，跳过")

def migrate_membership_orders(sqlite_conn, pg_conn):
    """迁移会员订单表"""
    print("\n📦 迁移会员订单表 (membership_orders)...")
    
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()
    
    try:
        sqlite_cur.execute("""
            SELECT id, order_no, user_id, plan_type, amount, status, payment_method, 
                   paid_at, expires_at, created_at, updated_at
            FROM membership_orders
        """)
        rows = sqlite_cur.fetchall()
        
        if not rows:
            print("   ⚠️  没有会员订单需要迁移")
            return
        
        success_count = 0
        for row in rows:
            try:
                # 转换所有 ID 字段为 UUID
                row_list = list(row)
                # id, user_id 都需要转换
                if row_list[0] is not None and isinstance(row_list[0], int):
                    row_list[0] = int_to_uuid(row_list[0])
                if row_list[2] is not None and isinstance(row_list[2], int):
                    row_list[2] = int_to_uuid(row_list[2])
                # 清理时间戳字段 (paid_at, expires_at, created_at, updated_at)
                row_list[7] = clean_timestamp(row_list[7])
                row_list[8] = clean_timestamp(row_list[8])
                row_list[9] = clean_timestamp(row_list[9])
                row_list[10] = clean_timestamp(row_list[10])
                
                pg_cur.execute("""
                    INSERT INTO membership_orders (id, order_no, user_id, plan_type, amount, status, 
                                                  payment_method, paid_at, expires_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (order_no) DO UPDATE SET
                        status = EXCLUDED.status,
                        payment_method = EXCLUDED.payment_method,
                        paid_at = EXCLUDED.paid_at,
                        updated_at = EXCLUDED.updated_at
                """, tuple(row_list))
                success_count += 1
            except Exception as e:
                print(f"   ⚠️  跳过订单 {row[1] if len(row) > 1 else 'unknown'}: {e}")
        
        pg_conn.commit()
        print(f"   ✅ 成功迁移 {success_count}/{len(rows)} 条会员订单")
    except sqlite3.OperationalError:
        print("   ⚠️  表不存在，跳过")

def main():
    """主函数"""
    print("=" * 60)
    print("🚀 开始数据库迁移：SQLite → Supabase")
    print("=" * 60)
    
    # 连接数据库
    print("\n🔌 连接数据库...")
    sqlite_conn = connect_sqlite()
    pg_conn = connect_postgres()
    print("   ✅ 数据库连接成功")
    
    try:
        # 迁移各个表
        migrate_users(sqlite_conn, pg_conn)
        migrate_characters(sqlite_conn, pg_conn)
        migrate_chat_messages(sqlite_conn, pg_conn)
        migrate_chat_summaries(sqlite_conn, pg_conn)
        migrate_user_character_profiles(sqlite_conn, pg_conn)
        migrate_membership_orders(sqlite_conn, pg_conn)
        
        print("\n" + "=" * 60)
        print("🎉 数据库迁移完成！")
        print("=" * 60)
        print("\n💡 提示：")
        print("1. 请在 Supabase 控制台检查数据是否正确")
        print("2. 确认数据无误后，可以修改 .env 中的 DATABASE_URL")
        print("3. 重启应用即可使用 Supabase 数据库")
        
    except Exception as e:
        print(f"\n❌ 迁移过程中出现错误: {e}")
        pg_conn.rollback()
    finally:
        sqlite_conn.close()
        pg_conn.close()

if __name__ == "__main__":
    main()
