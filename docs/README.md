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

- 角色导入：`CHARACTER_IMPORT_SOP.md`
- 好感度系统：`AFFECTION_SYSTEM.md`
- Regenerate/Continue 测试：`REGENERATE_CONTINUE_TEST_CHECKLIST.md`

## 数据库

- 全量建表：`supabase_schema.sql`
- 迁移脚本：`migrations/`

## 归档与草稿

- 历史过程记录：`/OPTIMIZATION_PROGRESS.md`
- 研究草稿：`.trae/documents/`（不作为正式运行文档）

说明：

- 生产环境若发现 `chat_messages.versions` 缺失，请执行 `migrations/001_add_message_versions.sql`。
- 文档与代码不一致时，以当前代码与脚本行为为准，再同步回文档。
