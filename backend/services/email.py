"""
邮件发送服务模块 - 使用 Resend 发送验证码邮件

这个模块封装了 Resend API 的调用，提供：
- 发送密码重置验证码邮件
- 简单的重试机制
- HTML 邮件模板

使用方法：
    from services.email import send_reset_code_email
    
    success = send_reset_code_email("user@example.com", "123456")
    if success:
        print("邮件发送成功")
    else:
        print("邮件发送失败")

Resend 文档：https://resend.com/docs
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from config import logger

# Resend API 配置
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_API_URL = "https://api.resend.com/emails"

# 发件人邮箱（Resend 免费版默认使用这个）
DEFAULT_FROM_EMAIL = "onboarding@resend.dev"


def send_reset_code_email(to_email: str, code: str, max_retries: int = 3) -> bool:
    """
    发送密码重置验证码邮件。
    
    使用 Resend API 发送 HTML 格式的验证码邮件，包含重试机制。
    
    Args:
        to_email: 收件人邮箱地址
        code: 6 位数字验证码
        max_retries: 最大重试次数（默认 3 次）
    
    Returns:
        bool: 发送成功返回 True，失败返回 False
    
    注意：
        - 需要设置环境变量 RESEND_API_KEY
        - 免费版每天限制 100 封邮件
        - 邮件可能被归类到垃圾箱，提醒用户检查
    """
    if not RESEND_API_KEY:
        logger.error("RESEND_API_KEY 未设置，无法发送邮件")
        return False
    
    # HTML 邮件模板
    html_content = f"""
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
    
    # 邮件主题
    subject = "【AI Friend】密码重置验证码"
    
    # 请求数据
    payload: dict[str, Any] = {
        "from": DEFAULT_FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }
    
    # 请求头
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    
    # 带重试机制的发送
    for attempt in range(max_retries):
        try:
            response = requests.post(
                RESEND_API_URL,
                json=payload,
                headers=headers,
                timeout=30,
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"密码重置邮件已发送: {to_email}, message_id: {result.get('id')}")
                return True
            else:
                error_msg = response.text
                logger.warning(f"Resend API 返回错误 (尝试 {attempt + 1}/{max_retries}): {response.status_code} - {error_msg}")
                
                # 如果是 4xx 错误（客户端错误），不重试
                if 400 <= response.status_code < 500:
                    logger.error(f"Resend API 客户端错误，停止重试: {error_msg}")
                    return False
                
                # 其他错误，等待后重试
                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))  # 指数退避
                    
        except requests.exceptions.Timeout:
            logger.warning(f"Resend API 请求超时 (尝试 {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(1 * (attempt + 1))
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"Resend API 请求异常 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1 * (attempt + 1))
    
    logger.error(f"邮件发送失败，已重试 {max_retries} 次: {to_email}")
    return False


def generate_reset_code() -> str:
    """
    生成 6 位数字验证码。
    
    Returns:
        str: 6 位数字字符串（如 "123456"）
    """
    import random
    return "".join(random.choices("0123456789", k=6))
