"""前端静态资产回归测试。"""

from __future__ import annotations

import struct
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]


def _png_chunk_types(path: Path) -> list[bytes]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), f"{path} 不是 PNG 文件"

    offset = 8
    chunk_types: list[bytes] = []
    while offset < len(data):
        assert offset + 12 <= len(data), f"{path} PNG chunk 不完整"
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        assert chunk_end <= len(data), f"{path} PNG chunk 长度越界"
        chunk_types.append(chunk_type)
        offset = chunk_end
        if chunk_type == b"IEND":
            break

    assert chunk_types[-1:] == [b"IEND"], f"{path} 缺少 IEND chunk"
    assert offset == len(data), f"{path} IEND 后存在多余数据"
    return chunk_types


def test_default_avatar_png_is_valid():
    chunk_types = _png_chunk_types(PROJECT_DIR / "frontend/assets/default-avatar.png")

    assert b"IHDR" in chunk_types
    assert b"IDAT" in chunk_types


def test_home_page_declares_favicon():
    html = (PROJECT_DIR / "index.html").read_text(encoding="utf-8")

    assert 'rel="icon"' in html
    assert "frontend/assets/default-avatar.png" in html


def test_admin_page_declares_favicon():
    html = (PROJECT_DIR / "frontend/admin/index.html").read_text(encoding="utf-8")

    assert 'rel="icon"' in html
    assert "/api/frontend/assets/default-avatar.png" in html
