"""media 路由安全回归测试。"""

import pytest

from core.config import PROJECT_DIR
from core.exceptions import NotFoundError
from routers.media import resolve_media_response


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
