# AIFriend（Lunar）

面向女性用户的 AI 角色扮演聊天 Web 应用。前端为原生 JavaScript（IIFE 模块），后端为 FastAPI + PostgreSQL（Supabase）。

## 项目现状

- 前端用户站：`/`（`index.html` + `frontend/modules/`）
- 管理后台：`/admin.html`
- 后端 API：`/api/*`
- 健康检查：`/api/health`

## 技术栈

- 后端：Python 3.10+、FastAPI、Uvicorn、httpx、psycopg2（ThreadedConnectionPool）
- 数据库：PostgreSQL（Supabase）+ Alembic 迁移
- 前端：原生 HTML/CSS/JavaScript（IIFE）
- 测试：pytest（878 tests）+ Node.js 脚本

## 本地开发

### 1) 安装依赖

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 配置环境变量

- 复制 `backend/.env.example` 为 `backend/.env`
- 至少配置：`DATABASE_URL`、`AIFRIEND_API_KEY`、`AIFRIEND_BASE_URL`、`AIFRIEND_MODEL`
- 邮件服务：SMTP 或 Resend 任一即可

### 3) 初始化数据库

```bash
cd backend && python3 -m alembic upgrade head
```

迁移说明：

- `001_initial_schema.py`：基线迁移，创建全部 18 张表
- `002_text_to_timestamptz_jsonb.py`：类型修复（幂等可重跑）
- `003_add_reset_code_attempt_count.py`：密码重试计数列（幂等）

### 4) 启动后端

```bash
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## 测试与质量门禁

```bash
cd backend
python3 -m pytest ../tests/ -q --ignore=../tests/integration

cd ..
node tests/test_frontend_utils.js
node tests/check_admin_actions.js --strict --allow-list=tests/admin_action_allowlist.json
```

## 一键部署

```bash
bash deploy.sh
```

`deploy.sh` 执行：SSH 检查 → 本地门禁 → 服务器备份 → rsync 同步 → 数据库迁移 → 重启服务 → 健康检查门禁

回滚：`bash rollback.sh`

## 文档导航

- 总导航：[docs/README.md](docs/README.md)
- 部署主文档：[docs/DEPLOYMENT_GUIDE_VPS.md](docs/DEPLOYMENT_GUIDE_VPS.md)
- 上线检查清单：[docs/DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md)
- 后端接口文档：[docs/backend_api.md](docs/backend_api.md)
- 前端架构文档：[docs/FRONTEND_ARCHITECTURE.md](docs/FRONTEND_ARCHITECTURE.md)
- 开发规范：[docs/dev_rules.md](docs/dev_rules.md)
