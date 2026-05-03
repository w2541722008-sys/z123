# VPS 部署主文档

本文档以当前仓库脚本为准，适用于项目生产目录 `/opt/aifriend`。

## 目标架构

- 应用目录：`/opt/aifriend`
- 后端进程：`uvicorn main:app --host 127.0.0.1 --port 8000`（systemd 管理）
- 反向代理：Nginx/OpenResty（将 `/api` 与静态资源转发到后端）
- 数据库：Supabase PostgreSQL
- 数据库迁移：Alembic（`backend/alembic/`）

## 首次部署

### 1. 准备服务器

- 安装 Python 3.10+
- 安装依赖：`pip3 install -r /opt/aifriend/backend/requirements.txt`
- 准备项目目录：`/opt/aifriend`
- 推荐使用 `setup_server.sh` 一键初始化

### 2. 配置环境变量

- 复制：`backend/.env.example -> backend/.env`
- 核心变量：
  - `DATABASE_URL`：Supabase 连接字符串
  - `AIFRIEND_API_KEY`：AI 模型 API Key
  - `AIFRIEND_BASE_URL`：AI 模型 Base URL
  - `AIFRIEND_MODEL`：AI 模型名称
  - `ALLOWED_ORIGINS`：CORS 允许的域名
  - `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD`：邮件服务配置
  - `ADMIN_EMAILS`：管理员邮箱

### 3. 初始化数据库

使用 Alembic 自动迁移（推荐）：

```bash
cd /opt/aifriend/backend
python3 -m alembic upgrade head
```

迁移说明：

- `001_initial_schema.py`：基线迁移，创建全部 18 张表（含 `chat_messages.versions` 列）
- `002_text_to_timestamptz_jsonb.py`：类型修复（33 列 text → timestamptz、11 列 text → jsonb），幂等可重跑

> ⚠️ 旧版 SQL 迁移文件（`docs/supabase_schema.sql`、`docs/migrations/`）已由 Alembic 替代，新环境无需手动执行。

### 4. 启动服务

```bash
cd /opt/aifriend/backend
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
```

或使用 systemd：

```bash
sudo systemctl start aifriend
sudo systemctl enable aifriend
```

## 日常发布（推荐）

在本地执行：

```bash
cd /Users/jjj/aifriend
bash deploy.sh
```

脚本行为：

1. 检查 SSH 连接
2. 本地门禁（pytest + 前端测试）
3. 远端备份当前版本
4. rsync 同步到 `/opt/aifriend`
5. 远端执行 Alembic 数据库迁移
6. 远端重启 uvicorn
7. 健康检查

补充脚本：

- `verify_server.sh`：在服务器执行环境与健康巡检

## 回滚

```bash
ssh ubuntu@124.156.199.146
cd /opt
ls -d backup_*
rm -rf aifriend
cp -r backup_XXXXXX aifriend
cd aifriend && bash restart.sh
```

> ⚠️ 回滚后若数据库迁移已执行，需单独评估是否需要降级迁移（`alembic downgrade`）。

## 关键健康检查

- `curl -s http://localhost:8000/api/health`
- `ps aux | grep uvicorn`
- `tail -f /var/log/aifriend.log`
- `sudo systemctl status aifriend`

可执行快速巡检：

```bash
cd /opt/aifriend
bash verify_server.sh
```

## 常见问题

- 健康检查 degraded：优先检查 `DATABASE_URL` 与生产环境配置缺失项。
- 登录/邮件异常：检查 SMTP 配置或 `RESEND_API_KEY`、邮箱域名发信配置。
- 后台无法访问：确认 `/admin.html` 的静态文件与代理路径可达。
- 数据库迁移失败：检查 `alembic/versions/` 迁移脚本，002 迁移为幂等设计可重跑。
