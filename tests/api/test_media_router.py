"""media 路由安全回归测试。"""

import pytest

from core.config import PROJECT_DIR
from core.exceptions import NotFoundError
from routers.media import _MAX_AVATAR_SIZE, _read_limited_upload, resolve_media_response


@pytest.mark.parametrize(
    "raw_value",
    [
        "backend/.env.example",
        str(PROJECT_DIR / "backend" / ".env.example"),
        "frontend/admin/js/api.js",
        "/frontend/admin/js/api.js",
    ],
)
def test_resolve_media_response_denies_non_image_project_files(raw_value: str):
    """数据库里的媒体路径不能变成任意项目文件读取/跳转。"""
    with pytest.raises(NotFoundError):
        resolve_media_response(raw_value)


def test_resolve_media_response_allows_frontend_image_asset():
    """合法的前端图片资源仍然可用。"""
    response = resolve_media_response("/frontend/assets/default-avatar.png")

    assert response.status_code in (200, 307)


class _AsyncChunkFile:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def read(self, size=-1):
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


@pytest.mark.anyio
async def test_read_limited_upload_accepts_small_file():
    content = await _read_limited_upload(_AsyncChunkFile([b"\x89PNG\r\n\x1a\n", b"small"]))

    assert content == b"\x89PNG\r\n\x1a\nsmall"


@pytest.mark.anyio
async def test_read_limited_upload_rejects_stream_over_limit():
    with pytest.raises(Exception) as exc:
        await _read_limited_upload(_AsyncChunkFile([b"a" * (_MAX_AVATAR_SIZE + 1)]))

    assert "2MB" in str(exc.value)
