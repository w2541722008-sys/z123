"""
邮件发送服务模块 - 支持 SMTP（推荐）和 Resend 两种方式

SMTP 方式（推荐）：
    - 使用 QQ 邮箱 / 163 邮箱等 SMTP 服务
    - 免费，可发送到任意邮箱
    - 配置：SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM

Resend 方式（备选）：
    - 使用 Resend API
    - 免费版只能发送到注册时绑定的邮箱
    - 配置：RESEND_API_KEY

使用方法：
    from services.email import send_reset_code_email

    success = send_reset_code_email("user@example.com", "123456")
"""

from __future__ import annotations

import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import httpx

from core.config import logger

# ============================================================
# SMTP 配置（优先使用）
# ============================================================
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()  # 如 smtp.qq.com
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))   # SSL: 465, TLS: 587
SMTP_USER = os.getenv("SMTP_USER", "").strip()   # 发件邮箱地址
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()  # 授权码（非邮箱登录密码）
SMTP_FROM = os.getenv("SMTP_FROM", "").strip()   # 发件人显示名，如 "AI Friend <xxx@qq.com>"

# ============================================================
# Resend API 配置（备选）
# ============================================================
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_API_URL = "https://api.resend.com/emails"
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")


def _mask_email(email: str) -> str:
    """将邮箱地址脱敏为 u***@example.com 格式，用于日志输出。"""
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    return f"{local[0]}***@{domain}"


def _build_reset_email_html(code: str) -> str:
    """生成密码重置验证码的 HTML 邮件内容。"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>密码重置验证码</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background-color: #f5f5f5;
                margin: 0;
                padding: 20px;
            }}
            .container {{
                max-width: 480px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 12px;
                padding: 40px;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            }}
            .logo {{
                text-align: center;
                margin-bottom: 24px;
                font-size: 24px;
                font-weight: 600;
                color: #3B82F6;
            }}
            .title {{
                font-size: 20px;
                font-weight: 600;
                color: #1f2937;
                margin-bottom: 16px;
                text-align: center;
            }}
            .description {{
                font-size: 14px;
                color: #6b7280;
                line-height: 1.6;
                margin-bottom: 24px;
                text-align: center;
            }}
            .code-box {{
                background: linear-gradient(135deg, #3B82F6 0%, #60A5FA 100%);
                border-radius: 8px;
                padding: 24px;
                text-align: center;
                margin-bottom: 24px;
            }}
            .code {{
                font-size: 32px;
                font-weight: 700;
                color: #ffffff;
                letter-spacing: 8px;
                font-family: 'Courier New', monospace;
            }}
            .expiry {{
                font-size: 13px;
                color: #9ca3af;
                text-align: center;
                margin-bottom: 24px;
            }}
            .warning {{
                font-size: 12px;
                color: #ef4444;
                background-color: #fef2f2;
                border-radius: 6px;
                padding: 12px;
                text-align: center;
            }}
            .footer {{
                font-size: 12px;
                color: #9ca3af;
                text-align: center;
                margin-top: 32px;
                padding-top: 24px;
                border-top: 1px solid #e5e7eb;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">AI Friend</div>
            <div class="title">密码重置</div>
            <div class="description">
                您正在重置 AI Friend 账户的密码。请使用以下验证码完成验证：
            </div>
            <div class="code-box">
                <div class="code">{code}</div>
            </div>
            <div class="expiry">验证码 10 分钟内有效</div>
            <div class="warning">
                如果您没有请求重置密码，请忽略此邮件。请勿将验证码告诉任何人。
            </div>
            <div class="footer">
                此邮件由系统自动发送，请勿回复
            </div>
        </div>
    </body>
    </html>
    """


