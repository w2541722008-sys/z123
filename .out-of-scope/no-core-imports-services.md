---
scope: agent-behavior
severity: high
---

# 禁止 core/ 导入 services/

## 规则

Agent **绝对禁止**在 `backend/core/` 的任何模块中 `import` 或 `from ... import` `backend/services/` 的任何模块。

## 原因

- 这是项目的**分层依赖铁律**：`routers/ → services/ → repositories/ → core/ + constants/`
- 依赖方向必须单向：上层可以依赖下层，下层不能依赖上层
- 如果 core/ 导入 services/，会造成循环依赖，破坏模块边界

## 正确做法

如果 core/ 层需要调用 services/ 的功能，使用**回调注入**：

```python
# main.py 的 lifespan 中注册回调
from core.auth import register_cache_callbacks
from services.cache_service import get_cached_user, set_cached_user

register_cache_callbacks(
    on_get=get_cached_user,
    on_set=set_cached_user
)
```

```python
# core/auth/__init__.py 中通过回调调用
_cache_get_callback = None

def register_cache_callbacks(on_get, on_set):
    global _cache_get_callback
    _cache_get_callback = on_get

# 使用时调用回调，而非直接 import services
if _cache_get_callback:
    user = _cache_get_callback(user_id)
```

## 检测方法

```bash
# 检查是否有违规导入
grep -r "from backend.services\|from services\|import backend.services" backend/core/
```
