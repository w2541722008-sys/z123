# 优化进度

## 已完成（架构重构 8 项 + 基础优化 9 项）

### 架构重构（2026-04 ~ 2026-05）

| # | 重构项 | 效果 |
|---|--------|------|
| 1 | `get_db_dep` 归还前 rollback 兜底 | 未提交事务自动回滚，杜绝连接池脏连接 |
| 2 | `chat_retry._message_projection` 提升为公共 API | 消除跨模块私有 API 调用，`message_projection` 统一入口 |
| 3 | `core/auth.py` 缓存回调注入 | `register_cache_callbacks()` 由 `main.py` 启动时注入，解除 core → services 反向依赖 |
| 4 | `memory_service` 拆分 | 原 1038 行 → `stream_filter.py` + `character_memory_repository.py`，原文件保留 re-export 兼容层 |
| 5 | `character_state` 拆分 | 剧情事件逻辑独立为 `story_event_service.py`，原文件改为调用新模块 |
| 6 | 建立 `repositories/` 层 | 5 个 repository（character/user/auth/billing/chat），前台路由和 admin 路由的 SQL 全部迁移至此层 |
| 7 | DB Schema 修复（Alembic 迁移 002） | 33 个 text 列 → timestamptz，11 个 text 列 → jsonb；created_at/updated_at 改用 DB DEFAULT now()；jsonb 列移除 json.loads() |
| 8 | Chat Stream 简化 | 6 文件 1744 行 → 3 文件 1127 行（-35%），删除 5 个 Deps dataclass，合并 `_stream_infra.py` / `_prepare.py` / `_chat_send.py` |

### 基础优化（2026-03 ~ 2026-04）

| # | 优化项 | 效果 |
|---|--------|------|
| 1 | 后台前端模块化拆分 | actions/bootstrap/overview/char-list/char-crud/normalizers 等 |
| 2 | 管理后台事件统一 | `data-action` + 委托分发 |
| 3 | auth/billing/admin 权限与错误契约测试补强 | 测试覆盖关键业务路径 |
| 4 | CI 接入前端测试与 admin action 严格校验 | 质量门禁自动化 |
| 5 | 连接池线程安全 | `SimpleConnectionPool` → `ThreadedConnectionPool` |
| 6 | httpx 迁移 | `model_adapter.py` 从 urllib 迁移至 `httpx.Client`，含重试与超时控制 |
| 7 | 路径遍历防护 | `routers/media.py` 添加白名单目录校验 |
| 8 | 错误信息安全 | `model_adapter.py` RuntimeError 不再暴露原始 API 响应 |
| 9 | 枚举统一 | `constants/` 模块（Mood 9 种 + StoryPhase 4 种） |

## 当前架构分层

```
backend/
├── main.py                  # 应用入口（lifespan 模式）
├── core/                    # 基础设施层（auth/config/database/schemas/model_adapter）
│   └── prompt_assembler.py  # 兼容 re-export，实际在 services/
├── constants/               # 枚举常量（Mood / StoryPhase）
├── repositories/            # 数据访问层（SQL 集中管理）
├── services/                # 业务逻辑层
├── routers/                 # API 路由层
│   ├── chat/                # 包式路由（__init__.py + _route_builders.py）
│   └── admin/               # 子路由聚合（5 个业务域模块）
└── utils/                   # 通用工具

依赖方向：routers/ → services/ → core/
              ↓         ↓
         repositories/（SQL 数据访问）
```

## 待做

- 前端模块系统升级
- 用户缓存失效补全（改密码/支付后）
- `SimpleCache` → Redis（多实例部署时）

## 持续原则

- 小步改造、行为不变、每步可回归
- 以可维护性和可回滚性优先
