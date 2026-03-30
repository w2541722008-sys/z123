from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Iterable

from config import AI_CHAT_MAX_OUTPUT_TOKENS


# ============================================================
# 模型配置与调用适配层
# 说明：
# - 这里只处理“如何与模型接口通信”
# - 不关心角色卡、记忆、上下文编排细节
# - 后续换模型 / 换供应商，优先改这里
# ============================================================
DEFAULT_AI_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_AI_MODEL = "MiniMax-M2.5"

_MODEL_PROFILE_PREFIX = {
    "basic": "AIFRIEND_BASIC",
    "vip": "AIFRIEND_VIP",
    "svip": "AIFRIEND_SVIP",
}


def get_ai_config(env: dict[str, str | None], profile: str = "basic") -> dict[str, str]:
    """从环境变量中读取模型配置，支持 basic / vip / svip 三套策略。"""
    profile_name = (profile or "basic").strip().lower()
    prefix = _MODEL_PROFILE_PREFIX.get(profile_name, "AIFRIEND_BASIC")

    profile_api_key = (env.get(f"{prefix}_API_KEY") or "").strip()
    profile_base_url = (env.get(f"{prefix}_BASE_URL") or "").strip().rstrip("/")
    profile_model = (env.get(f"{prefix}_MODEL") or "").strip()

    return {
        "api_key": profile_api_key or (env.get("AIFRIEND_API_KEY") or "").strip(),
        "base_url": profile_base_url or (env.get("AIFRIEND_BASE_URL") or DEFAULT_AI_BASE_URL).strip().rstrip("/"),
        "model": profile_model or (env.get("AIFRIEND_MODEL") or DEFAULT_AI_MODEL).strip(),
        "profile": profile_name,
    }


def build_chat_payload(
    messages: list[dict[str, str]],
    config: dict[str, str],
    stream: bool,
    temperature: float = 0.9,
    max_tokens: int = AI_CHAT_MAX_OUTPUT_TOKENS,
) -> dict[str, Any]:
    """统一构建 OpenAI 兼容 chat payload，方便后续替换 provider。

    max_tokens 说明：
      - 以前是 512，导致 AI 的回复经常被硬截断（说到一半就没了），体验很差
      - 现在默认值由 AI_CHAT_MAX_OUTPUT_TOKENS 控制，当前走配置化
      - 如果某条消息需要更长的回复（比如 AI 讲故事），调用方可以传入更大的值
      - 理论上限建议不超过 4096（更长的模型输出会很慢，不适合聊天场景）
    """
    return {
        "model": config["model"],
        "messages": messages,
        "stream": stream,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


def _build_request(config: dict[str, str], payload: dict[str, Any]) -> urllib.request.Request:
    return urllib.request.Request(
        url=f"{config['base_url']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['api_key']}",
        },
        method="POST",
    )


def request_chat_completion(
    messages: list[dict[str, str]],
    config: dict[str, str],
    normalize_reply_text,
    max_tokens: int | None = None,
) -> str:
    """普通非流式模型调用。"""
    if not config["api_key"]:
        raise RuntimeError("AIFRIEND_API_KEY 未配置")

    payload = build_chat_payload(
        messages=messages,
        config=config,
        stream=False,
        max_tokens=max_tokens or AI_CHAT_MAX_OUTPUT_TOKENS,
    )
    req = _build_request(config, payload)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"模型接口错误 {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"模型接口连接失败: {exc}") from exc

    data = json.loads(body)
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    reply = normalize_reply_text(content)
    if not reply:
        raise RuntimeError("模型返回了空内容")
    return reply


def stream_chat_completion(
    messages: list[dict[str, str]],
    config: dict[str, str],
    max_tokens: int | None = None,
) -> Iterable[str]:
    """流式模型调用，逐块产出 delta 文本。"""
    if not config["api_key"]:
        raise RuntimeError("AIFRIEND_API_KEY 未配置")

    payload = build_chat_payload(
        messages=messages,
        config=config,
        stream=True,
        max_tokens=max_tokens or AI_CHAT_MAX_OUTPUT_TOKENS,
    )
    req = _build_request(config, payload)

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            while True:
                raw_line = resp.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line or not line.startswith("data: "):
                    continue
                payload_text = line[6:]
                if payload_text == "[DONE]":
                    break
                try:
                    data = json.loads(payload_text)
                except json.JSONDecodeError:
                    continue
                delta = data.get("choices", [{}])[0].get("delta", {}).get("content")
                if delta:
                    yield delta
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"模型接口错误 {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"模型接口连接失败: {exc}") from exc
