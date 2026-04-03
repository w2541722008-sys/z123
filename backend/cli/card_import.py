"""
card_import.py —— 手动导入单张 PNG 角色卡
===========================================

用法：
    python card_import.py --path /path/to/角色.png
    python card_import.py --path ../角色卡/新角色.png
    python card_import.py --list          # 查看数据库里现有角色
    python card_import.py --dry-run --path xxx.png  # 只解析不写库

注意：
- 导入后角色处于 import_locked=0 状态，展示字段是 PNG 原始数据
- 需要接着跑 card_analyze.py 做 AI 分析，填好展示字段并设 import_locked=1
- 已导入的卡（import_locked=1）不会被覆盖展示字段，但技术字段会更新

完整流程：
  1. card_import.py --path xxx.png     （解析 PNG，写入数据库）
  2. card_analyze.py --name 角色名     （AI 分析，填展示字段，设 import_locked=1）
  3. 人工复核，确认 subtitle/tags/opening_message
  4. main.py 里配置 is_visible/home_priority（如需前台展示）
"""

import argparse
import json
import os
import sys
from pathlib import Path

# ── 路径设置 ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent  # cli/ → backend/

# 把 backend/ 加入模块搜索路径
sys.path.insert(0, str(BASE_DIR))

# 加载环境变量（必须在导入 database 之前）
from config import load_env_file

load_env_file()

from card_asset_parser import build_import_record, canonical_card_stem  # noqa: E402
from database import get_conn  # noqa: E402


# ── 连接数据库 ───────────────────────────────────────────────────────────────
# 现在使用 database.py 中的 PostgreSQL 连接


def list_characters() -> None:
    """列出当前数据库里所有角色的状态。"""
    conn = get_conn()
    rows = conn.execute(
        "select name, id, import_locked, is_visible, home_priority, source_path "
        "from characters order by home_priority, name"
    ).fetchall()
    conn.close()

    if not rows:
        print("数据库里还没有角色。")
        return

    print(f"=== 数据库当前共 {len(rows)} 张角色卡 ===\n")
    for r in rows:
        lock_icon = "🔒 已锁定" if r["import_locked"] else "🔓 未锁定"
        vis_icon = "✅ 可见" if r["is_visible"] else "🚫 隐藏"
        priority_str = f"优先级={r['home_priority']}" if r["home_priority"] < 900 else "不在前台"
        print(f"  [{lock_icon}] [{vis_icon}] [{priority_str}] {r['name']}")
        print(f"      id={r['id']}")
        if r["source_path"]:
            print(f"      来源={r['source_path']}")
        print()


