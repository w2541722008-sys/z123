"""model_adapter 额外单元测试。

补充已有 test_model_adapter.py 未覆盖的函数：get_ai_config / build_chat_payload /
_build_request_headers / _build_request_url / _handle_model_error / _get_optional_params。
"""
import os
from unittest.mock import patch

import httpx
import pytest

from core.model_adapter import (
    get_ai_config,
    build_chat_payload,
    _build_request_headers,
    _build_request_url,
    _handle_model_error,
    _get_optional_params,
)


# ============================================================
# get_ai_config
# ============================================================
class TestGetAiConfig:
    def test_basic_profile_default(self):
        env = {
            "AIFRIEND_BASIC_API_KEY": "key-basic",
            "AIFRIEND_BASIC_BASE_URL": "https://api.basic.com",
            "AIFRIEND_BASIC_MODEL": "model-basic",
        }
        result = get_ai_config(env, "basic")
        assert result["api_key"] == "key-basic"
        assert result["base_url"] == "https://api.basic.com"
        assert result["model"] == "model-basic"
        assert result["profile"] == "basic"

    def test_vip_profile(self):
        env = {
            "AIFRIEND_VIP_API_KEY": "key-vip",
            "AIFRIEND_VIP_BASE_URL": "https://api.vip.com/",
            "AIFRIEND_VIP_MODEL": "model-vip",
        }
        result = get_ai_config(env, "vip")
        assert result["api_key"] == "key-vip"
        assert result["base_url"] == "https://api.vip.com"  # trailing slash stripped
        assert result["model"] == "model-vip"
        assert result["profile"] == "vip"

    def test_svip_profile(self):
        env = {
            "AIFRIEND_SVIP_API_KEY": "key-svip",
            "AIFRIEND_SVIP_BASE_URL": "https://api.svip.com",
            "AIFRIEND_SVIP_MODEL": "model-svip",
        }
        result = get_ai_config(env, "svip")
        assert result["api_key"] == "key-svip"
        assert result["profile"] == "svip"

    def test_fallback_to_default_env(self):
        env = {
            "AIFRIEND_API_KEY": "fallback-key",
            "AIFRIEND_BASE_URL": "https://fallback.com",
            "AIFRIEND_MODEL": "fallback-model",
        }
        result = get_ai_config(env, "basic")
        assert result["api_key"] == "fallback-key"
        assert result["base_url"] == "https://fallback.com"
        assert result["model"] == "fallback-model"

    def test_profile_specific_overrides_fallback(self):
        env = {
            "AIFRIEND_API_KEY": "fallback-key",
            "AIFRIEND_BASIC_API_KEY": "specific-key",
        }
        result = get_ai_config(env, "basic")
        assert result["api_key"] == "specific-key"

    def test_empty_profile_defaults_to_basic(self):
        env = {"AIFRIEND_API_KEY": "key"}
        result = get_ai_config(env, "")
        assert result["profile"] == "basic"

    def test_none_profile_defaults_to_basic(self):
        env = {"AIFRIEND_API_KEY": "key"}
        result = get_ai_config(env, None)
        assert result["profile"] == "basic"

    def test_unknown_profile_uses_basic_prefix(self):
        env = {
            "AIFRIEND_API_KEY": "fallback-key",
        }
        result = get_ai_config(env, "unknown")
        assert result["api_key"] == "fallback-key"

    def test_whitespace_stripped(self):
        env = {
            "AIFRIEND_BASIC_API_KEY": "  key  ",
            "AIFRIEND_BASIC_BASE_URL": "  https://api.com/  ",
            "AIFRIEND_BASIC_MODEL": "  model  ",
        }
        result = get_ai_config(env, "basic")
        assert result["api_key"] == "key"
        assert result["base_url"] == "https://api.com"
        assert result["model"] == "model"


