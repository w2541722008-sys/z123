#!/usr/bin/env python3
"""
数据库备份脚本

功能：
    - 备份 SQLite 数据库文件
    - 自动添加时间戳
    - 保留最近 N 个备份
    - 可以手动运行或通过 cron 定时执行

使用方法：
    手动备份：python backup_db.py
    恢复备份：python backup_db.py --restore
    列出备份：python backup_db.py --list
    定时备份：添加到 crontab
        # 每天凌晨 2 点备份
        0 2 * * * cd /path/to/backend && python backup_db.py
"""

import shutil
from datetime import datetime
from pathlib import Path

# 配置
DB_PATH = Path(__file__).parent / "data" / "aifriend.db"
BACKUP_DIR = Path(__file__).parent / "data" / "backups"
MAX_BACKUPS = 7  # 保留最近 7 个备份


def backup_database():
    """备份数据库文件。"""
    # 检查数据库文件是否存在
    if not DB_PATH.exists():
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return False
    
    # 创建备份目录
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    # 生成备份文件名（带时间戳）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"aifriend_backup_{timestamp}.db"
    
    try:
        # 复制数据库文件
        shutil.copy2(DB_PATH, backup_file)
        print(f"✅ 备份成功: {backup_file}")
        
        # 清理旧备份
        cleanup_old_backups()
        
        return True
    except Exception as e:
        print(f"❌ 备份失败: {e}")
        return False


def cleanup_old_backups():
    """删除超过保留数量的旧备份。"""
    # 获取所有备份文件，按修改时间排序
    backups = sorted(
        BACKUP_DIR.glob("aifriend_backup_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    
    # 删除超出保留数量的备份
    for old_backup in backups[MAX_BACKUPS:]:
        try:
            old_backup.unlink()
            print(f"🗑️  删除旧备份: {old_backup.name}")
        except Exception as e:
            print(f"⚠️  删除失败: {old_backup.name} - {e}")


def list_backups():
    """列出所有可用的备份文件。"""
    if not BACKUP_DIR.exists():
        print("❌ 备份目录不存在")
        return []
    
    backups = sorted(
        BACKUP_DIR.glob("aifriend_backup_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    
    if not backups:
        print("📁 没有找到备份文件")
        return []
    
    print(f"\n📁 找到 {len(backups)} 个备份文件：\n")
    for i, backup in enumerate(backups, 1):
        size_mb = backup.stat().st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(backup.stat().st_mtime)
        print(f"  {i}. {backup.name}")
        print(f"     大小: {size_mb:.2f} MB")
        print(f"     时间: {mtime.strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    return backups


def restore_database():
    """从备份恢复数据库。"""
    backups = list_backups()
    
    if not backups:
        return False
    
    # 让用户选择要恢复的备份
    try:
        choice = input("\n请输入要恢复的备份编号（输入 0 取消）: ").strip()
        choice_num = int(choice)
        
        if choice_num == 0:
            print("❌ 取消恢复")
            return False
        
        if choice_num < 1 or choice_num > len(backups):
            print("❌ 无效的编号")
            return False
        
        selected_backup = backups[choice_num - 1]
        
        # 确认操作
        print(f"\n⚠️  警告：此操作将覆盖当前数据库！")
        print(f"   将从以下备份恢复: {selected_backup.name}")
        confirm = input("   确认恢复？(yes/no): ").strip().lower()
        
        if confirm != "yes":
            print("❌ 取消恢复")
            return False
        
        # 在恢复前备份当前数据库
        if DB_PATH.exists():
            print("\n📦 正在备份当前数据库...")
            backup_database()
        
        # 执行恢复
        print(f"\n🔄 正在恢复数据库...")
        shutil.copy2(selected_backup, DB_PATH)
        print(f"✅ 恢复成功: {selected_backup.name} -> {DB_PATH.name}")
        
        return True
        
    except ValueError:
        print("❌ 请输入有效的数字")
        return False
    except KeyboardInterrupt:
        print("\n❌ 操作已取消")
        return False
    except Exception as e:
        print(f"❌ 恢复失败: {e}")
        return False


if __name__ == "__main__":
    import sys
    
    # 解析命令行参数
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "--list":
            print("=" * 50)
            print("数据库备份列表")
            print("=" * 50)
            list_backups()
            print("=" * 50)
        
        elif command == "--restore":
            print("=" * 50)
            print("数据库恢复")
            print("=" * 50)
            restore_database()
            print("=" * 50)
        
        else:
            print("❌ 未知命令")
            print("\n使用方法：")
            print("  python backup_db.py           # 备份数据库")
            print("  python backup_db.py --list    # 列出所有备份")
            print("  python backup_db.py --restore # 恢复数据库")
    
    else:
        # 默认执行备份
        print("=" * 50)
        print("开始数据库备份...")
        print("=" * 50)
        backup_database()
        print("=" * 50)