# ============================================================
# SMTP 发送方式
# ============================================================
def _send_via_smtp(to_email: str, code: str, max_retries: int = 3) -> bool:
    """通过 SMTP 发送验证码邮件（支持 QQ/163/Gmail 等）。"""
    from_display = SMTP_FROM or SMTP_USER  # 显示名，如 "AI Friend <xxx@qq.com>"
    from_envelope = SMTP_USER  # 信封发件人，必须是纯邮箱地址
    masked = _mask_email(to_email)

    for attempt in range(max_retries):
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "【AI Friend】密码重置验证码"
            msg["From"] = from_display
            msg["To"] = to_email
            msg.attach(MIMEText(_build_reset_email_html(code), "html", "utf-8"))

            use_ssl = SMTP_PORT == 465
            if use_ssl:
                server: smtplib.SMTP | smtplib.SMTP_SSL = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
            else:
                server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
                server.ehlo()
                server.starttls()
                server.ehlo()

            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(from_envelope, [to_email], msg.as_string())
            server.quit()

            logger.info("验证码邮件已通过 SMTP 发送: %s", masked)
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP 认证失败，请检查 SMTP_USER 和 SMTP_PASSWORD（授权码）")
            return False  # 认证错误不重试
        except smtplib.SMTPException as e:
            logger.warning("SMTP 发送失败 (尝试 %d/%d): %s", attempt + 1, max_retries, e)
        except Exception as e:
            logger.warning("SMTP 发送异常 (尝试 %d/%d): %s", attempt + 1, max_retries, e, exc_info=True)

        if attempt < max_retries - 1:
            time.sleep(1 * (attempt + 1))

    logger.error("SMTP 邮件发送失败，已重试 %d 次: %s", max_retries, masked)
    return False


# ============================================================
# Resend 发送方式（备选）
# ============================================================
def _send_via_resend(to_email: str, code: str, max_retries: int = 3) -> bool:
    """通过 Resend API 发送验证码邮件。"""
    if not RESEND_API_KEY:
        logger.error("RESEND_API_KEY 未设置，无法发送邮件")
        return False

    payload: dict[str, Any] = {
        "from": RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": "【AI Friend】密码重置验证码",
        "html": _build_reset_email_html(code),
    }

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    masked = _mask_email(to_email)

    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(RESEND_API_URL, json=payload, headers=headers)

            if response.status_code == 200:
                result = response.json()
                logger.info("验证码邮件已通过 Resend 发送: %s, id: %s", masked, result.get("id"))
                return True

            error_size = len(response.content or b"")
            logger.warning(
                "Resend API 返回错误 (尝试 %d/%d): status=%s response_bytes=%s",
                attempt + 1,
                max_retries,
                response.status_code,
                error_size,
            )

            if 400 <= response.status_code < 500:
                logger.error("Resend API 客户端错误，停止重试: status=%s", response.status_code)
                return False

            if attempt < max_retries - 1:
                time.sleep(1 * (attempt + 1))

        except httpx.TimeoutException:
            logger.warning("Resend API 请求超时 (尝试 %d/%d)", attempt + 1, max_retries)
            if attempt < max_retries - 1:
                time.sleep(1 * (attempt + 1))
        except httpx.HTTPError as e:
            logger.warning("Resend API 请求异常 (尝试 %d/%d): %s", attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(1 * (attempt + 1))

    logger.error("Resend 邮件发送失败，已重试 %d 次: %s", max_retries, masked)
    return False


# ============================================================
# 统一发送入口
# ============================================================
def send_reset_code_email(to_email: str, code: str, max_retries: int = 3) -> bool:
    """
    发送密码重置验证码邮件。

    优先使用 SMTP（可发到任意邮箱），未配置时回退到 Resend。

    Args:
        to_email: 收件人邮箱地址
        code: 6 位数字验证码
        max_retries: 最大重试次数（默认 3 次）

    Returns:
        bool: 发送成功返回 True，失败返回 False
    """
    # 优先 SMTP
    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        return _send_via_smtp(to_email, code, max_retries)

    # 回退 Resend
    if RESEND_API_KEY:
        return _send_via_resend(to_email, code, max_retries)

    logger.error("邮件服务未配置：请设置 SMTP 或 RESEND_API_KEY")
    return False


def generate_reset_code() -> str:
    """
    生成 6 位数字验证码（密码学安全版本）。

    Returns:
        str: 6 位数字字符串（如 "123456"）
    """
    import secrets
    return "".join(secrets.choice("0123456789") for _ in range(6))
