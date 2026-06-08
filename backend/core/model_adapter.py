from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Iterable, Mapping

import httpx

from core.config import AI_CHAT_MAX_OUTPUT_TOKENS, DEFAULT_AI_BASE_URL, DEFAULT_AI_MODEL
import os

logger = logging.getLogger(__name__)

# 熔断器回调 — 由 main.py lifespan 注入，解除 core 对 services 的直接依赖
_get_circuit_breaker: Callable[..., Any] | None = None


def register_circuit_breaker(cb_fn: Callable[..., Any]) -> None:
    """注册熔断器工厂函数（由 main.py 在启动时调用）。"""
    global _get_circuit_breaker
    _get_circuit_breaker = cb_fn

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ[key])
    except (KeyError, ValueError):
        return default

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ[key])
    except (KeyError, ValueError):
        return default

# 常量定义（均支持环境变量覆盖，未设置时使用默认值）
DEFAULT_TIMEOUT = _env_int("AI_HTTP_TIMEOUT", 60)
STREAM_TIMEOUT = _env_int("AI_STREAM_TIMEOUT", 120)
_MAX_ATTEMPTS = _env_int("AI_MAX_ATTEMPTS", 3)
_RETRY_BACKOFF_BASE = _env_float("AI_RETRY_BACKOFF_BASE", 0.5)
_MAX_STREAM_ATTEMPTS = _env_int("AI_MAX_STREAM_ATTEMPTS", 2)
_STREAM_RETRY_DELAY = _env_float("AI_STREAM_RETRY_DELAY", 0.5)

# 每线程独立 httpx.Client — httpx.Client 非线程安全，ThreadPoolExecutor 多线程并发访问
# 同一全局实例会导致数据错乱。threading.local() 确保每个线程独享自己的连接池。
_local = threading.local()


def _get_http_client() -> httpx.Client:
    client = getattr(_local, 'http_client', None)
    if client is None or client.is_closed:
        client = httpx.Client(timeout=DEFAULT_TIMEOUT)
        _local.http_client = client
    return client


def _get_stream_client() -> httpx.Client:
    client = getattr(_local, 'stream_client', None)
    if client is None or client.is_closed:
        client = httpx.Client(timeout=STREAM_TIMEOUT)
        _local.stream_client = client
    return client

# ============================================================
# 模型配置与调用适配层
# 说明：
# - 这里只处理"如何与模型接口通信"
# - 不关心角色卡、记忆、上下文编排细节
# - 后续换模型 / 换供应商，优先改这里
# ============================================================

# 重导出配置常量（实际定义已迁移到 config.py）

_MODEL_PROFILE_PREFIX = {
    "basic": "AIFRIEND_BASIC",
    "vip": "AIFRIEND_VIP",
    "svip": "AIFRIEND_SVIP",
}


def get_ai_config(env: dict[str, str | None] | Mapping[str, str], profile: str = "basic") -> dict[str, str]:
    """从环境变量中读取模型配置，支持 basic / vip / svip 三套策略。"""
    profile_name = (profile or "").strip().lower() or "basic"
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
    top_p: float | None = None,
    repetition_penalty: float | None = None,
) -> dict[str, Any]:
    """统一构建 OpenAI 兼容 chat payload，方便后续替换 provider。

    max_tokens 说明：
      - 以前是 512，导致 AI 的回复经常被硬截断（说到一半就没了），体验很差
      - 现在默认值由 AI_CHAT_MAX_OUTPUT_TOKENS 控制，当前走配置化
      - 如果某条消息需要更长的回复（比如 AI 讲故事），调用方可以传入更大的值
      - 理论上限建议不超过 4096（更长的模型输出会很慢，不适合聊天场景）

    参数说明：
      - temperature: 控制创造性，0.7-0.9 推荐
      - top_p: 控制输出多样性，0.9 推荐
      - repetition_penalty: 防止复读，1.05-1.1 推荐
    """
    payload: dict[str, Any] = {
        "model": config["model"],
        "messages": messages,
        "stream": stream,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # 添加可选参数（如果提供了的话）
    if top_p is not None:
        payload["top_p"] = top_p
    if repetition_penalty is not None:
        payload["repetition_penalty"] = repetition_penalty

    return payload


def _get_optional_params() -> dict[str, float]:
    """从环境变量读取可选的模型参数。

    Note: MiniMax API 不支持 presence_penalty / frequency_penalty / repetition_penalty
    这些参数会被忽略，防复读请通过后置规则实现。
    """
    params: dict[str, float] = {}

    top_p = os.environ.get("AIFRIEND_TOP_P", "").strip()
    if top_p:
        try:
            params["top_p"] = float(top_p)
        except ValueError:
            pass

    # Note: repetition_penalty 不被 MiniMax 支持，已移除
    # 防复读请通过角色配置的"后置规则"实现，例如：
    # "避免重复之前说过的话，每次回复要有新的细节或进展"

    return params


def _handle_model_error(exc: httpx.HTTPError) -> None:
    """统一处理模型接口异常，转换为 RuntimeError 并记录日志。"""
    if isinstance(exc, httpx.HTTPStatusError):
        logger.error(
            "模型接口错误 status=%s response_bytes=%s",
            exc.response.status_code,
            len(exc.response.content or b""),
        )
        raise RuntimeError("模型接口调用失败") from exc
    if isinstance(exc, httpx.ConnectError):
        logger.error("模型接口连接失败: %s", exc)
        raise RuntimeError("模型接口连接失败") from exc
    if isinstance(exc, httpx.TimeoutException):
        logger.error("模型接口超时: %s", exc)
        raise RuntimeError("模型接口请求超时") from exc
    # 兜底：其他 httpx 异常
    logger.error("模型接口请求异常: %s", exc)
    raise RuntimeError("模型接口请求失败") from exc


def _is_retriable(exc: httpx.HTTPError) -> bool:
    """判断是否为可重试的瞬时错误（连接失败、超时、网关错误）。"""
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (502, 503, 504)
    return False


def _build_request_headers(config: dict[str, str]) -> dict[str, str]:
    """构建模型请求的通用 headers。"""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }


