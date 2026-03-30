"""
配置模块 - 集中管理所有配置常量、环境变量和路径

这个文件存放：
- 路径配置（项目根目录、数据目录等）
- 环境变量加载（从 .env 文件读取）
- 应用常量（Token 有效期、摘要触发阈值等）
- 工具函数（UTC 时间格式化）
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path


def _int_env(name: str, default: int, *, minimum: int | None = None) -> int:
    """读取整数环境变量，非法时回退到默认值。"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value

# ============================================================
# 基础路径配置
# ============================================================
BASE_DIR = Path(__file__).resolve().parent  # backend/ 目录
PROJECT_DIR = BASE_DIR.parent  # aifriend/ 项目根目录
DATA_DIR = BASE_DIR / "data"  # 数据文件存放目录
DB_PATH = DATA_DIR / "aifriend.db"  # SQLite 数据库文件路径
SECRET_FILE = DATA_DIR / "app_secret.txt"  # 应用密钥文件路径
ENV_FILE = BASE_DIR / ".env"  # 环境变量配置文件路径

# 确保数据目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 前端静态文件路径
# ============================================================
FRONTEND_DIR = PROJECT_DIR  # index.html 在项目根目录
FRONTEND_STATIC_DIR = PROJECT_DIR / "frontend"  # CSS/JS 等资源文件目录


# ============================================================
# 环境变量加载
# ============================================================
def load_env_file() -> None:
    """
    从 backend/.env 读取环境变量，已存在的系统环境变量优先。
    
    格式要求：每行一个 KEY=value，支持 # 注释
    示例：
        API_KEY=sk-xxx
        DEBUG=true  # 这是注释
    """
    if not ENV_FILE.exists():
        return

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# 启动时立即加载环境变量
load_env_file()


# ============================================================
# 应用密钥（用于 Token 签名）
# ============================================================
if SECRET_FILE.exists():
    APP_SECRET = SECRET_FILE.read_text(encoding="utf-8").strip()
else:
    # 首次运行时生成随机密钥并保存
    APP_SECRET = secrets.token_hex(32)
    SECRET_FILE.write_text(APP_SECRET, encoding="utf-8")


# ============================================================
# 日志配置
# ============================================================
# 应用日志（后台任务报错会写到这里，不会影响前端用户）
logger = logging.getLogger("aifriend")


# ============================================================
# 对话窗口与记忆压缩配置
# ============================================================
# 触发摘要生成的消息数量阈值
# 当未摘要的消息超过这个数量时，会触发后台摘要生成
SUMMARY_TRIGGER_COUNT = 24

# 摘要生成的最大 token 数（控制摘要长度）
SUMMARY_MAX_TOKENS = 500


# ============================================================
# Token 有效期配置
# ============================================================
# Token 默认有效 30 天。超过这个时间用户需要重新登录。
# 可通过 .env 中的 TOKEN_EXPIRE_DAYS 覆盖。
TOKEN_EXPIRE_DAYS = _int_env("TOKEN_EXPIRE_DAYS", 30, minimum=1)


# ============================================================
# 基础限流配置（保持简单、低复杂度）
# ============================================================
# 登录：同一 IP 10 分钟最多 15 次；同一邮箱 10 分钟最多 10 次
LOGIN_RATE_LIMIT_COUNT = _int_env("LOGIN_RATE_LIMIT_COUNT", 15, minimum=1)
LOGIN_RATE_LIMIT_WINDOW_SECONDS = _int_env("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 600, minimum=10)
LOGIN_RATE_LIMIT_EMAIL_COUNT = 10

# 注册：同一 IP 1 小时最多 6 次
REGISTER_RATE_LIMIT_COUNT = 6
REGISTER_RATE_LIMIT_WINDOW_SECONDS = 3600

# 找回密码：同一 IP 半小时最多 5 次
PASSWORD_RESET_RATE_LIMIT_COUNT = 5
PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS = 1800

# 验证/重置验证码：同一 IP 10 分钟最多 12 次
VERIFY_CODE_RATE_LIMIT_COUNT = 12
VERIFY_CODE_RATE_LIMIT_WINDOW_SECONDS = 600

# 已登录聊天：同一用户 60 秒最多 45 次请求
CHAT_RATE_LIMIT_COUNT = _int_env("CHAT_RATE_LIMIT_COUNT", 45, minimum=1)
CHAT_RATE_LIMIT_WINDOW_SECONDS = _int_env("CHAT_RATE_LIMIT_WINDOW_SECONDS", 60, minimum=10)

# 游客试聊：同一 IP 10 分钟最多 12 次请求
GUEST_CHAT_RATE_LIMIT_COUNT = _int_env("GUEST_CHAT_RATE_LIMIT_COUNT", 12, minimum=1)
GUEST_CHAT_RATE_LIMIT_WINDOW_SECONDS = _int_env("GUEST_CHAT_RATE_LIMIT_WINDOW_SECONDS", 600, minimum=10)


# ============================================================
# 成本防护配置（P0）
# ============================================================
# token 估算比例：1600 中文字符 ≈ 1000 tokens
COST_ESTIMATE_CHARS_PER_TOKEN = 1.6

# 单次聊天最大输出 token，限制单轮回复成本
AI_CHAT_MAX_OUTPUT_TOKENS = _int_env("AI_CHAT_MAX_OUTPUT_TOKENS", 768, minimum=64)

# 免费注册用户（free）每日 token 预算
FREE_DAILY_TOKEN_LIMIT = _int_env("FREE_DAILY_TOKEN_LIMIT", 180000, minimum=1000)

# 游客每日 token 预算（按 IP）
GUEST_DAILY_TOKEN_LIMIT = _int_env("GUEST_DAILY_TOKEN_LIMIT", 40000, minimum=1000)

# VIP / SVIP 每日 token 预算
VIP_DAILY_TOKEN_LIMIT = _int_env("VIP_DAILY_TOKEN_LIMIT", 450000, minimum=1000)
SVIP_DAILY_TOKEN_LIMIT = _int_env("SVIP_DAILY_TOKEN_LIMIT", 900000, minimum=1000)

# 会员订单预留配置（网页支付接入前先把产品参数固定下来）
VIP_PLAN_PRICE_CENTS = _int_env("VIP_PLAN_PRICE_CENTS", 2990, minimum=0)
SVIP_PLAN_PRICE_CENTS = _int_env("SVIP_PLAN_PRICE_CENTS", 5990, minimum=0)
VIP_PLAN_DURATION_DAYS = _int_env("VIP_PLAN_DURATION_DAYS", 30, minimum=1)
SVIP_PLAN_DURATION_DAYS = _int_env("SVIP_PLAN_DURATION_DAYS", 30, minimum=1)

# 请求日志保留天数，避免日志表无限增长
AI_REQUEST_LOG_RETENTION_DAYS = _int_env("AI_REQUEST_LOG_RETENTION_DAYS", 30, minimum=1)


# ============================================================
# 工具函数
# ============================================================
def utc_now_iso() -> str:
    """
    返回统一的 UTC ISO 时间字符串，前端展示时再按本地时区格式化。
    
    使用 UTC 时间存储的好处：
    - 避免时区转换混乱
    - 数据库中时间戳统一
    - 前端根据用户本地时区显示
    """
    return datetime.now(timezone.utc).isoformat()
