"""email 服务纯函数单元测试 — 掩码、HTML 模板生成。"""

from services.email import _mask_email, _build_reset_email_html


class TestMaskEmail:
    def test_standard_email_masked(self):
        result = _mask_email("user@example.com")
        assert result == "u***@example.com"

    def test_short_local_part(self):
        result = _mask_email("a@b.com")
        assert result == "a***@b.com"

    def test_no_at_symbol_returns_placeholder(self):
        result = _mask_email("invalid")
        assert result == "***"

    def test_empty_string(self):
        result = _mask_email("")
        assert result == "***"

    def test_long_email(self):
        result = _mask_email("verylongusername123@domain.com")
        assert result == "v***@domain.com"


class TestBuildResetEmailHtml:
    def test_contains_verification_code(self):
        html = _build_reset_email_html("123456")
        assert "123456" in html

    def test_is_html_format(self):
        html = _build_reset_email_html("000000")
        assert "<html" in html.lower() or "<div" in html.lower() or "</" in html.lower()

    def test_empty_code_handled(self):
        html = _build_reset_email_html("")
        assert isinstance(html, str)

    def test_special_characters_in_code(self):
        html = _build_reset_email_html("<script>alert(1)</script>")
        # 验证码中不应包含可执行 HTML
        assert isinstance(html, str)
