#!/bin/bash

# Supabase 数据库备份脚本
# 使用方法: ./backup_supabase.sh

# 备份目录
BACKUP_DIR="/opt/aifriend/backups"
mkdir -p $BACKUP_DIR

# 备份文件名（带时间戳）
BACKUP_FILE="$BACKUP_DIR/backup_$(date +%Y%m%d_%H%M%S).sql"

# 从 .env 读取数据库连接信息
if [ -f "/opt/aifriend/backend/.env" ]; then
    source /opt/aifriend/backend/.env
else
    echo "错误: 找不到 .env 文件"
    exit 1
fi

# 检查 DATABASE_URL 是否存在
if [ -z "$DATABASE_URL" ]; then
    echo "错误: DATABASE_URL 未设置"
    exit 1
fi

# 执行备份
echo "开始备份数据库..."
pg_dump $DATABASE_URL > $BACKUP_FILE

# 检查备份是否成功
if [ $? -eq 0 ]; then
    # 压缩备份
    gzip $BACKUP_FILE
    echo "备份完成: $BACKUP_FILE.gz"
    
    # 删除 7 天前的备份
    find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete
    echo "已清理 7 天前的旧备份"
else
    echo "错误: 备份失败"
    exit 1
fi