# ============================================================
# build_chat_payload
# ============================================================
class TestBuildChatPayload:
    def test_basic_non_stream(self):
        config = {"model": "gpt-4", "api_key": "key", "base_url": "https://api.com"}
        messages = [{"role": "user", "content": "hello"}]
        result = build_chat_payload(messages, config, stream=False)
        assert result["model"] == "gpt-4"
        assert result["messages"] == messages
        assert result["stream"] is False
        assert "temperature" in result
        assert "max_tokens" in result

    def test_stream_true(self):
        config = {"model": "gpt-4", "api_key": "key", "base_url": "https://api.com"}
        result = build_chat_payload([], config, stream=True)
        assert result["stream"] is True

    def test_custom_max_tokens(self):
        config = {"model": "gpt-4", "api_key": "key", "base_url": "https://api.com"}
        result = build_chat_payload([], config, stream=False, max_tokens=2048)
        assert result["max_tokens"] == 2048

    def test_top_p_included(self):
        config = {"model": "gpt-4", "api_key": "key", "base_url": "https://api.com"}
        result = build_chat_payload([], config, stream=False, top_p=0.9)
        assert result["top_p"] == 0.9

    def test_top_p_not_included_when_none(self):
        config = {"model": "gpt-4", "api_key": "key", "base_url": "https://api.com"}
        result = build_chat_payload([], config, stream=False, top_p=None)
        assert "top_p" not in result

    def test_repetition_penalty_included(self):
        config = {"model": "gpt-4", "api_key": "key", "base_url": "https://api.com"}
        result = build_chat_payload([], config, stream=False, repetition_penalty=1.1)
        assert result["repetition_penalty"] == 1.1

    def test_custom_temperature(self):
        config = {"model": "gpt-4", "api_key": "key", "base_url": "https://api.com"}
        result = build_chat_payload([], config, stream=False, temperature=0.5)
        assert result["temperature"] == 0.5


# ============================================================
# _build_request_headers
# ============================================================
class TestBuildRequestHeaders:
    def test_basic(self):
        config = {"api_key": "sk-test123"}
        headers = _build_request_headers(config)
        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer sk-test123"


# ============================================================
# _build_request_url
# ============================================================
class TestBuildRequestUrl:
    def test_basic(self):
        config = {"base_url": "https://api.example.com"}
        url = _build_request_url(config)
        assert url == "https://api.example.com/chat/completions"

    def test_trailing_slash(self):
        config = {"base_url": "https://api.example.com/"}
        # Note: get_ai_config already strips trailing slashes,
        # but _build_request_url just concatenates
        url = _build_request_url(config)
        assert url == "https://api.example.com//chat/completions"


# ============================================================
# _handle_model_error
# ============================================================
class TestHandleModelError:
    def test_http_status_error(self):
        response = httpx.Response(429, text="rate limited")
        exc = httpx.HTTPStatusError("err", request=httpx.Request("POST", "http://x"), response=response)
        with pytest.raises(RuntimeError, match="模型接口调用失败"):
            _handle_model_error(exc)

    def test_connect_error(self):
        exc = httpx.ConnectError("connection refused")
        with pytest.raises(RuntimeError, match="模型接口连接失败"):
            _handle_model_error(exc)

    def test_timeout_error(self):
        exc = httpx.TimeoutException("timed out")
        with pytest.raises(RuntimeError, match="模型接口请求超时"):
            _handle_model_error(exc)

    def test_generic_httpx_error(self):
        exc = httpx.HTTPError("unknown error")
        with pytest.raises(RuntimeError, match="模型接口请求失败"):
            _handle_model_error(exc)


# ============================================================
# _get_optional_params
# ============================================================
class TestGetOptionalParams:
    def test_no_env_vars(self):
        with patch.dict(os.environ, {}, clear=True):
            result = _get_optional_params()
            assert result == {}

    def test_valid_top_p(self):
        with patch.dict(os.environ, {"AIFRIEND_TOP_P": "0.9"}, clear=True):
            result = _get_optional_params()
            assert result["top_p"] == 0.9

    def test_invalid_top_p_ignored(self):
        with patch.dict(os.environ, {"AIFRIEND_TOP_P": "not_a_number"}, clear=True):
            result = _get_optional_params()
            assert result == {}

    def test_empty_top_p_ignored(self):
        with patch.dict(os.environ, {"AIFRIEND_TOP_P": ""}, clear=True):
            result = _get_optional_params()
            assert result == {}
