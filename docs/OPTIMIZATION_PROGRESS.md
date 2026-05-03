# 优化进度

## 已完成

### 架构重构（8 项，2026-04 ~ 2026-05）

| # | 重构项 | 效果 |
|---|--------|------|
| 1 | `get_db_dep` 归还前 rollback 兜底 | 未提交事务自动回滚，杜绝脏连接 |
| 2 | `chat_retry.message_projection` 公共化 | 消除跨模块私有 API 调用 |
| 3 | `core/auth.py` 缓存回调注入 | 解除 core → services 反向依赖 |
| 4 | `memory_service` 拆分 | 1038 行 → `stream_filter.py` + `character_memory_repository.py` |
| 5 | `character_state` 拆分 | 剧情事件独立为 `story_event_service.py` |
| 6 | `repositories/` 数据访问层 | 5 个 repository，SQL 全部集中管理 |
| 7 | DB Schema 修复（Alembic 002） | 33 列 timestamptz + 11 列 jsonb |
| 8 | Chat Stream 简化 | 6 文件 1744 行 → 3 文件 1127 行（-35%） |

### 安全加固（2026-05）

| # | 项目 | 说明 |
|---|------|------|
| 1 | Admin 鉴权补全 | 所有 admin 子路由统一 `get_admin_user` 依赖 |
| 2 | `admin_update_user_plan` 鉴权修复 | `get_current_user` → `get_admin_user` |
| 3 | Cookie SameSite 升级 | 生产环境 `Strict`，开发环境 `Lax` |
| 4 | 安全响应头 | HSTS / X-Frame-Options / X-Content-Type-Options / Referrer-Policy |
| 5 | 前端 Token 泄露修复 | 移除 admin api.js console.log |
| 6 | 邮件配置校验 | SMTP 或 Resend 任一即可（原仅检查 Resend） |

### 缓存与部署加固（2026-05）

| # | 项目 | 说明 |
|---|------|------|
| 1 | 用户缓存失效补全 | billing.py 4 个端点添加 `invalidate_user()` |
| 2 | assert 违规修复 | `auth.py` assert → if + raise HTTPException |
| 3 | 迁移 003 | `password_reset_codes.attempt_count` 列，幂等 |
| 4 | 回滚脚本 | `rollback.sh` 支持 `--to` 指定备份 |
| 5 | 健康检查门禁 | deploy.sh 部署后自动检查，失败提示回滚 |
| 6 | 日志轮转 | `/etc/logrotate.d/aifriend`（daily, rotate 14, max 50M） |
| 7 | restart.sh .env 解析 | 逐行读取替代 `source`，避免特殊字符报错 |

## 当前架构

```
backend/
├── main.py                  # 应用入口（lifespan + 安全头中间件）
├── core/                    # 基础设施（auth/config/database/schemas/model_adapter）
├── constants/               # 枚举常量（Mood / StoryPhase）
├── repositories/            # 数据访问层（SQL 集中管理）
├── services/                # 业务逻辑层
├── routers/                 # API 路由层
│   ├── chat/                # 包式路由
│   └── admin/               # 子路由聚合（6 个业务域模块）
└── utils/                   # 通用工具
```

## 待做

- `SimpleCache` → Redis（多实例部署时）
- `prompt_assembler.py` 拆分（大文件）
- 前端 ES Module 升级
- 测试覆盖率 51% → 70%+