def _build_request_url(config: dict[str, str]) -> str:
    """构建模型请求的 URL。"""
    return f"{config['base_url']}/chat/completions"


def request_chat_completion(
    messages: list[dict[str, str]],
    config: dict[str, str],
    normalize_reply_text: Callable[[str], str],
    max_tokens: int | None = None,
) -> str:
    """普通非流式模型调用，瞬时错误自动重试最多 2 次。"""
    if not config["api_key"]:
        raise RuntimeError("AIFRIEND_API_KEY 未配置")

    breaker = _get_circuit_breaker()
    endpoint_key = config["base_url"]

    # 熔断器检查（OPEN 状态直接抛异常，上层转 503）
    breaker.before_request(endpoint_key)

    optional_params = _get_optional_params()
    payload = build_chat_payload(
        messages=messages,
        config=config,
        stream=False,
        max_tokens=max_tokens or AI_CHAT_MAX_OUTPUT_TOKENS,
        **optional_params,
    )

    url = _build_request_url(config)
    headers = _build_request_headers(config)

    body = ""
    for attempt in range(_MAX_ATTEMPTS):
        try:
            client = _get_http_client()
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.text
            break
        except httpx.HTTPError as exc:
            if attempt < (_MAX_ATTEMPTS - 1) and _is_retriable(exc):
                wait = _RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "模型调用失败，%.1f秒后重试(%s/%s): %s",
                    wait, attempt + 2, _MAX_ATTEMPTS, exc,
                )
                time.sleep(wait)
                # 重试前再次检查熔断器
                breaker.before_request(endpoint_key)
                continue
            breaker.report_failure(endpoint_key)
            _handle_model_error(exc)

    data = json.loads(body)
    choices = data.get("choices", [])
    content = choices[0].get("message", {}).get("content", "") if choices else ""
    reply = normalize_reply_text(content)
    if not reply:
        breaker.report_failure(endpoint_key)
        raise RuntimeError("模型返回了空内容")
    breaker.report_success(endpoint_key)
    return reply


def stream_chat_completion(
    messages: list[dict[str, str]],
    config: dict[str, str],
    max_tokens: int | None = None,
) -> Iterable[str]:
    """流式模型调用，逐块产出 delta 文本。

    连接建立阶段（TCP 连接 + HTTP 响应头）支持瞬时错误自动重试 1 次，
    流式数据迭代阶段不重试（已向客户端发送了部分内容）。
    """
    if not config["api_key"]:
        raise RuntimeError("AIFRIEND_API_KEY 未配置")

    breaker = _get_circuit_breaker()
    endpoint_key = config["base_url"]

    # 熔断器检查
    breaker.before_request(endpoint_key)

    optional_params = _get_optional_params()
    payload = build_chat_payload(
        messages=messages,
        config=config,
        stream=True,
        max_tokens=max_tokens or AI_CHAT_MAX_OUTPUT_TOKENS,
        **optional_params,
    )

    url = _build_request_url(config)
    headers = _build_request_headers(config)

    # 连接建立阶段（可重试）
    resp_ctx = None
    for attempt in range(_MAX_STREAM_ATTEMPTS):
        try:
            client = _get_stream_client()
            resp_ctx = client.stream("POST", url, json=payload, headers=headers)
            resp = resp_ctx.__enter__()
            resp.raise_for_status()
            break
        except httpx.HTTPError as exc:
            if resp_ctx is not None:
                try:
                    resp_ctx.__exit__(None, None, None)
                except Exception:
                    pass
                resp_ctx = None
            if attempt < (_MAX_STREAM_ATTEMPTS - 1) and _is_retriable(exc):
                logger.warning("流式连接建立失败，%.1f秒后重试: %s", _STREAM_RETRY_DELAY, exc)
                time.sleep(_STREAM_RETRY_DELAY)
                breaker.before_request(endpoint_key)
                continue
            breaker.report_failure(endpoint_key)
            _handle_model_error(exc)

    # 流式迭代阶段（不重试）
    breaker.report_success(endpoint_key)
    try:
        for raw_line in resp.iter_lines():
            line = raw_line.strip()
            if not line or not line.startswith("data: "):
                continue
            payload_text = line[6:]
            if payload_text == "[DONE]":
                break
            try:
                data = json.loads(payload_text)
            except json.JSONDecodeError:
                continue
            choices = data.get("choices", [])
            delta = choices[0].get("delta", {}).get("content") if choices else None
            if delta:
                yield delta
    except httpx.HTTPError as exc:
        breaker.report_failure(endpoint_key)
        _handle_model_error(exc)
    finally:
        if resp_ctx is not None:
            resp_ctx.__exit__(None, None, None)
