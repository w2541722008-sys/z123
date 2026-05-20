"""
model_adapter 模块单元测试

覆盖范围：
  - get_ai_config: 模型配置读取（basic/vip/svip 策略 + fallback）
  - build_chat_payload: OpenAI 兼容 payload 构建
  - _get_optional_params: 环境变量可选参数解析
"""

import httpx
import pytest

from core.model_adapter import (
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
    _build_request_headers,
    _build_request_url,
    _get_optional_params,
    _handle_model_error,
    build_chat_payload,
    get_ai_config,
)


# ============================================================
# 1. get_ai_config 测试
# ============================================================

class TestGetAiConfig:
    """模型配置读取 — 支持 basic/vip/svip 三套策略。"""

    def test_basic_profile_reads_basic_env(self):
        """basic profile 应读取 AIFRIEND_BASIC_* 前缀的环境变量。"""
        env = {
            "AIFRIEND_BASIC_API_KEY": "key_basic",
            "AIFRIEND_BASIC_BASE_URL": "https://basic.example.com",
            "AIFRIEND_BASIC_MODEL": "model-basic",
        }
        cfg = get_ai_config(env, profile="basic")
        assert cfg["api_key"] == "key_basic"
        assert cfg["base_url"] == "https://basic.example.com"
        assert cfg["model"] == "model-basic"
        assert cfg["profile"] == "basic"

    def test_vip_profile_reads_vip_env(self):
        """vip profile 应读取 AIFRIEND_VIP_* 前缀的环境变量。"""
        env = {
            "AIFRIEND_VIP_API_KEY": "key_vip",
            "AIFRIEND_VIP_MODEL": "model-vip",
        }
        cfg = get_ai_config(env, profile="vip")
        assert cfg["api_key"] == "key_vip"
        assert cfg["profile"] == "vip"

    def test_svip_profile_reads_svip_env(self):
        """svip profile 应读取 AIFRIEND_SVIP_* 前缀的环境变量。"""
        env = {
            "AIFRIEND_SVIP_API_KEY": "key_svip",
            "AIFRIEND_SVIP_BASE_URL": "https://svip.example.com/v1/",
            "AIFRIEND_SVIP_MODEL": "svip-model",
        }
        cfg = get_ai_config(env, profile="svip")
        assert cfg["api_key"] == "key_svip"
        assert cfg["base_url"] == "https://svip.example.com/v1"
        assert cfg["model"] == "svip-model"

    def test_falls_back_to_generic_when_profile_specific_missing(self):
        """profile 特定值缺失时，fallback 到通用 AIFRIEND_* 变量。"""
        env = {
            "AIFRIEND_API_KEY": "generic_key",
            "AIFRIEND_BASE_URL": "https://generic.example.com",
            "AIFRIEND_MODEL": "generic-model",
        }
        cfg = get_ai_config(env, profile="vip")
        assert cfg["api_key"] == "generic_key"
        assert cfg["base_url"] == "https://generic.example.com"

    def test_falls_back_to_defaults_when_no_env_set(self):
        """所有环境变量未设置时，使用硬编码默认值。"""
        cfg = get_ai_config({}, profile="basic")
        assert cfg["api_key"] == ""
        assert cfg["base_url"] == DEFAULT_AI_BASE_URL
        assert cfg["model"] == DEFAULT_AI_MODEL

    def test_strips_whitespace_from_values(self):
        """自动去除值的首尾空白。"""
        env = {"AIFRIEND_BASIC_API_KEY": "  key_with_spaces  "}
        cfg = get_ai_config(env, profile="basic")
        assert cfg["api_key"] == "key_with_spaces"

    def test_strips_trailing_slash_from_base_url(self):
        """base_url 自动去除尾部斜杠。"""
        env = {"AIFRIEND_BASIC_BASE_URL": "https://api.example.com/v1/"}
        cfg = get_ai_config(env, profile="basic")
        assert not cfg["base_url"].endswith("/")

    def test_unknown_profile_falls_back_to_basic_prefix(self):
        """未知 profile 名回退到 AIFRIEND_BASIC 前缀。"""
        env = {"AIFRIEND_BASIC_API_KEY": "from_basic"}
        cfg = get_ai_config(env, profile="unknown_profile")
        assert cfg["api_key"] == "from_basic"

    def test_none_or_empty_profile_treated_as_basic(self):
        """空/None profile 视为 basic。"""
        cfg1 = get_ai_config({}, profile=None)
        cfg2 = get_ai_config({}, profile="")
        cfg3 = get_ai_config({}, profile="  ")
        assert cfg1["profile"] == "basic"
        assert cfg2["profile"] == "basic"
        assert cfg3["profile"] == "basic"


# ============================================================
# 2. build_chat_payload 测试
# ============================================================

