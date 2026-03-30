"""
generate_avatars.py
调用 MiniMax image-01 文生图 API，为角色生成动漫风格头像
输出到 assets/images/ 目录

使用前配置：
  复制 backend/.env，或直接在环境变量里设置 AIFRIEND_API_KEY
  export AIFRIEND_API_KEY=sk-xxxxx
"""
import os
import time
import base64
import requests
from pathlib import Path
from dotenv import load_dotenv

# ── 加载 .env 文件（从 backend/.env 读取 API Key）──────────────
_backend_env = Path(__file__).parent / "backend" / ".env"
if _backend_env.exists():
    load_dotenv(_backend_env)

# ── API 配置（从环境变量读取，不硬编码密钥）──────────────────────
API_KEY = os.environ.get("AIFRIEND_API_KEY", "")
if not API_KEY:
    raise RuntimeError(
        "未找到 AIFRIEND_API_KEY。\n"
        "请在 backend/.env 里配置，或 export AIFRIEND_API_KEY=your_key"
    )
API_URL = os.environ.get(
    "AIFRIEND_IMAGE_API_URL",
    "https://api.minimaxi.com/v1/image_generation"
)
OUT_DIR = os.path.join(os.path.dirname(__file__), "assets", "images")

# ── 4个角色的头像提示词 ───────────────────────────────────────
CHARACTERS = [
    {
        "filename": "tianmei.jpg",
        "prompt": (
            "anime portrait of a beautiful charming young adult Chinese woman, "
            "sweet girl style, soft shoulder-length wavy hair in warm chestnut-brown, "
            "gentle alluring eyes with natural makeup, soft pink lips with a warm smile, "
            "wearing a flowy off-shoulder pastel pink top, "
            "warm golden sunlight background with soft bokeh, "
            "mature feminine beauty, slightly seductive yet innocent vibe, "
            "highly detailed anime illustration, clean line art, "
            "portrait composition, face and shoulders, square format 1:1, "
            "artstation quality, no text, no watermark, no childish elements"
        ),
    },
    {
        "filename": "dandan.jpg",
        "prompt": (
            "anime portrait of a handsome sunny young adult Chinese man in his early 20s, "
            "warm and cheerful personality, slightly messy caramel-brown hair with natural highlights, "
            "bright warm eyes with a gentle smile, defined facial features, "
            "wearing a casual open collar shirt in warm beige-orange tone, "
            "bright warm sunlight outdoor background, "
            "mature youthful charm, not childish, "
            "highly detailed anime illustration, clean line art, "
            "portrait composition, face and shoulders, square format 1:1, "
            "artstation quality, no text, no watermark"
        ),
    },
]


def generate_one(char: dict) -> bool:
    """生成单张图片并保存"""
    name = char["filename"]
    out_path = os.path.join(OUT_DIR, name)

    print(f"[生成中] {name} ...")

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "image-01",
        "prompt": char["prompt"],
        "aspect_ratio": "1:1",
        "response_format": "base64",   # 直接返回 base64，不依赖临时 URL
        "n": 1,
        "prompt_optimizer": False,      # 关闭优化，保持 prompt 原意
    }

    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()

        # 解析 base64 图片数据
        # MiniMax 实际返回格式: {"data": {"image_base64": ["...base64str..."]}}
        data = result.get("data", {})
        image_list = data.get("image_base64", [])

        if not image_list:
            print(f"  ⚠ 未找到 image_base64，完整响应: {result}")
            return False

        # image_base64 是一个列表，取第一个
        img_b64 = image_list[0] if isinstance(image_list, list) else image_list

        # 写入 jpg 文件
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(img_b64))

        print(f"  ✅ 保存到 {out_path}")
        return True

    except Exception as e:
        print(f"  ❌ 失败: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"     响应: {e.response.text[:300]}")
        return False


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"输出目录: {OUT_DIR}\n")

    for i, char in enumerate(CHARACTERS):
        ok = generate_one(char)
        if not ok:
            print(f"  跳过 {char['filename']}")
        # 每张之间等1秒，避免频率限制
        if i < len(CHARACTERS) - 1:
            time.sleep(1)

    print("\n全部完成！")


if __name__ == "__main__":
    main()
