# 数据库备份指南

> **最后更新**: 2026-04-01
> **数据库**: Supabase (PostgreSQL)

---

## 概述

项目使用 Supabase 托管的 PostgreSQL 数据库（共 17 张表），不再使用本地 SQLite。
备份通过 `pg_dump` 工具将远程数据库导出为 SQL 文件并 gzip 压缩。

---

## 备份脚本

### 脚本位置

```
backend/backup_supabase.sh
```

### 工作原理

1. 从 `backend/.env` 读取 `DATABASE_URL`
2. 使用 `pg_dump` 导出完整数据库为 `.sql` 文件
3. 自动 gzip 压缩
4. 自动删除 7 天前的旧备份
5. 备份保存到 `/opt/aifriend/backups/`

### 前置条件

服务器上需要安装 PostgreSQL 客户端工具（不需要完整 PostgreSQL Server）：

```bash
# Ubuntu/Debian
sudo apt-get install postgresql-client

# CentOS/RHEL
sudo yum install postgresql

# macOS
brew install postgresql
```

---

## 手动备份

### 在服务器上执行

```bash
bash /opt/aifriend/backend/backup_supabase.sh
```

成功输出：
```
开始备份数据库...
备份完成: /opt/aifriend/backups/backup_20260401_030000.sql.gz
已清理 7 天前的旧备份
```

### 查看已有备份

```bash
ls -lh /opt/aifriend/backups/
```

### 本地开发环境备份（可选）

如果你在本地也想手动备份远程 Supabase 数据库：

```bash
# 需要先安装 pg_dump
pg_dump "postgresql://postgres:你的密码@db.xxx.supabase.co:5432/postgres" > backup_$(date +%Y%m%d).sql

# 压缩
gzip backup_$(date +%Y%m%d).sql
```

---

## 恢复数据库

> ⚠️ **恢复操作会覆盖当前数据库的全部数据！执行前务必确认已备份当前状态。**

### 步骤

```bash
# 1. 先备份当前数据库（防止恢复出问题）
bash /opt/aifriend/backend/backup_supabase.sh

# 2. 解压备份文件
gunzip /opt/aifriend/backups/backup_YYYYMMDD_HHMMSS.sql.gz

# 3. 恢复（从 .env 读取 DATABASE_URL）
source /opt/aifriend/backend/.env
psql $DATABASE_URL < /opt/aifriend/backups/backup_YYYYMMDD_HHMMSS.sql

# 4. 确认恢复成功后，可以删除解压后的 .sql 文件
rm /opt/aifriend/backups/backup_YYYYMMDD_HHMMSS.sql
```

---

## 定时备份配置

### Linux（crontab）

```bash
# 编辑 crontab
crontab -e

# 每天凌晨 3 点自动备份
0 3 * * * /opt/aifriend/backend/backup_supabase.sh >> /opt/aifriend/logs/backup.log 2>&1
```

### macOS（launchd）

macOS 推荐使用 launchd 而非 crontab：

```bash
# 1. 创建日志目录
mkdir -p /opt/aifriend/logs

# 2. 创建 plist 文件
cat > ~/Library/LaunchAgents/com.aifriend.backup.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.aifriend.backup</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/opt/aifriend/backend/backup_supabase.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/opt/aifriend/logs/backup.log</string>
    <key>StandardErrorPath</key>
    <string>/opt/aifriend/logs/backup.log</string>
</dict>
</plist>
EOF

# 3. 加载任务
launchctl load ~/Library/LaunchAgents/com.aifriend.backup.plist
```

### 1Panel（推荐，生产服务器）

如果你使用 1Panel 管理面板：

1. 左侧菜单 → **计划任务**
2. 点击 **创建任务**
3. 填写：
   - 任务名称：`数据库备份`
   - 任务类型：Shell 脚本
   - 执行周期：每天 3:00
   - 脚本内容：`/opt/aifriend/backend/backup_supabase.sh`
4. 点击确定

---

## 备份策略建议

### 生产环境（VPS）

| 项目 | 建议 |
|------|------|
| 频率 | 每天至少 1 次 |
| 时间 | 凌晨 3:00（业务低峰期） |
| 保留天数 | 7 天（脚本默认） |
| 验证 | 每月恢复测试 1 次 |

### 额外保障

- **Supabase 自带备份**：Supabase 免费版提供每日自动备份（保留 7 天），可在 Supabase 控制台 → Settings → Database → Backups 查看
- **双重保险**：建议同时启用脚本备份 + Supabase 自带备份

---

## 监控备份状态

### 查看备份日志

```bash
tail -20 /opt/aifriend/logs/backup.log
```

### 检查备份文件

```bash
# 查看备份文件列表和大小
ls -lh /opt/aifriend/backups/

# 确认今天的备份已生成
ls -lht /opt/aifriend/backups/ | head -5
```

### 验证备份完整性

```bash
# 解压后检查 SQL 文件是否能被 psql 解析（不实际执行）
gunzip -c /opt/aifriend/backups/backup_YYYYMMDD_HHMMSS.sql.gz | head -20
```

---

## 故障排查

### pg_dump 命令找不到

```bash
# 确认 pg_dump 已安装
which pg_dump

# 如果没有，安装 PostgreSQL 客户端
sudo apt-get install postgresql-client   # Ubuntu/Debian
```

### 备份失败：连接被拒绝

1. 检查 `.env` 中 `DATABASE_URL` 是否正确
2. 确认 Supabase 项目没有被暂停（免费版 7 天无活动会暂停）
3. 检查服务器网络是否能访问 Supabase（`ping db.xxx.supabase.co`）

### 备份文件为空或异常小

可能是 `DATABASE_URL` 格式不正确。正确格式：

```
postgresql://postgres:[密码]@db.xxx.supabase.co:5432/postgres
```

### cron 任务未执行（Linux）

1. 检查 cron 服务：`sudo systemctl status cron`
2. 检查 crontab 语法：`crontab -l`
3. 检查脚本是否有执行权限：`ls -l /opt/aifriend/backend/backup_supabase.sh`
4. 查看系统日志：`grep CRON /var/log/syslog`
