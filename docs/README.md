# AIFriend 文档导航

## 快速开始

- **[部署指南](DEPLOYMENT_GUIDE.md)** - 完整部署流程（本地 + 生产）
- **[开发规范](DEV_RULES.md)** - 必读的开发规则
- **[API 文档](API.md)** - 后端接口完整列表

## 业务功能

- **[好感度系统](AFFECTION_SYSTEM.md)** - 好感度/剧情沉浸度机制
- **[角色导入](CHARACTER_IMPORT_SOP.md)** - 角色卡导入与配置流程
- **[管理后台](ADMIN_PANEL_GUIDE.md)** - 后台管理界面使用说明

## 技术架构

- **[前端架构](FRONTEND_ARCHITECTURE.md)** - 前端模块结构
- **[测试指南](../tests/README_TEST_GUIDE.md)** - 测试系统说明

## 数据库

- **Schema 管理**: 使用 Alembic 迁移框架（`backend/alembic/`）
- **初始化**: `cd backend && python3 -m alembic upgrade head`
- **历史参考**: `supabase_schema.sql`（已由 Alembic 替代，仅归档）

---

**注意**: 文档与代码不一致时，以代码为准。
