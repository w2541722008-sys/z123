# 数据库备份指南

## 备份脚本使用

### 手动备份
```bash
cd /path/to/aifriend/backend
python backup_db.py
```

### 列出所有备份
```bash
python backup_db.py --list
```

### 恢复数据库
```bash
python backup_db.py --restore
```

## 定时备份配置

### Linux/macOS (crontab)

1. **编辑 crontab**
```bash
crontab -e
```

2. **添加定时任务**

每天凌晨 2 点备份：
```cron
0 2 * * * cd /path/to/aifriend/backend && /usr/bin/python3 backup_db.py >> /path/to/logs/backup.log 2>&1
```

每 6 小时备份一次：
```cron
0 */6 * * * cd /path/to/aifriend/backend && /usr/bin/python3 backup_db.py >> /path/to/logs/backup.log 2>&1
```

每周日凌晨 3 点备份：
```cron
0 3 * * 0 cd /path/to/aifriend/backend && /usr/bin/python3 backup_db.py >> /path/to/logs/backup.log 2>&1
```

3. **查看当前的 crontab**
```bash
crontab -l
```

### 注意事项

- 将 `/path/to/aifriend/backend` 替换为实际的项目路径
- 将 `/usr/bin/python3` 替换为实际的 Python 路径（使用 `which python3` 查看）
- 创建日志目录：`mkdir -p /path/to/logs`
- 确保脚本有执行权限：`chmod +x backup_db.py`

## 备份策略建议

### 生产环境
- **频率**：每天至少备份一次
- **时间**：选择业务低峰期（如凌晨 2-4 点）
- **保留**：至少保留 7 天的备份（脚本默认配置）

### 开发环境
- **频率**：每周备份一次即可
- **时间**：任意时间
- **保留**：保留 3-5 个备份即可

## 备份文件位置

- **数据库文件**：`backend/data/aifriend.db`
- **备份目录**：`backend/data/backups/`
- **备份文件命名**：`aifriend_backup_YYYYMMDD_HHMMSS.db`

## 恢复流程

1. 列出可用备份：
```bash
python backup_db.py --list
```

2. 选择要恢复的备份：
```bash
python backup_db.py --restore
```

3. 按提示输入备份编号

4. 确认恢复操作（输入 `yes`）

**注意**：恢复前会自动备份当前数据库，确保数据安全。

## 监控备份状态

### 查看备份日志
```bash
tail -f /path/to/logs/backup.log
```

### 检查备份文件
```bash
ls -lh backend/data/backups/
```

### 验证备份完整性
```bash
# 使用 SQLite 命令行工具检查备份文件
sqlite3 backend/data/backups/aifriend_backup_YYYYMMDD_HHMMSS.db "PRAGMA integrity_check;"
```

## 故障排查

### 备份失败
1. 检查磁盘空间：`df -h`
2. 检查文件权限：`ls -l backend/data/`
3. 查看错误日志：`cat /path/to/logs/backup.log`

### cron 任务未执行
1. 检查 cron 服务状态：`systemctl status cron` (Linux) 或 `sudo launchctl list | grep cron` (macOS)
2. 检查 crontab 语法：`crontab -l`
3. 查看系统日志：`grep CRON /var/log/syslog` (Linux)

### 恢复失败
1. 确认备份文件完整性
2. 检查数据库文件权限
3. 确保没有其他进程占用数据库文件
