"""
数据库模块 - 管理 SQLite 连接、表初始化和迁移

这个文件存放：
- 数据库连接获取函数
- 所有表的创建语句（init_db）
- 数据库结构迁移逻辑（兼容旧版本）

使用方式：
    from database import get_conn, init_db
    
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users").fetchall()
    conn.close()

WAL 模式说明：
- 启用 WAL（Write-Ahead Logging）后，读写操作可以并行
- 大幅提升并发性能，避免"database is locked"错误
- 会生成 aifriend.db-wal 和 aifriend.db-shm 两个临时文件
- 正常关闭时会自动合并回主数据库文件
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from config import AI_REQUEST_LOG_RETENTION_DAYS, DB_PATH, TOKEN_EXPIRE_DAYS, logger

# 连接超时时间（秒）- 等待锁释放的最大时间
CONNECTION_TIMEOUT = 30

# 启用 WAL 模式的标志（方便调试时关闭）
WAL_MODE_ENABLED = True


def get_conn(timeout: float = CONNECTION_TIMEOUT) -> sqlite3.Connection:
    """
    获取数据库连接，返回带行工厂（row_factory）的连接对象。
    
    特性：
    - WAL 模式：读写并行，提升并发性能
    - 行工厂：支持通过列名访问数据
    - 超时机制：等待锁释放，避免立即报错
    
    使用示例：
        conn = get_conn()
        row = conn.execute("SELECT * FROM users WHERE id = 1").fetchone()
        print(row["email"])
        conn.close()
    
    Args:
        timeout: 等待锁释放的超时时间（秒），默认 30 秒
    
    Returns:
        配置好的 sqlite3.Connection 对象
    
    注意：调用方需要负责关闭连接（conn.close()）
    """
    conn = sqlite3.connect(DB_PATH, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    
    # 启用 WAL 模式（提升并发性能）
    if WAL_MODE_ENABLED:
        conn.execute("PRAGMA journal_mode=WAL")
        # 同步模式：NORMAL 是性能和安全的平衡
        conn.execute("PRAGMA synchronous=NORMAL")
        # 临时文件存放在内存中（提升性能）
        conn.execute("PRAGMA temp_store=MEMORY")
        # 缓存大小：-64000 表示 64MB（负号表示 KB 单位）
        conn.execute("PRAGMA cache_size=-64000")
    
    return conn


def _enable_wal_mode(conn: sqlite3.Connection) -> None:
    """
    为现有数据库启用 WAL 模式。
    
    在 init_db 中调用，确保数据库创建后就启用 WAL。
    """
    if not WAL_MODE_ENABLED:
        conn.execute("PRAGMA foreign_keys=ON")
        return
    conn.execute("PRAGMA foreign_keys=ON")
    
    # 检查当前 journal 模式
    row = conn.execute("PRAGMA journal_mode").fetchone()
    current_mode = row[0] if row else "unknown"
    
    if current_mode.lower() != "wal":
        # 切换到 WAL 模式
        result = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        new_mode = result[0] if result else "unknown"
        logger.info(f"数据库 journal_mode: {current_mode} -> {new_mode}")
    
    # 设置其他优化参数
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-64000")


def init_db() -> None:
    """
    初始化数据库，创建所有表和索引。
    
    这个函数是幂等的（idempotent），可以安全地多次调用：
    - 表已存在时不会报错（IF NOT EXISTS）
    - 字段已存在时不会重复添加（通过 pragma table_info 检查）
    - WAL 模式会自动启用（提升并发性能）
    
    数据库升级策略：
    - 新字段通过 ALTER TABLE ADD COLUMN 添加
    - 默认值确保旧数据兼容性
    - 不需要的数据迁移脚本，保持简单
    """
    conn = get_conn()
    cur = conn.cursor()
    
    # 启用 WAL 模式（必须在创建表之前）
    _enable_wal_mode(conn)

    # ============================================================
    # 用户表
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            password_algo TEXT NOT NULL DEFAULT 'sha256',
            nickname TEXT,
            plan_type TEXT NOT NULL DEFAULT 'free',
            plan_expires_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    # ============================================================
    # 认证 Token 表
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    # ============================================================
    # 角色表（角色卡）
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS characters (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            abbr TEXT NOT NULL,
            subtitle TEXT,
            avatar_url TEXT,
            cover_url TEXT,
            description TEXT,
            tags TEXT NOT NULL,
            opening_message TEXT,
            system_prompt TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            mock_reply_style TEXT NOT NULL,
            asset_type TEXT NOT NULL DEFAULT 'character',
            source_kind TEXT NOT NULL DEFAULT 'seed',
            source_path TEXT NOT NULL DEFAULT '',
            embedded_format TEXT NOT NULL DEFAULT 'json',
            raw_card_json TEXT NOT NULL DEFAULT '',
            structured_asset_json TEXT NOT NULL DEFAULT '',
            import_diagnostics TEXT NOT NULL DEFAULT '[]',
            is_visible INTEGER NOT NULL DEFAULT 1,
            home_priority INTEGER NOT NULL DEFAULT 999,
            card_type TEXT NOT NULL DEFAULT 'intimate',
            required_plan TEXT NOT NULL DEFAULT 'guest',
            import_locked INTEGER NOT NULL DEFAULT 0,
            affection_enabled INTEGER NOT NULL DEFAULT 1,
            affection_rules_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )

    # 角色表字段迁移（兼容旧版本）
    character_columns = [row[1] for row in cur.execute("PRAGMA table_info(characters)").fetchall()]
    migrations = [
        ("asset_type", "TEXT NOT NULL DEFAULT 'character'"),
        ("source_kind", "TEXT NOT NULL DEFAULT 'seed'"),
        ("source_path", "TEXT NOT NULL DEFAULT ''"),
        ("embedded_format", "TEXT NOT NULL DEFAULT 'json'"),
        ("raw_card_json", "TEXT NOT NULL DEFAULT ''"),
        ("structured_asset_json", "TEXT NOT NULL DEFAULT ''"),
        ("runtime_cache_json", "TEXT NOT NULL DEFAULT ''"),
        ("import_diagnostics", "TEXT NOT NULL DEFAULT '[]'"),
        ("is_visible", "INTEGER NOT NULL DEFAULT 1"),
        ("home_priority", "INTEGER NOT NULL DEFAULT 999"),
        ("card_type", "TEXT NOT NULL DEFAULT 'intimate'"),
        ("required_plan", "TEXT NOT NULL DEFAULT 'guest'"),
        ("import_locked", "INTEGER NOT NULL DEFAULT 0"),
        ("affection_enabled", "INTEGER NOT NULL DEFAULT 1"),
        ("affection_rules_json", "TEXT NOT NULL DEFAULT '{}'"),
    ]
    for column, definition in migrations:
        if column not in character_columns:
            cur.execute(f"ALTER TABLE characters ADD COLUMN {column} {definition}")

    # ============================================================
    # 聊天消息表
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            character_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            is_summarized INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
        )
        """
    )

    # 聊天消息表字段迁移
    message_columns = [row[1] for row in cur.execute("PRAGMA table_info(chat_messages)").fetchall()]
    if "is_summarized" not in message_columns:
        cur.execute("ALTER TABLE chat_messages ADD COLUMN is_summarized INTEGER NOT NULL DEFAULT 0")

    # ============================================================
    # 用户角色配置表（备注、签名等）
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_character_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            character_id TEXT NOT NULL,
            remark TEXT NOT NULL DEFAULT '',
            custom_signature TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, character_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
        )
        """
    )

    # ============================================================
    # 聊天摘要表（长期记忆）
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            character_id TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            memory_version INTEGER NOT NULL DEFAULT 1,
            last_message_id INTEGER,
            last_summarized_at TEXT,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, character_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE,
            FOREIGN KEY(last_message_id) REFERENCES chat_messages(id) ON DELETE SET NULL
        )
        """
    )

    # 摘要表字段迁移
    summary_columns = [row[1] for row in cur.execute("PRAGMA table_info(chat_summaries)").fetchall()]
    if "last_summarized_at" not in summary_columns:
        cur.execute("ALTER TABLE chat_summaries ADD COLUMN last_summarized_at TEXT")
    if "created_at" not in summary_columns:
        cur.execute("ALTER TABLE chat_summaries ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")

    # ============================================================
    # 索引优化
    # ============================================================
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_user_character_time ON chat_messages(user_id, character_id, created_at ASC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_summary_user_character ON chat_summaries(user_id, character_id)"
    )

    # ============================================================
    # 角色关系状态表（好感度、剧情阶段等）
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS character_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            character_id TEXT NOT NULL,
            affection INTEGER NOT NULL DEFAULT 30,
            story_phase TEXT NOT NULL DEFAULT 'stranger',
            mood TEXT NOT NULL DEFAULT 'neutral',
            custom_vars TEXT NOT NULL DEFAULT '{}',
            daily_event_counts TEXT NOT NULL DEFAULT '{}',
            daily_affection_gained INTEGER NOT NULL DEFAULT 0,
            last_event_timestamps TEXT NOT NULL DEFAULT '{}',
            daily_reset_date TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, character_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
        )
        """
    )

    # 状态表字段迁移
    state_columns = [row[1] for row in cur.execute("PRAGMA table_info(character_states)").fetchall()]
    state_migrations = [
        ("daily_event_counts", "TEXT NOT NULL DEFAULT '{}'"),
        ("daily_affection_gained", "INTEGER NOT NULL DEFAULT 0"),
        ("last_event_timestamps", "TEXT NOT NULL DEFAULT '{}'"),
        ("daily_reset_date", "TEXT NOT NULL DEFAULT ''"),
    ]
    for column, definition in state_migrations:
        if column not in state_columns:
            cur.execute(f"ALTER TABLE character_states ADD COLUMN {column} {definition}")

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_state_user_character ON character_states(user_id, character_id)"
    )

    # ============================================================
    # 其他表字段迁移（兼容旧版本）
    # ============================================================
    # auth_tokens 表加 expires_at 字段
    token_columns = [row[1] for row in cur.execute("PRAGMA table_info(auth_tokens)").fetchall()]
    if "expires_at" not in token_columns:
        cur.execute("ALTER TABLE auth_tokens ADD COLUMN expires_at TEXT NOT NULL DEFAULT ''")

    # users 表加 password_algo 字段（用于密码哈希算法迁移）
    user_columns = [row[1] for row in cur.execute("PRAGMA table_info(users)").fetchall()]
    if "password_algo" not in user_columns:
        cur.execute("ALTER TABLE users ADD COLUMN password_algo TEXT NOT NULL DEFAULT 'sha256'")
    if "plan_type" not in user_columns:
        cur.execute("ALTER TABLE users ADD COLUMN plan_type TEXT NOT NULL DEFAULT 'free'")
    if "plan_expires_at" not in user_columns:
        cur.execute("ALTER TABLE users ADD COLUMN plan_expires_at TEXT NOT NULL DEFAULT ''")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_plan_type ON users(plan_type)"
    )

    # auth_tokens 相关索引必须放在 expires_at 字段迁移之后，避免旧库启动时报错
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_expires ON auth_tokens(user_id, expires_at)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires ON auth_tokens(expires_at)"
    )

    # 为历史 token 补齐 expires_at，避免永久有效
    legacy_tokens = cur.execute(
        "SELECT token, created_at FROM auth_tokens WHERE expires_at = '' OR expires_at IS NULL"
    ).fetchall()
    if legacy_tokens:
        fallback_expire = (datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)).isoformat()
        for row in legacy_tokens:
            try:
                created_at = datetime.fromisoformat(row["created_at"])
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                expires_at = (created_at + timedelta(days=TOKEN_EXPIRE_DAYS)).isoformat()
            except Exception:
                expires_at = fallback_expire
            cur.execute(
                "UPDATE auth_tokens SET expires_at = ? WHERE token = ?",
                (expires_at, row["token"]),
            )

    # 清理启动时已经过期的 token
    cur.execute(
        "DELETE FROM auth_tokens WHERE expires_at != '' AND expires_at <= ?",
        (datetime.now(timezone.utc).isoformat(),),
    )

    # ============================================================
    # 密码重置验证码表
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    
    # 密码重置码表索引
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_reset_codes_email ON password_reset_codes(email)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_reset_codes_expires ON password_reset_codes(expires_at)"
    )

    # 清理已使用或已过期的验证码，避免表无限增长
    cur.execute(
        "DELETE FROM password_reset_codes WHERE used = 1 OR expires_at <= ?",
        (datetime.now(timezone.utc).isoformat(),),
    )

    # ============================================================
    # AI 请求消耗日志表（成本防护 / 排查用）
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_request_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            guest_ip TEXT NOT NULL DEFAULT '',
            character_id TEXT NOT NULL DEFAULT '',
            endpoint TEXT NOT NULL DEFAULT '',
            request_chars INTEGER NOT NULL DEFAULT 0,
            estimated_input_tokens INTEGER NOT NULL DEFAULT 0,
            estimated_output_tokens INTEGER NOT NULL DEFAULT 0,
            total_estimated_tokens INTEGER NOT NULL DEFAULT 0,
            used_fallback INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'success',
            error_detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_request_logs_created_at ON ai_request_logs(created_at)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_request_logs_user_day ON ai_request_logs(user_id, created_at)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_request_logs_guest_day ON ai_request_logs(guest_ip, created_at)"
    )

    # 清理过旧的请求日志，防止表无限膨胀
    logs_cutoff = (datetime.now(timezone.utc) - timedelta(days=AI_REQUEST_LOG_RETENTION_DAYS)).isoformat()
    cur.execute(
        "DELETE FROM ai_request_logs WHERE created_at < ?",
        (logs_cutoff,),
    )

    # ============================================================
    # 会员订单表（网页支付预留）
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS membership_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            plan_type TEXT NOT NULL,
            amount_cents INTEGER NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'CNY',
            duration_days INTEGER NOT NULL DEFAULT 30,
            status TEXT NOT NULL DEFAULT 'pending',
            payment_provider TEXT NOT NULL DEFAULT '',
            provider_trade_no TEXT NOT NULL DEFAULT '',
            checkout_url TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            paid_at TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL DEFAULT '',
            closed_at TEXT NOT NULL DEFAULT '',
            meta_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_membership_orders_user_created ON membership_orders(user_id, created_at)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_membership_orders_status_created ON membership_orders(status, created_at)"
    )

    # ============================================================
    # 角色配置系统 - 记忆分类表
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            color TEXT DEFAULT '#6366F1',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_category_character ON memory_categories(character_id)"
    )

    # ============================================================
    # 角色配置系统 - 记忆条目表（World Info 机制）
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS character_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT NOT NULL,
            keywords TEXT NOT NULL,
            trigger_logic TEXT NOT NULL DEFAULT 'any',
            content TEXT NOT NULL,
            category_id INTEGER,
            position TEXT NOT NULL DEFAULT 'before',
            priority INTEGER NOT NULL DEFAULT 100,
            is_active INTEGER NOT NULL DEFAULT 1,
            max_recursion INTEGER NOT NULL DEFAULT 1,
            comment TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE,
            FOREIGN KEY(category_id) REFERENCES memory_categories(id) ON DELETE SET NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_character ON character_memories(character_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_category ON character_memories(category_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_active ON character_memories(character_id, is_active)"
    )

    # ============================================================
    # 角色配置系统 - 开场白表
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS character_greetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT NOT NULL,
            story_phase TEXT NOT NULL DEFAULT 'stranger',
            mood TEXT NOT NULL DEFAULT 'neutral',
            content TEXT NOT NULL,
            storyline_id INTEGER,
            priority INTEGER NOT NULL DEFAULT 100,
            is_active INTEGER NOT NULL DEFAULT 1,
            use_count INTEGER NOT NULL DEFAULT 0,
            comment TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE,
            FOREIGN KEY(storyline_id) REFERENCES character_storylines(id) ON DELETE SET NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_greeting_character ON character_greetings(character_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_greeting_phase ON character_greetings(character_id, story_phase, is_active)"
    )

    # ============================================================
    # 角色配置系统 - 剧情线表
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS character_storylines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            unlock_score INTEGER NOT NULL DEFAULT 0,
            is_default INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_storyline_character ON character_storylines(character_id)"
    )

    # ============================================================
    # 角色配置系统 - 后置规则表
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS character_post_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            storyline_id INTEGER,
            story_phase TEXT,
            priority INTEGER NOT NULL DEFAULT 100,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE,
            FOREIGN KEY(storyline_id) REFERENCES character_storylines(id) ON DELETE SET NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_post_rule_character ON character_post_rules(character_id)"
    )

    # ============================================================
    # 角色配置系统 - 剧情事件表
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS story_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            trigger_score INTEGER NOT NULL,
            unlocked_memory_ids TEXT DEFAULT '',
            unlocked_greeting_ids TEXT DEFAULT '',
            unlocked_storyline_id INTEGER,
            event_content TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE,
            FOREIGN KEY(unlocked_storyline_id) REFERENCES character_storylines(id) ON DELETE SET NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_story_event_character ON story_events(character_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_story_event_score ON story_events(character_id, trigger_score)"
    )

    # ============================================================
    # 角色配置系统 - 用户剧情进度表
    # ============================================================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_story_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            character_id TEXT NOT NULL,
            current_storyline_id INTEGER,
            unlocked_storyline_ids TEXT NOT NULL DEFAULT '',
            triggered_event_ids TEXT NOT NULL DEFAULT '',
            selected_greeting_ids TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, character_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE,
            FOREIGN KEY(current_storyline_id) REFERENCES character_storylines(id) ON DELETE SET NULL
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_story_progress_user ON user_story_progress(user_id, character_id)"
    )

    conn.commit()
    conn.close()
