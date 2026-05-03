# VPS 部署主文档

适用于项目生产目录 `/opt/aifriend`。

## 目标架构

- 应用目录：`/opt/aifriend`
- 后端进程：`uvicorn main:app --host 127.0.0.1 --port 8000`（systemd 管理）
- 反向代理：Nginx（HTTPS + `/api` 与静态资源转发）
- 数据库：Supabase PostgreSQL
- 数据库迁移：Alembic（`backend/alembic/`）

## 首次部署

### 1. 准备服务器

```bash
bash setup_server.sh
```

脚本自动完成：Python venv、Nginx 配置、systemd 服务、防火墙、swap、日志轮转。

### 2. 配置环境变量

- 复制 `backend/.env.example` → `backend/.env`
- 核心变量：`DATABASE_URL`、`AIFRIEND_API_KEY`、`AIFRIEND_BASE_URL`、`AIFRIEND_MODEL`、`ALLOWED_ORIGINS`、`ADMIN_EMAILS`
- 邮件服务：SMTP 或 Resend 任一即可
- `ENV=production` + `DEBUG=false`

### 3. 初始化数据库

```bash
cd /opt/aifriend/backend
python3 -m alembic upgrade head
```

迁移说明：

- `001_initial_schema.py`：基线迁移，创建全部 18 张表
- `002_text_to_timestamptz_jsonb.py`：类型修复，幂等可重跑
- `003_add_reset_code_attempt_count.py`：密码重试计数列，幂等

### 4. 启动服务

```bash
sudo systemctl start aifriend
sudo systemctl enable aifriend
```

### 5. 配置 SSL

```bash
sudo certbot --nginx -d lunawhisp.com
```

## 日常发布

```bash
bash deploy.sh
```

脚本流程（7 步）：

1. 检查 SSH 连接
2. 本地门禁（pytest + 前端测试）
3. 远端备份（自动清理，保留最新 1 份）
4. rsync 同步到 `/opt/aifriend`
5. 远端 Alembic 迁移 + 重启 uvicorn
6. 健康检查门禁（失败提示回滚）
7. 输出结果

## 回滚

```bash
bash rollback.sh                  # 交互式，自动选择最新备份
bash rollback.sh --to backup_YYYYMMDD_HHMMSS  # 指定备份
```

> 回滚后若数据库迁移已执行，需评估是否需要 `alembic downgrade`。

## 健康检查

```bash
curl -s https://lunawhisp.com/api/health
sudo systemctl status aifriend
tail -f /var/log/aifriend.log
```

## 常见问题

- 健康检查 degraded：检查 `DATABASE_URL` 与 `.env` 配置
- 邮件异常：检查 SMTP 配置或 `RESEND_API_KEY`
- 迁移失败：002/003 均为幂等设计，可重跑 `alembic upgrade head`
- 日志无轮转：检查 `/etc/logrotate.d/aifriend` 是否存在
