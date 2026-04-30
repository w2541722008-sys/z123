# 数据库备份指南

适用环境：生产服务器 `/opt/aifriend`

## 脚本位置

- `backend/backup_supabase.sh`

脚本行为：

1. 从 `/opt/aifriend/backend/.env` 读取 `DATABASE_URL`
2. 执行 `pg_dump`
3. 生成并压缩备份到 `/opt/aifriend/backups/backup_YYYYMMDD_HHMMSS.sql.gz`
4. 默认自动清理 7 天前备份（可通过 `RETENTION_DAYS` 覆盖）

## 手动备份

```bash
bash /opt/aifriend/backend/backup_supabase.sh
```

自定义保留天数：

```bash
RETENTION_DAYS=14 bash /opt/aifriend/backend/backup_supabase.sh
```

## 查看备份

```bash
ls -lh /opt/aifriend/backups/
```

## 恢复备份

```bash
gunzip /opt/aifriend/backups/backup_YYYYMMDD_HHMMSS.sql.gz
source /opt/aifriend/backend/.env
psql "$DATABASE_URL" < /opt/aifriend/backups/backup_YYYYMMDD_HHMMSS.sql
```

## 定时备份（Linux）

```bash
crontab -e
0 3 * * * /opt/aifriend/backend/backup_supabase.sh >> /opt/aifriend/logs/backup.log 2>&1
```

## 常见故障

- `pg_dump: command not found`：安装 PostgreSQL 客户端。
- `DATABASE_URL 未设置`：检查 `.env` 是否存在且变量名正确。
- 备份文件异常小：检查数据库连接串与网络连通性。
