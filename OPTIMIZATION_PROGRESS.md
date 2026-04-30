# 优化进度（当前）

## 已完成

- 后台前端模块化拆分（actions/bootstrap/overview/char-list/char-crud/normalizers 等）
- 管理后台事件统一为 `data-action` + 委托分发
- auth/billing/admin 权限与错误契约测试补强
- CI 接入前端测试与 admin action 严格校验
- **连接池线程安全**：`SimpleConnectionPool` → `ThreadedConnectionPool`
- **httpx 迁移**：`model_adapter.py` 从 urllib 迁移至 `httpx.Client`（同步客户端），含重试与超时控制
- **路径遍历防护**：`routers/media.py` 添加白名单目录校验（`_is_under_safe_dir`）
- **错误信息安全**：`model_adapter.py` RuntimeError 不再暴露原始 API 响应，仅记日志
- **枚举统一**：创建 `constants/` 模块（`Mood` 9种 + `StoryPhase` 4种），`prompt_assembler`、`character_state`、`character_config` 统一从 `constants` 导入
- **缓存上限保护**：`cache_service.py` 添加 `max_size=500` + 过期淘汰 + `__len__`
- **main.py 瘦身**：健康检查逻辑移至 `services/health_service.py`，头像/封面/用户头像端点移至 `routers/media.py`（main.py 从 540行→271行）
- **SQL 集中化（部分）**：`prompt_assembler.py` 中的 `get_character_memories_from_db` 和 `get_character_post_rules_from_db` 已移至 `services/memory_service.py`（重命名为 `fetch_character_memories` / `fetch_character_post_rules`）
- **依赖清理**：移除 `requests` 死依赖，分离 `requirements-dev.txt`，移除 `admin.py.bak`，删除重复 `_get_now_iso()` 函数
- **AI 配置集中**：`DEFAULT_AI_BASE_URL` / `DEFAULT_AI_MODEL` 移至 `config.py`

## 当前重点

- 文档体系统一：以 `README.md` + `docs/README.md` 作为导航入口
- 部署/测试/架构文档与脚本行为持续对齐

## 持续原则

- 小步改造、行为不变、每步可回归
- 以可维护性和可回滚性优先
