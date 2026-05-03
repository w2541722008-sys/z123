# 文档导航

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
- `001_initial_schema.py`：基线迁移（全部建表）
- `002_text_to_timestamptz_jsonb.py`：类型修复（text→timestamptz/jsonb）
- `003_add_reset_code_attempt_count.py`：密码重试计数列
- 历史参考：`supabase_schema.sql`、`migrations/`（已由 Alembic 替代，仅归档）

## 归档

- 重构进度：`OPTIMIZATION_PROGRESS.md`
- 重构审计：`refactoring_audit_report.md`
- 测试诊断：`test_diagnostic_report.md`

> 新环境初始化使用 `alembic upgrade head`，不再需要手动执行 SQL。
> 文档与代码不一致时，以代码和脚本行为为准。