def import_png(png_path: Path, dry_run: bool = False) -> None:
    """解析指定 PNG 文件，写入数据库（干跑模式只打印不写库）。"""
    if not png_path.exists():
        print(f"❌ 文件不存在：{png_path}")
        sys.exit(1)

    print(f"正在解析：{png_path.name} ...")

    # 构造 source 字典，card_asset_parser 用这个格式读取 PNG
    source = {
        "canonical_name": canonical_card_stem(png_path),
        "primary_path": png_path,   # Path 对象，load_card_source 需要
        "png_path": png_path,
        "source_kind": "png",
        "source_path": str(png_path),
    }

    try:
        record = build_import_record(source, sort_order=0)
    except Exception as e:
        print(f"❌ 解析失败：{e}")
        sys.exit(1)

    if record is None:
        print("❌ 解析失败：文件可能不是有效的 SillyTavern PNG 角色卡。")
        sys.exit(1)

    # 基础信息打印
    print(f"\n✅ 解析成功")
    print(f"   角色名：{record.get('name', '(未知)')}")
    print(f"   ID：{record.get('id', '(未知)')}")
    print(f"   subtitle：{(record.get('subtitle', '') or '')[:80]}")
    print(f"   tags：{record.get('tags', [])}")
    print(f"   opening_message：{(record.get('opening_message', '') or '')[:100]}...")
    print(f"   system_prompt 长度：{len(record.get('system_prompt', '') or '')} 字符")

    diag_raw = record.get("import_diagnostics", "[]")
    try:
        diag = json.loads(diag_raw) if isinstance(diag_raw, str) else (diag_raw or [])
    except Exception:
        diag = []
    if diag:
        print(f"\n   ⚠️  解析诊断：{len(diag)} 条提示")
        for d in diag[:5]:
            print(f"      - {d}")

    if dry_run:
        print("\n[dry-run 模式：以上仅为预览，未写入数据库]")
        return

    # 检查是否已存在
    conn = get_conn()
    existing = conn.execute(
        "select id, name, import_locked from characters where id = %s",
        (record["id"],)
    ).fetchone()

    if existing:
        print(f"\n   ⚠️  角色 [{existing['name']}] 已在数据库中（id={existing['id']}）")
        if existing["import_locked"]:
            print("   📌 该卡已锁定（import_locked=1）")
            print("   → 技术字段（system_prompt/raw_card_json 等）将更新")
            print("   → 展示字段（subtitle/tags/opening_message）保持不变")
        else:
            print("   → 该卡未锁定，所有字段将更新（含展示字段）")

        confirm = input("\n继续写入？[y/N] ").strip().lower()
        if confirm != "y":
            print("已取消。")
            conn.close()
            return

    # 写入数据库（UPSERT）
    # 技术字段：始终更新
    # 展示字段：import_locked=1 时保留库里的值（由 CASE WHEN 实现）
    cur = conn.cursor()
    cur.execute(
        """
        insert into characters (
            id, name, abbr, subtitle, avatar_url, cover_url, description,
            tags, opening_message, system_prompt, sort_order, mock_reply_style,
            asset_type, source_kind, source_path, embedded_format, raw_card_json,
            structured_asset_json, runtime_cache_json, import_diagnostics,
            is_visible, home_priority, card_type, import_locked
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
        on conflict(id) do update set
            -- 技术字段：始终跟随 PNG 更新（原始素材）
            name=excluded.name,
            abbr=excluded.abbr,
            avatar_url=excluded.avatar_url,
            cover_url=excluded.cover_url,
            system_prompt=excluded.system_prompt,
            sort_order=excluded.sort_order,
            mock_reply_style=excluded.mock_reply_style,
            asset_type=excluded.asset_type,
            source_kind=excluded.source_kind,
            source_path=excluded.source_path,
            embedded_format=excluded.embedded_format,
            raw_card_json=excluded.raw_card_json,
            structured_asset_json=excluded.structured_asset_json,
            import_diagnostics=excluded.import_diagnostics,
            -- 展示字段：import_locked=1 时保留库里的值
            subtitle=case when characters.import_locked = 1
                          then characters.subtitle else excluded.subtitle end,
            description=excluded.description,
            tags=case when characters.import_locked = 1
                      then characters.tags else excluded.tags end,
            opening_message=case when characters.import_locked = 1
                                 then characters.opening_message
                                 else excluded.opening_message end,
            runtime_cache_json=case when characters.import_locked = 1
                                    then characters.runtime_cache_json
                                    else excluded.runtime_cache_json end,
            -- 配置字段
            is_visible=characters.is_visible,
            home_priority=characters.home_priority,
            card_type=case when characters.card_type != 'intimate'
                           then characters.card_type else excluded.card_type end,
            import_locked=characters.import_locked
        """,
        (
            record["id"],
            record["name"],
            record.get("abbr", record["name"]),
            record.get("subtitle", ""),
            record.get("avatar_path", ""),
            record.get("cover_path", ""),
            record.get("description", ""),
            json.dumps(record.get("tags", []), ensure_ascii=False),
            record.get("opening_message", ""),
            record.get("system_prompt", ""),
            record.get("sort_order", 0),
            json.dumps(record.get("mock_reply_style", []), ensure_ascii=False),
            record.get("asset_type", "character"),
            record.get("source_kind", "png"),
            str(png_path),
            record.get("embedded_format", "json"),
            record.get("raw_card_json", ""),
            record.get("structured_asset_json", ""),
            record.get("runtime_cache_json", ""),
            record.get("import_diagnostics", "[]"),
            0,    # is_visible：默认隐藏，整理好后手动开放
            999,  # home_priority：默认不在前台
            record.get("card_type", "intimate"),
        ),
    )
    conn.commit()
    conn.close()

    print(f"\n✅ 写入完成！角色 [{record['name']}] 已进入数据库（import_locked=0）")
    print(f"\n下一步：运行 AI 分析工具，填写展示字段：")
    print(f"  python card_analyze.py --name \"{record['name']}\"")


# ── 命令行入口 ───────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="手动导入单张 PNG 角色卡到数据库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python card_import.py --list
  python card_import.py --path ../character_cards/新角色.png
  python card_import.py --dry-run --path ../character_cards/新角色.png
        """,
    )
    parser.add_argument("--path", type=Path, help="要导入的 PNG 文件路径")
    parser.add_argument("--list", action="store_true", help="列出当前数据库里的所有角色")
    parser.add_argument("--dry-run", action="store_true", help="只解析预览，不写入数据库")
    args = parser.parse_args()

    if args.list:
        list_characters()
        return

    if not args.path:
        parser.print_help()
        print("\n错误：请提供 --path 参数指定要导入的 PNG 文件。")
        sys.exit(1)

    import_png(args.path.resolve(), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
