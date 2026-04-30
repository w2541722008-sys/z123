# VPS 部署主文档

本文档以当前仓库脚本为准，适用于项目生产目录 `/opt/aifriend`。

## 目标架构

- 应用目录：`/opt/aifriend`
- 后端进程：`uvicorn main:app --host 0.0.0.0 --port 8000`
- 反向代理：Nginx/OpenResty（将 `/api` 与静态资源转发到后端）
- 数据库：Supabase PostgreSQL

## 首次部署

### 1. 准备服务器

- 安装 Python 3.10+
- 安装依赖：`pip3 install -r /opt/aifriend/backend/requirements.txt`
- 准备项目目录：`/opt/aifriend`

### 2. 配置环境变量

- 复制：`backend/.env.example -> backend/.env`
- 核心变量：
  - `DATABASE_URL`
  - `AIFRIEND_API_KEY`
  - `AIFRIEND_BASE_URL`
  - `AIFRIEND_MODEL`
  - `ALLOWED_ORIGINS`
  - `RESEND_API_KEY`
  - `ADMIN_EMAILS`

### 3. 初始化数据库

- 执行 `docs/supabase_schema.sql`
- 再执行 `docs/migrations/001_add_message_versions.sql`（用于 `chat_messages.versions`）

### 4. 启动服务

```bash
cd /opt/aifriend/backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## 日常发布（推荐）

在本地执行：

```bash
cd /Users/jjj/aifriend
bash deploy.sh
```

脚本行为：

- 本地测试门禁
- 远端备份当前版本
- rsync 同步
- 远端重启
- 健康检查

补充脚本：

- `verify_server.sh`：在服务器执行环境与健康巡检
- `deploy_to_server.sh`：兼容旧入口，内部直接转发到 `deploy.sh`

## 回滚

```bash
ssh root@45.76.182.245
cd /opt
ls -d backup_*
rm -rf aifriend
cp -r backup_XXXXXX aifriend
cd aifriend && bash restart.sh
```

## 关键健康检查

- `curl -s http://localhost:8000/api/health`
- `ps aux | grep uvicorn`
- `tail -f /var/log/aifriend.log`

可执行快速巡检：

```bash
cd /opt/aifriend
bash verify_server.sh
```

## 常见问题

- 健康检查 degraded：优先检查 `DATABASE_URL` 与生产环境配置缺失项。
- 登录/邮件异常：检查 `RESEND_API_KEY`、邮箱域名发信配置。
- 后台无法访问：确认 `/admin.html` 或 `/frontend/admin/index.html` 的静态文件与代理路径可达。
