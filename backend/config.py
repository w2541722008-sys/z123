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


def _int_env(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
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
    if maximum is not None and value > maximum:
        return default
    return value

# ============================================================
# 基础路径配置
# ============================================================
BASE_DIR = Path(__file__).resolve().parent  # backend/ 目录
PROJECT_DIR = BASE_DIR.parent  # aifriend/ 项目根目录
DATA_DIR = BASE_DIR / "data"  # 数据文件存放目录
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
# 数据库配置
# ============================================================
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL 环境变量未设置，请在 .env 文件中配置 Supabase 连接字符串")


# ============================================================
# 环境与调试模式配置
# ============================================================
ENV = os.environ.get("ENV", "development")
DEBUG = os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")


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
# 认证与后台管理员配置
# ============================================================
# 管理后台管理员邮箱白名单，多个邮箱用英文逗号分隔
ADMIN_EMAILS = {
    item.strip().lower()
    for item in os.environ.get("ADMIN_EMAILS", "").split(",")
    if item.strip()
}

# Token 默认有效 30 天。超过这个时间用户需要重新登录。
# 可通过 .env 中的 TOKEN_EXPIRE_DAYS 覆盖。
TOKEN_EXPIRE_DAYS = _int_env("TOKEN_EXPIRE_DAYS", 30, minimum=1, maximum=365)


# ============================================================
# 基础限流配置（保持简单、低复杂度）
# ============================================================
# 登录：同一 IP 10 分钟最多 15 次；同一邮箱 10 分钟最多 10 次
LOGIN_RATE_LIMIT_COUNT = _int_env("LOGIN_RATE_LIMIT_COUNT", 15, minimum=1, maximum=100)
LOGIN_RATE_LIMIT_WINDOW_SECONDS = _int_env("LOGIN_RATE_LIMIT_WINDOW_SECONDS", 600, minimum=10, maximum=3600)
LOGIN_RATE_LIMIT_EMAIL_COUNT = _int_env("LOGIN_RATE_LIMIT_EMAIL_COUNT", 10, minimum=1, maximum=100)

# 注册：同一 IP 1 小时最多 6 次
REGISTER_RATE_LIMIT_COUNT = _int_env("REGISTER_RATE_LIMIT_COUNT", 6, minimum=1, maximum=100)
REGISTER_RATE_LIMIT_WINDOW_SECONDS = _int_env("REGISTER_RATE_LIMIT_WINDOW_SECONDS", 3600, minimum=10, maximum=86400)

# 找回密码：同一 IP 半小时最多 5 次
PASSWORD_RESET_RATE_LIMIT_COUNT = _int_env("PASSWORD_RESET_RATE_LIMIT_COUNT", 5, minimum=1, maximum=100)
PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS = _int_env("PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS", 1800, minimum=10, maximum=86400)

# 验证/重置验证码：同一 IP 10 分钟最多 12 次
VERIFY_CODE_RATE_LIMIT_COUNT = _int_env("VERIFY_CODE_RATE_LIMIT_COUNT", 12, minimum=1, maximum=100)
VERIFY_CODE_RATE_LIMIT_WINDOW_SECONDS = _int_env("VERIFY_CODE_RATE_LIMIT_WINDOW_SECONDS", 600, minimum=10, maximum=86400)

# 已登录聊天：同一用户 60 秒最多 45 次请求
CHAT_RATE_LIMIT_COUNT = _int_env("CHAT_RATE_LIMIT_COUNT", 45, minimum=1, maximum=200)
CHAT_RATE_LIMIT_WINDOW_SECONDS = _int_env("CHAT_RATE_LIMIT_WINDOW_SECONDS", 60, minimum=10, maximum=300)

# 游客试聊：同一 IP 10 分钟最多 12 次请求
GUEST_CHAT_RATE_LIMIT_COUNT = _int_env("GUEST_CHAT_RATE_LIMIT_COUNT", 12, minimum=1, maximum=50)
GUEST_CHAT_RATE_LIMIT_WINDOW_SECONDS = _int_env("GUEST_CHAT_RATE_LIMIT_WINDOW_SECONDS", 600, minimum=10, maximum=3600)


# ============================================================
# 成本防护配置（P0）
# ============================================================
# token 估算比例：1600 中文字符 ≈ 1000 tokens
COST_ESTIMATE_CHARS_PER_TOKEN = 1.6

# 单次聊天最大输出 token，限制单轮回复成本
AI_CHAT_MAX_OUTPUT_TOKENS = _int_env("AI_CHAT_MAX_OUTPUT_TOKENS", 768, minimum=64, maximum=4096)

# 免费注册用户（free）每日 token 预算
FREE_DAILY_TOKEN_LIMIT = _int_env("FREE_DAILY_TOKEN_LIMIT", 180000, minimum=1000, maximum=1000000)

# 游客每日 token 预算（按 IP）
GUEST_DAILY_TOKEN_LIMIT = _int_env("GUEST_DAILY_TOKEN_LIMIT", 40000, minimum=1000, maximum=200000)

# VIP / SVIP 每日 token 预算
VIP_DAILY_TOKEN_LIMIT = _int_env("VIP_DAILY_TOKEN_LIMIT", 450000, minimum=1000, maximum=5000000)
SVIP_DAILY_TOKEN_LIMIT = _int_env("SVIP_DAILY_TOKEN_LIMIT", 900000, minimum=1000, maximum=10000000)

# 会员订单预留配置（网页支付接入前先把产品参数固定下来）
VIP_PLAN_PRICE_CENTS = _int_env("VIP_PLAN_PRICE_CENTS", 2990, minimum=0)
SVIP_PLAN_PRICE_CENTS = _int_env("SVIP_PLAN_PRICE_CENTS", 5990, minimum=0)
VIP_PLAN_DURATION_DAYS = _int_env("VIP_PLAN_DURATION_DAYS", 30, minimum=1)
SVIP_PLAN_DURATION_DAYS = _int_env("SVIP_PLAN_DURATION_DAYS", 30, minimum=1)

# 待支付订单有效期（分钟），超时后自动关闭，避免长期堆积无效 pending 订单
BILLING_PENDING_EXPIRE_MINUTES = _int_env("BILLING_PENDING_EXPIRE_MINUTES", 30, minimum=5, maximum=1440)

# 请求日志保留天数，避免日志表无限增长
AI_REQUEST_LOG_RETENTION_DAYS = _int_env("AI_REQUEST_LOG_RETENTION_DAYS", 30, minimum=1, maximum=365)


# ============================================================
# AI 模型默认配置
# ============================================================
DEFAULT_AI_BASE_URL = "https://realmrouter.cn/v1"
DEFAULT_AI_MODEL = "glm-5.1"


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


def validate_production_config() -> list[str]:
    """
    验证生产环境必需的配置项，返回缺失的配置列表。
    
    在应用启动时调用，如果有缺失配置会记录警告日志。
    生产环境下配置不安全会抛出异常阻止启动。
    """
    missing = []
    environment = os.environ.get("ENV", "development").lower()
    
    # 注意：DATABASE_URL 已在模块顶部检查，缺失时直接 raise RuntimeError，此处不再重复检查
    
    # 检查 DEBUG 模式（生产环境必须关闭）
    if environment == "production" and DEBUG:
        missing.append("DEBUG - 生产环境必须关闭 DEBUG 模式（设置 DEBUG=false）")
    
    # 检查 AI 模型配置
    if not os.environ.get("AIFRIEND_API_KEY", "").strip():
        missing.append("AIFRIEND_API_KEY - AI 模型 API Key 未设置")
    
    # 检查 CORS 配置
    origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not origins or "localhost" in origins.lower():
        missing.append("ALLOWED_ORIGINS - 生产环境必须设置真实域名（不能是 localhost）")
    
    # 检查邮件服务配置
    if not os.environ.get("RESEND_API_KEY", "").strip():
        missing.append("RESEND_API_KEY - 邮件服务 API Key 未设置")
    
    # 检查管理员邮箱
    if not ADMIN_EMAILS:
        missing.append("ADMIN_EMAILS - 管理员邮箱未设置")
    
    # 生产环境下，配置错误应该阻止启动
    if environment == "production" and missing:
        error_msg = "❌ 生产环境配置不安全，拒绝启动：\n" + "\n".join(f"  • {m}" for m in missing)
        raise RuntimeError(error_msg)
    
    # 非生产环境但有缺失配置，也记录警告
    if missing:
        import logging
        logging.warning("⚠️ 检测到缺失的配置项：")
        for m in missing:
            logging.warning(f"  • {m}")
    
    return missing
