# ADR-0002：分层依赖解耦 — 回调注入模式

**日期**：2025-05-01（推定，基于代码历史）
**状态**：已接受

## 背景

项目的分层架构定义了严格的单向依赖：`routers/ → services/ → repositories/ → core/ + constants/`。但 core/ 层（特别是 `auth.py`）有时需要访问 services/ 层的功能（如缓存服务），直接 import 会破坏分层纪律，可能造成循环依赖。

## 决策

使用**回调注入**模式解耦：core/ 层定义回调接口，由 `main.py` 在应用启动（lifespan）时将 services/ 层的具体实现注册进去。

```python
# core/auth.py — 定义回调接口
_cache_get_callback = None
_cache_set_callback = None

def register_cache_callbacks(on_get, on_set):
    global _cache_get_callback, _cache_set_callback
    _cache_get_callback = on_get
    _cache_set_callback = on_set

# main.py — lifespan 中注册
from core.auth import register_cache_callbacks
from services.cache_service import get_cached_user, set_cached_user

register_cache_callbacks(on_get=get_cached_user, on_set=set_cached_user)
```

## 备选方案

- **方案 A：允许 core/ 有限导入 services/** — 只允许"基础设施类"的 service
  - 未选原因："基础设施"和"业务"的边界会逐渐模糊，最终回到循环依赖。硬性禁止比软性约定更可靠

- **方案 B：将缓存功能下沉到 core/** — 把 cache_service 移到 core/ 内部
  - 未选原因：缓存涉及 Redis 连接、过期策略等，不是纯基础设施，放在 core/ 会让 core 变得过重

- **方案 C：事件总线** — core/ 发出事件，services/ 订阅
  - 未选原因：对于当前规模（auth 仅需缓存），事件总线过于重量级。如果未来 core/ 需要 10+ 种 services 功能，此方案值得重新评估

## 后果

### 正面
- 分层依赖方向严格单向，不存在循环依赖风险
- 注册点集中在 `main.py` 的 lifespan，便于全局概览
- core/ 层保持轻量，只定义接口不引入实现

### 负面
- 回调模式的理解成本高于直接 import
- 新增 core/ → services/ 的依赖时需要手动注册，可能被遗忘
- 全局变量（`_cache_get_callback`）在测试中需要手动重置

## 相关
- CLAUDE.md "分层依赖"规则
- `.out-of-scope/no-core-imports-services.md`
- `backend/main.py` — lifespan 注册点
- `backend/core/auth.py` — 回调定义
