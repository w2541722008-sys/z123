"""
card_analyze.py — 角色卡 AI 分析工具
==========================================

作用：
  对数据库里 import_locked=0 的角色，读取原始卡片内容（raw_card_json），
  调用 AI 自动生成用户友好的展示字段：
    - subtitle（简介，30-60字，吸引人，不含技术信息）
    - tags（标签列表，5个，反映角色特征和卡类型）
    - opening_message（开场白，如原卡开场白有问题则生成新的）

  分析完成后将字段写入数据库，并设 import_locked=1（之后不会被 PNG 重导入覆盖）。

使用方式：
  # 分析所有未锁定的角色
  python card_analyze.py

  # 只分析某个角色（支持模糊名称）
  python card_analyze.py --name "陈序"

  # 查看哪些卡还没分析（不执行分析）
  python card_analyze.py --list

  # 强制重新分析已锁定的卡（会临时解锁再重新跑 AI）
  python card_analyze.py --name "高凌枫" --force

注意：
  - 需要在 backend 目录下运行，确保 .env 里有 AIFRIEND_API_KEY
  - 每张卡调用一次 AI，共耗时几秒到十几秒
  - AI 输出为 JSON，解析失败时会打印错误并跳过，不影响其他卡
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import textwrap
from pathlib import Path

# ── 路径与配置 ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "aifriend.db"
ENV_FILE = BASE_DIR / ".env"


def load_env() -> dict[str, str | None]:
    """读取 .env 文件，返回 key-value 字典。"""
    env: dict[str, str | None] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ── AI 调用（直接复用 model_adapter 的逻辑，不引入 FastAPI 依赖）────────────
def call_ai(prompt: str, api_key: str, base_url: str, model: str) -> str:
    """调用 AI 接口，返回模型输出的文本（非流式）。"""
    import urllib.error
    import urllib.request

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.3,   # 分析任务用低温度，输出更稳定
        "max_tokens": 800,
    }
    req = urllib.request.Request(
        url=f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"AI 接口错误 {exc.code}: {detail[:300]}") from exc

    return body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()


# ── Prompt 构建 ────────────────────────────────────────────────────────────────
def build_analysis_prompt(char_name: str, card_json: str, card_type: str) -> str:
    """
    构建让 AI 分析角色卡的 prompt，要求 AI 输出 JSON。
    """
    # 从 raw_card_json 里提取关键内容，防止 prompt 太长
    try:
        card = json.loads(card_json)
        data = card.get("data", card)  # V2 格式有 data 包装层
        description = (data.get("description") or "")[:2000]
        personality = (data.get("personality") or "")[:1000]
        scenario = (data.get("scenario") or "")[:500]
        first_mes = (data.get("first_mes") or "")[:500]
        # 取第一条备用开场白（如果有）
        alt_greetings = data.get("alternate_greetings") or data.get("alternateGreetings") or []
        first_alt = alt_greetings[0][:400] if alt_greetings else ""
    except Exception:
        description = card_json[:2000]
        personality = scenario = first_mes = first_alt = ""

    # 卡类型对应的标签方向提示
    type_hint = {
        "intimate":  "标签方向：角色外貌特征、性格特点、与用户的关系类型、故事背景。例：高冷、青梅竹马、现代都市、校园。",
        "scenario":  "标签方向：故事题材、剧情类型、交互方式、时代背景。例：港式黑帮、剧情多线、年代感、悬疑。",
        "world":     "标签方向：世界类型、核心玩法、规模感、风格。例：世界探索、多NPC、日常模拟、校园。",
    }.get(card_type, "标签方向：综合体现角色特征和互动类型。")

    # 开场白分析提示
    om_hint = ""
    if first_mes:
        has_copyright = any(kw in first_mes for kw in ["discord", "请勿倒卖", "分享于", "http://", "https://", ".css", ".status-card", "<style"])
        if has_copyright:
            om_hint = "原卡开场白包含版权声明或技术代码，需要重新生成一个符合角色设定的开场白（100-200字，沉浸感强，不含任何链接或技术内容）。"
        else:
            om_hint = "原卡开场白内容合适，opening_message 字段填写 null（保留原卡开场白，不替换）。"
    else:
        om_hint = "原卡没有开场白，需要根据角色设定生成一个（100-150字，符合角色性格和故事背景）。"

    prompt = textwrap.dedent(f"""
    你是一个角色卡分析助手。我会给你一张 AI 角色卡的原始内容，请你分析后输出一个 JSON 对象。

    ## 角色名
    {char_name}

    ## 卡类型
    {card_type}（intimate=亲密对话角色 / scenario=剧情沙盒 / world=世界探索卡）

    ## 原始内容

    【角色描述】
    {description or '（空）'}

    【性格】
    {personality or '（空）'}

    【场景设定】
    {scenario or '（空）'}

    【原卡开场白】
    {first_mes or '（空）'}

    【备用开场白第一条】
    {first_alt or '（空）'}

    ## 输出要求

    请严格输出以下 JSON 格式，不要加任何其他文字：

    {{
      "subtitle": "30-60字的简介，面向用户，有吸引力，不含技术信息，不含链接，语气自然",
      "tags": ["标签1", "标签2", "标签3", "标签4", "标签5"],
      "opening_message": "新开场白文本，或者 null（如果原卡开场白可以直接用）"
    }}

    {type_hint}

    subtitle 要求：
    - 不超过 60 字，不少于 20 字
    - 描述角色的核心魅力和故事背景
    - 语气自然，像是向用户介绍这个角色
    - 不要包含 "AI"、"模拟"、"系统" 等技术词汇

    tags 要求：
    - 恰好 5 个标签
    - 每个标签 2-6 字
    - {type_hint}
    - 不包含技术标签（如 hybrid、character、system）

    opening_message 要求：
    {om_hint}

    只输出 JSON，不要任何解释，不要 markdown 代码块。
    """).strip()

    return prompt


# ── 核心分析逻辑 ──────────────────────────────────────────────────────────────
def analyze_character(
    char_id: str,
    char_name: str,
    raw_card_json: str,
    card_type: str,
    current_opening: str,
    ai_config: dict[str, str],
    dry_run: bool = False,
) -> dict | None:
    """
    调用 AI 分析一张角色卡，返回解析后的字段字典。
    dry_run=True 时只打印 prompt，不实际调用 AI。
    """
    prompt = build_analysis_prompt(char_name, raw_card_json, card_type)

    if dry_run:
        print(f"\n{'='*60}")
        print(f"[DRY RUN] {char_name} 的分析 prompt：")
        print(prompt[:1000] + ("..." if len(prompt) > 1000 else ""))
        return None

    print(f"  → 正在调用 AI 分析「{char_name}」...", flush=True)
    try:
        raw_output = call_ai(
            prompt=prompt,
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["model"],
        )
    except Exception as e:
        print(f"  ✗ AI 调用失败: {e}")
        return None

    # 清理 AI 输出：
    # 1. 剥掉思考链标签（<think>...</think>），MiniMax M2.5 推理模式会带这个
    import re as _re
    raw_no_think = _re.sub(r'<think>.*?</think>', '', raw_output, flags=_re.DOTALL).strip()
    cleaned = raw_no_think if raw_no_think else raw_output.strip()

    # 2. 去掉 markdown 代码块包装（```json ... ``` 或 ``` ... ```）
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # 去掉首行（```json 或 ```）和末行（```）
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # 3. 如果还是没有找到 JSON，尝试从输出里提取第一个 { ... } 块
    if not cleaned.strip().startswith("{"):
        m = _re.search(r'\{[\s\S]*\}', cleaned)
        if m:
            cleaned = m.group(0)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"  ✗ AI 输出不是合法 JSON: {e}")
        print(f"    原始输出: {raw_output[:300]}")
        return None

    # 校验字段
    if not result.get("subtitle") or not result.get("tags"):
        print(f"  ✗ AI 输出缺少必要字段: {result}")
        return None

    # opening_message 处理：null 表示保留原来的
    if result.get("opening_message") is None:
        result["opening_message"] = current_opening

    return result


# ── 写入数据库 ────────────────────────────────────────────────────────────────
def save_to_db(char_id: str, char_name: str, fields: dict) -> None:
    """将分析结果写入数据库，并设置 import_locked=1。"""
    conn = get_conn()
    cur = conn.cursor()

    try:
        tags_json = json.dumps(fields["tags"], ensure_ascii=False)
        cur.execute(
            """
            update characters
            set subtitle=?,
                tags=?,
                opening_message=?,
                import_locked=1
            where id=?
            """,
            (
                fields["subtitle"],
                tags_json,
                fields.get("opening_message", ""),
                char_id,
            ),
        )
        conn.commit()
        print(f"  ✓ 已写入数据库并锁定：{char_name}")
        print(f"    subtitle: {fields['subtitle']}")
        print(f"    tags: {fields['tags']}")
    except Exception as e:
        conn.rollback()
        print(f"  ✗ 写入失败: {e}")
    finally:
        conn.close()


# ── CLI 入口 ──────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="角色卡 AI 分析工具 - 自动生成 subtitle / tags / opening_message",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--name", "-n", help="角色名称（支持模糊匹配），不填则处理所有未锁定的卡")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有卡及其锁定状态，不执行分析")
    parser.add_argument("--force", "-f", action="store_true", help="强制重新分析（包括已锁定的卡）")
    parser.add_argument("--dry-run", "-d", action="store_true", help="只打印 prompt，不实际调用 AI")
    args = parser.parse_args()

    # 读取 AI 配置
    env = load_env()
    from model_adapter import DEFAULT_AI_BASE_URL, DEFAULT_AI_MODEL
    ai_config = {
        "api_key": (env.get("AIFRIEND_API_KEY") or "").strip(),
        "base_url": (env.get("AIFRIEND_BASE_URL") or DEFAULT_AI_BASE_URL).strip().rstrip("/"),
        "model": (env.get("AIFRIEND_MODEL") or DEFAULT_AI_MODEL).strip(),
    }

    if not ai_config["api_key"] and not args.list and not args.dry_run:
        print("✗ 错误：未找到 AIFRIEND_API_KEY，请检查 .env 文件")
        sys.exit(1)

    # 连接数据库
    if not DB_PATH.exists():
        print(f"✗ 数据库不存在：{DB_PATH}")
        sys.exit(1)

    conn = get_conn()

    # 查询目标角色
    if args.name:
        rows = conn.execute(
            "select id, name, card_type, import_locked, opening_message, raw_card_json from characters where name like ?",
            (f"%{args.name}%",),
        ).fetchall()
    elif args.force:
        rows = conn.execute(
            "select id, name, card_type, import_locked, opening_message, raw_card_json from characters"
        ).fetchall()
    else:
        rows = conn.execute(
            "select id, name, card_type, import_locked, opening_message, raw_card_json from characters where import_locked=0"
        ).fetchall()

    conn.close()

    # --list 模式：只打印状态
    if args.list:
        all_rows = get_conn().execute(
            "select name, card_type, import_locked, is_visible, home_priority from characters order by home_priority, name"
        ).fetchall()
        print(f"\n{'角色名':<20} {'类型':<12} {'已锁定':<8} {'可见':<6} {'首页优先级'}")
        print("-" * 65)
        for r in all_rows:
            locked_str = "✅ 已锁定" if r["import_locked"] else "⚠️ 未锁定"
            visible_str = "✓" if r["is_visible"] else "✗"
            print(f"{r['name']:<20} {r['card_type']:<12} {locked_str:<10} {visible_str:<6} {r['home_priority']}")
        get_conn().close()
        return

    if not rows:
        print("✓ 没有需要分析的角色卡（所有卡已锁定，或找不到匹配的角色名）")
        return

    print(f"\n共找到 {len(rows)} 张待分析卡片\n")

    for row in rows:
        char_id = row["id"]
        char_name = row["name"]
        card_type = row["card_type"] or "intimate"
        current_opening = row["opening_message"] or ""
        raw_card_json = row["raw_card_json"] or "{}"

        print(f"\n[{char_name}] card_type={card_type}")

        if not raw_card_json or raw_card_json == "{}":
            print("  ⚠ 无原始卡片数据（raw_card_json 为空），跳过")
            continue

        # 执行分析
        result = analyze_character(
            char_id=char_id,
            char_name=char_name,
            raw_card_json=raw_card_json,
            card_type=card_type,
            current_opening=current_opening,
            ai_config=ai_config,
            dry_run=args.dry_run,
        )

        if result and not args.dry_run:
            save_to_db(char_id, char_name, result)

    print("\n✓ 全部完成")


if __name__ == "__main__":
    main()
