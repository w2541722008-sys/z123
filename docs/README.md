# 文档导航（SSOT）

本目录文档按"单一事实来源"维护：每个领域仅保留一个主文档，其他文档只做引用或归档。

## 运行与部署

- 部署主文档：`DEPLOYMENT_GUIDE_VPS.md`
- 上线检查清单：`DEPLOYMENT_CHECKLIST.md`
- 快速入口：`QUICK_DEPLOY.md`
- 数据库备份：`DATABASE_BACKUP_GUIDE.md`

## 开发与架构

- 后端 API：`backend_api.md`
- 前端架构：`FRONTEND_ARCHITECTURE.md`
- 后台使用：`ADMIN_PANEL_GUIDE.md`
- 开发规范：`dev_rules.md`

## 业务专题

- 角色创建：`CHARACTER_IMPORT_SOP.md`
- 好感度系统：`AFFECTION_SYSTEM.md`

## 数据库

- Schema 管理：Alembic 迁移框架（`backend/alembic/`）
- 基线迁移：`backend/alembic/versions/001_initial_schema.py`（含全部建表）
- 类型修复迁移：`backend/alembic/versions/002_text_to_timestamptz_jsonb.py`（text→timestamptz/jsonb）
- 历史参考：`supabase_schema.sql`、`migrations/`（已由 Alembic 替代，仅作归档）

## 归档与草稿

- 重构进度：`docs/OPTIMIZATION_PROGRESS.md`
- 研究草稿：`.trae/documents/`（不作为正式运行文档）

说明：

- 新环境初始化数据库使用 `alembic upgrade head`，不再需要手动执行 SQL 文件。
- 文档与代码不一致时，以当前代码与脚本行为为准，再同步回文档。
