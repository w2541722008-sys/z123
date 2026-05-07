# migrations/

此目录存放历史手动 SQL 迁移记录，仅供参考。

| 文件 | 执行时间 | 说明 |
|------|---------|------|
| 001_add_message_versions.sql | 2026-04-02 | Regenerate/Continue 版本管理 |
| 002_add_performance_indexes.sql | 2026-04-21 | 查询性能索引 |
| 003_add_reset_code_attempt_count.sql | 2026-05-01 | 验证码安全增强 |
| 004_add_trigger_custom_key.sql | 2026-05 | 剧情事件自定义键触发 |

**Alembic 是本项目的权威迁移工具**，位于 `backend/alembic/`。所有新迁移必须通过 `alembic revision` 生成，不要手动执行此目录下的 SQL 文件。
