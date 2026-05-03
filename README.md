# AIFriend（Lunar）

面向女性用户的 AI 角色扮演聊天 Web 应用。前端为原生 JavaScript（IIFE 模块），后端为 FastAPI + PostgreSQL（Supabase）。

## 项目现状

- 前端用户站：`/`（`index.html` + `frontend/modules/`）
- 管理后台：`/admin.html`（服务端入口）与 `/frontend/admin/index.html`（静态入口）
- 后端 API：`/api/*`
- 健康检查：`/api/health`

## 技术栈

- 后端：Python 3.10+、FastAPI、Uvicorn、httpx、psycopg2（ThreadedConnectionPool）
- 数据库：PostgreSQL（Supabase）
- 前端：原生 HTML/CSS/JavaScript（IIFE）
- 测试：pytest + Node.js 脚本

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

### 3) 初始化数据库

- 使用 Alembic 自动迁移：`cd backend && python3 -m alembic upgrade head`
- 基线迁移包含全部建表，无需手动执行 SQL

### 4) 启动后端

```bash
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## 测试与质量门禁

```bash
cd backend
python3 -m pytest ../tests/ -q

cd ..
node tests/test_frontend_utils.js
node tests/check_admin_actions.js --strict --allow-list=tests/admin_action_allowlist.json
```

CI 与本地保持同一门禁策略：后端测试、前端测试、admin action 严格校验。

## 一键部署（项目标准）

```bash
cd /Users/jjj/aifriend
bash deploy.sh
```

`deploy.sh` 会执行：

- SSH 连通性检查
- 本地测试门禁
- 服务器备份（`/opt/backup_*`）
- rsync 同步到 `/opt/aifriend`
- 远端重启与健康检查

## 文档导航

- 总导航：[docs/README.md](docs/README.md)
- 部署主文档：[docs/DEPLOYMENT_GUIDE_VPS.md](docs/DEPLOYMENT_GUIDE_VPS.md)
- 上线检查清单：[docs/DEPLOYMENT_CHECKLIST.md](docs/DEPLOYMENT_CHECKLIST.md)
- 后端接口文档：[docs/backend_api.md](docs/backend_api.md)
- 前端架构文档：[docs/FRONTEND_ARCHITECTURE.md](docs/FRONTEND_ARCHITECTURE.md)
- 后台使用文档：[docs/ADMIN_PANEL_GUIDE.md](docs/ADMIN_PANEL_GUIDE.md)
- 数据库备份文档：[docs/DATABASE_BACKUP_GUIDE.md](docs/DATABASE_BACKUP_GUIDE.md)
