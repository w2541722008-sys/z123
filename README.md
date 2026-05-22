# AIFriend（Lunar）

面向女性用户的 AI 角色扮演聊天 Web 应用。前端为原生 JavaScript（IIFE 模块），后端为 FastAPI + PostgreSQL（Supabase）。

## 项目现状

- 用户端：`index.html` + `frontend/modules/`（18 个 JS 模块）
- 管理后台：`frontend/admin/index.html` + `frontend/admin/js/`（18 个 JS 模块）
- 后端 API：`/api/*`（FastAPI，路由 → 服务 → 仓库 三层架构）
- 健康检查：`/api/health`

## 技术栈

- 后端：Python 3.10+、FastAPI、Uvicorn、httpx、psycopg2（ThreadedConnectionPool）
- 数据库：PostgreSQL（Supabase）+ Alembic 迁移（14 个版本）
- 前端：原生 HTML/CSS/JavaScript（IIFE 模块模式）
- 测试：pytest（1149+ tests）+ Node.js 脚本

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

当前迁移版本（14 个）：001~014。

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

- **总导航**：[docs/README.md](docs/README.md)
- **部署指南**：[docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md)
- **API 文档**：[docs/API.md](docs/API.md)
- **好感度系统**：[docs/AFFECTION_SYSTEM.md](docs/AFFECTION_SYSTEM.md)
- **角色导入**：[docs/CHARACTER_IMPORT_SOP.md](docs/CHARACTER_IMPORT_SOP.md)
- **管理后台**：[docs/ADMIN_PANEL_GUIDE.md](docs/ADMIN_PANEL_GUIDE.md)
- **前端架构**：[docs/FRONTEND_ARCHITECTURE.md](docs/FRONTEND_ARCHITECTURE.md)
- **部署脚本**：`deploy.sh` / `restart.sh` / `rollback.sh` / `setup_server.sh` / `verify_server.sh`