class TestBuildChatPayload:
    """OpenAI 兼容 chat payload 构建。"""

    def test_basic_payload_structure(self):
        """基本 payload 应包含必要字段。"""
        config = {"model": "test-model"}
        messages = [{"role": "user", "content": "hello"}]
        payload = build_chat_payload(messages, config, stream=False)

        assert payload["model"] == "test-model"
        assert payload["messages"] == messages
        assert payload["stream"] is False
        assert "temperature" in payload
        assert "max_tokens" in payload

    def test_stream_flag_respected(self):
        """stream 参数应正确传递。"""
        config = {"model": "m"}
        p_stream = build_chat_payload([], config, stream=True)
        p_nostream = build_chat_payload([], config, stream=False)
        assert p_stream["stream"] is True
        assert p_nostream["stream"] is False

    def test_custom_temperature_and_max_tokens(self):
        """自定义 temperature 和 max_tokens 应生效。"""
        config = {"model": "m"}
        payload = build_chat_payload([], config, stream=True, temperature=0.5, max_tokens=100)
        assert payload["temperature"] == 0.5
        assert payload["max_tokens"] == 100

    def test_optional_top_p_included_when_provided(self):
        """提供 top_p 时应包含在 payload 中。"""
        config = {"model": "m"}
        payload = build_chat_payload([], config, stream=True, top_p=0.9)
        assert "top_p" in payload
        assert payload["top_p"] == 0.9

    def test_optional_top_p_omitted_when_none(self):
        """top_p 为 None 时不应出现在 payload 中。"""
        config = {"model": "m"}
        payload = build_chat_payload([], config, stream=True, top_p=None)
        assert "top_p" not in payload

    def test_optional_repetition_penalty_included(self):
        """repetition_penalty 提供时应包含。"""
        config = {"model": "m"}
        payload = build_chat_payload([], config, stream=True, repetition_penalty=1.05)
        assert payload["repetition_penalty"] == 1.05


# ============================================================
# 3. _get_optional_params 测试
# ============================================================

class TestGetOptionalParams:
    """从环境变量读取可选模型参数。"""

    def test_returns_empty_dict_by_default(self):
        """无环境变量时返回空字典。"""
        import os as _os
        old = dict(_os.environ)
        try:
            for k in list(_os.environ.keys()):
                if k.startswith("AIFRIEND"):
                    del _os.environ[k]
            params = _get_optional_params()
            assert params == {}
        finally:
            _os.environ.clear()
            _os.environ.update(old)

    def test_parses_top_p_from_env(self):
        """从 AIFRIEND_TOP_P 解析浮点数。"""
        import os as _os
        old_environ = _os.environ.copy()
        try:
            _os.environ["AIFRIEND_TOP_P"] = "0.95"
            params = _get_optional_params()
            assert params.get("top_p") == 0.95
        finally:
            _os.environ.clear()
            _os.environ.update(old_environ)

    def test_ignores_invalid_top_p_value(self):
        """非法 top_p 值被静默忽略。"""
        import os as _os
        old_environ = _os.environ.copy()
        try:
            _os.environ["AIFRIEND_TOP_P"] = "not_a_number"
            params = _get_optional_params()
            assert "top_p" not in params
        finally:
            _os.environ.clear()
            _os.environ.update(old_environ)

    def test_ignores_empty_top_p_value(self):
        """空字符串 top_p 被忽略。"""
        import os as _os
        old_environ = _os.environ.copy()
        try:
            _os.environ["AIFRIEND_TOP_P"] = ""
            params = _get_optional_params()
            assert "top_p" not in params
        finally:
            _os.environ.clear()
            _os.environ.update(old_environ)


# ============================================================
# 以下测试从 test_model_adapter_extra.py 合并而来
# ============================================================

class TestBuildRequestHeaders:
    """验证 _build_request_headers 构造正确的请求头。"""

    def test_content_type_and_authorization(self):
        config = {"api_key": "sk-test123"}
        headers = _build_request_headers(config)
        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer sk-test123"


class TestBuildRequestUrl:
    """验证 _build_request_url 拼接正确的 API URL。"""

    def test_basic_url_concatenation(self):
        config = {"base_url": "https://api.example.com"}
        url = _build_request_url(config)
        assert url == "https://api.example.com/chat/completions"

    def test_handles_trailing_slash(self):
        config = {"base_url": "https://api.example.com/"}
        url = _build_request_url(config)
        assert url == "https://api.example.com//chat/completions"


class TestHandleModelError:
    """验证 _handle_model_error 对不同 httpx 异常的映射。"""

    def test_http_status_error_raises_runtime_error(self):
        response = httpx.Response(429, text="rate limited")
        exc = httpx.HTTPStatusError("err", request=httpx.Request("POST", "http://x"), response=response)
        with pytest.raises(RuntimeError, match="模型接口调用失败"):
            _handle_model_error(exc)

    def test_connect_error_raises_runtime_error(self):
        exc = httpx.ConnectError("connection refused")
        with pytest.raises(RuntimeError, match="模型接口连接失败"):
            _handle_model_error(exc)

    def test_timeout_error_raises_runtime_error(self):
        exc = httpx.TimeoutException("timed out")
        with pytest.raises(RuntimeError, match="模型接口请求超时"):
            _handle_model_error(exc)

    def test_generic_httpx_error_raises_runtime_error(self):
        exc = httpx.HTTPError("unknown error")
        with pytest.raises(RuntimeError, match="模型接口请求失败"):
            _handle_model_error(exc)
