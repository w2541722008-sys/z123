# AIFriend 代码优化清单

> ⚠️ **本文档为历史存档**（2026-03-31 评估记录）
> SQLite → Supabase 迁移后，部分条目已过时。当前代码状态请以实际代码为准。
> 数据库相关优化项（如 backup_db.py）已不适用，项目已使用 `backup_supabase.sh`。

**文档版本**: v1.0  
**创建日期**: 2026-03-31  
**最后更新**: 2026-04-03（新增 P3-3~P3-7：聊天UI/智能滚动/头像预加载/Nginx缓存/语法修复）  
**项目路径**: `/Users/jjj/aifriend`

---

## 📋 文档说明

本文档是对 AIFriend 项目的全面代码质量评估结果，列出了所有需要优化的点。

**使用方式**：
- 每个优化项都标注了优先级（P0/P1/P2/P3）和风险等级（低/中/高）
- AI 助手可以直接根据这份清单执行优化任务
- 完成后在对应项目前打勾 ✅
- 遵循 `docs/dev_rules.md` 中的开发规则

**优先级定义**：
- **P0**: 严重问题，必须立即处理
- **P1**: 重要问题，应尽快处理
- **P2**: 中等问题，可以计划处理
- **P3**: 低优先级，有时间再处理

**风险等级定义**：
- **低风险**: 改动小，不影响业务逻辑
- **中风险**: 需要测试验证，可能影响部分功能
- **高风险**: 涉及核心逻辑，需要充分测试和回退准备

---

## ✅ 已完成的优化（2026-03-31 ~ 2026-04-03）

### 1. 安全性修复
- ✅ 移除了 `.env` 文件的 Git 跟踪
- ✅ 创建了 `.env.example` 和 `.env.production.example` 模板
- ✅ 更新了 `.gitignore`，增强了敏感信息保护
- ✅ 创建了部署检查清单 `docs/DEPLOYMENT_CHECKLIST.md`

### 2. 文件组织
- ✅ 删除了废弃的备份文件（`backend/auth.py.bak`）
- ✅ 删除了废弃文件：`frontend/app.js`（88KB 死代码）、`backend/migrate_db.py`、`backend/migrate_db_v2.py`、`backend/check_order.py`
- ✅ 删除了临时目录：`.playwright-cli/`
- ✅ 移动了 CLI 工具到 `backend/cli/` 目录（`card_import.py`、`card_analyze.py`）
- ✅ 创建了数据库备份脚本 `backend/backup_supabase.sh`（替代旧版 backup_db.py）
- ✅ 创建了数据库监控服务 `backend/services/db_monitor.py`
- ✅ 创建了缓存服务 `backend/services/cache_service.py`
- ✅ 创建了用户头像存储目录 `avatars/.gitkeep`

### 3. 代码质量提升（第一批）
- ✅ `backend/model_adapter.py`: 提取了硬编码常量，补充了类型注解
- ✅ `backend/services/usage_guard.py`: 提取了错误消息截断常量

### 4. 代码去重与重构
- ✅ `backend/routers/chat.py`: 提取 `_stream_ai_completion()` 公共函数，消除 4 处 SSE 流式处理重复逻辑
- ✅ 修复 StopIteration bug：生成器 return 值在 4 个调用方正确捕获

### 5. 新功能实现
- ✅ 新增 **Regenerate + Continue** 聊天增强功能（SSE 流式交互）
- ✅ 新增 **用户头像系统**（上传/更换/展示，含安全防护 + 旧文件自动清理）
- ✅ 新增聊天消息**角色/用户头像显示**（36px 正方形，微信风格对齐）
- ✅ 新增**智能时间戳**（>5 分钟间隔显示，微信风格居中分割线）
- ✅ auth.js bootstrap 改为**仅认证失败时清登录态**
- ✅ **P1-B**: SSE 流式响应超时控制（120 秒，防 AI 提供商挂起）
- ✅ **P1-C**: Token 滑动续期机制（剩余 <7 天自动延长至 30 天，活跃用户不因过期被踢出）

### 6. 代码重构
- ✅ **P1-D**: admin.py 拆分为 `routers/admin/` 包（2936 行 → 4 子模块 + 共享模块）
  - characters.py: ~2000 行, 34 路由（角色 CRUD + 记忆/开场白/剧情线/规则/事件/分类）
  - users.py: ~431 行, 7 路由（用户管理 + 会员）
  - orders.py: ~207 行, 3 路由（订单管理）
  - dashboard.py: ~281 行, 5 路由（统计/仪表盘/审计日志）
  - _shared.py: 常量 + 事务工具 + 审计日志

### 7. Bug 修复
- ✅ 修复 `_sliding_extend_token` 中 `extend_conn` 未初始化的 NameError 风险

### 8. P2 前端优化（2026-04-03）
- ✅ **P2-1**: SSE 连接切换时 abort 旧连接（4处流式API全覆盖）
- ✅ **P2-2**: fetch 请求添加 AbortController 超时（20s 默认超时）
- ✅ **P2-3**: 大量消息渲染性能优化（DocumentFragment 批量渲染）

### 9. 文档更新
- ✅ 更新 README.md（目录结构、API 路由、依赖列表、已完成功能）
- ✅ 更新 docs/FRONTEND_ARCHITECTURE.md（模块接口、头像系统、智能时间戳）
- ✅ 更新 docs/backend_api.md（补充头像 API）
- ✅ 同步更新本文档（CODE_OPTIMIZATION_CHECKLIST.md）状态标记

### 10. 单元测试套件建立（2026-04-03）
- ✅ **测试基础设施**: `tests/conftest.py` — FakeConn / Mock 数据工厂 / 测试辅助函数
- ✅ **test_auth.py** (20 用例): Token 哈希 / bcrypt 密码 / 滑动续期(含 NameError 回归) / 管理员判断
- ✅ **test_memory_service.py** (33 用例): SSE 流式 </think> 标签过滤（状态机）/ STATE_UPDATE 标签解析
- ✅ **test_prompt_assembler.py** (50 用例): TokenBudget 预算分配 / JSON 解析 / 文本工具 / World Info 触发
- ✅ **test_model_adapter.py** (22 用例): 三套模型策略读取 / payload 构建 / 可选参数解析
- ✅ **test_json_utils.py** (19 用例): 安全 JSON 数组/对象解析 / 序列化 / 边界情况
- ✅ **test_card_text_utils.py** (48 用例): 文本清洗 / XML 剥离 / HTML 清除 / 模板变量 / 截断
- ✅ **test_character_state.py** (22 用例): 好感度三防机制 / 阶段推进 / 状态增量白名单
- ✅ **test_frontend_utils.js** (31 用例): SSE 事件解析 / XSS 防护 / 日期格式化
- **总计: 265 个用例，100% 通过率，覆盖 9 个核心模块**

### 11. 生产部署 Bug 修复（2026-04-03）
- ✅ **P3-1**: `auth.py` CurrentUser 类缺少 `avatar_url` 字段 → `/api/auth/me` 返回 500 → 管理后台无法访问
  - 根因：[auth.py:291](../backend/auth.py#L291) 引用 `user.avatar_url` 但 CurrentUser dataclass 未定义该字段
  - 修复：添加 `avatar_url: str = ""` 字段 + SQL 查询补充 `COALESCE(users.avatar_url, '')`
- ✅ **P3-2**: `main.py` 头像/封面接口 `get_db()` 用法错误 → 所有头像/封面请求返回 500
  - 根因：[main.py:316,335](../backend/main.py#L316) 将生成器函数 `get_db()` 直接赋值给变量，未使用 `with` 语句
  - 错误：`AttributeError: '_GeneratorContextManager' object has no attribute 'execute'`
  - 修复：改为 `with get_db() as conn:` 正确用法
- ✅ **生产部署**: HTTPS 配置完成（Let's Encrypt + OpenResty）、systemd 开机自启、WAF 问题排查与绕过
- ✅ **P3-3**: 聊天 UI 按钮位置重构 — 新增 `.msg-body` 垂直容器统一 AI 消息 DOM 结构，Regenerate/Continue 按钮固定在气泡左下角（[chat.js](../frontend/modules/chat.js)）
- ✅ **P3-4**: 智能滚动 — 流式输出时用户上滑查看历史自动暂停跟滚，回底 120px 内恢复（`_autoScroll` 状态 + scroll 事件监听）
- ✅ **P3-5**: 角色头像预加载 — 首页角色列表渲染后通过 `new Image()` 预加载所有头像/封面到浏览器缓存（[app.js](../frontend/modules/app.js) `preloadCharacterImages()`）
- ✅ **P3-6**: Nginx 图片长期缓存 — 静态图片资源设置 30d 缓存 + `Cache-Control: public, immutable`（[aifriend.conf](../aifriend.conf)）
- ✅ **P3-7**: chat.js 语法修复 — `appendMsg()` else 块缺少闭合大括号导致整个 IIFE 模块崩溃，页面无法进入聊天界面

---

## 🔴 P0 优先级（严重问题）

### 安全性
- [ ] **检查生产环境配置** (风险: 高)
  - 文件: `backend/config.py`, `.env.production.example`
  - 任务: 确认生产环境的 `DEBUG` 模式已关闭
  - 任务: 确认 `CORS_ORIGINS` 配置正确，不允许 `*`
  - 任务: 确认所有敏感信息都通过环境变量配置

- [ ] **数据库备份策略** (风险: 高)
  - 文件: `backend/backup_supabase.sh`
  - 任务: 确认备份脚本可以正常运行
  - 任务: 设置定时备份任务（cron job / 1Panel 计划任务）
  - 任务: 测试备份恢复流程
  - 参考: `docs/DATABASE_BACKUP_GUIDE.md`

---

## 🟠 P1 优先级（重要问题）

### 代码质量

- [x] ~~**提取 `backend/routers/chat.py` 中的重复代码**~~ (风险: 中) ✅ 已完成
  - `chat_stream` 和 `chat_guest_stream` 的公共流式逻辑已提取为 `_stream_ai_completion()`
- [x] ~~**拆分 `backend/routers/admin.py`**~~ (风险: 高) ✅ 已完成
  - 拆分为 `routers/admin/` 包：characters(34路由) + users(7路由) + orders(3路由) + dashboard(5路由)
  - 共享模块 `_shared.py` 提取常量和工具函数

### 文档更新

- [x] ~~**更新 `docs/backend_api.md`**~~ (风险: 低) ✅ 已完成（补充头像 API）
- [x] ~~**创建架构文档**~~ (风险: 低) ✅ 已完成（FRONTEND_ARCHITECTURE.md + README 架构章节）

### 性能优化

- [x] ~~**SSE 连接超时控制**~~ (风险: 中) ✅ 已完成
  - `chat.py`: `_stream_ai_completion()` 添加 `time.monotonic()` 超时检查（`SSE_STREAM_TIMEOUT=120s`）

### 安全加固

- [x] ~~**Token 过期机制**~~ (风险: 中) ✅ 已完成
  - `auth.py`: 新增 `_sliding_extend_token()` 滑动续期函数
  - 剩余有效期 < 7 天时自动延长至 30 天，活跃用户不因过期被踢出

- [x] ~~**头像旧文件清理**~~ (风险: 低) ✅ 已完成
  - `main.py`: 上传新头像前查询并删除旧文件，防止 avatars/ 目录无限增长

---

## 🟡 P2 优先级（改进建议）

### 代码质量

- [x] ~~**清理未使用的导入和变量**~~ ✅ 已完成
- [x] ~~**统一异常处理模式**~~ (部分完成)
  - `get_db()` 上下文管理器用法已统一
  - StopIteration 捕获模式已统一

### 前端优化

- [x] ~~**SSE 连接切换时 abort 旧连接**~~ ✅ 已完成 (2026-04-03)
  - 文件: `frontend/modules/chat.js`
  - 实现: `_streamController` + `abortStream()` + 4处流式API调用全部传递 signal
  - 覆盖: send(游客/登录)、regenerateMessage、continueMessage

- [x] ~~**fetch 请求添加 AbortController 超时**~~ ✅ 已完成 (2026-04-03)
  - 文件: `frontend/modules/api.js`
  - 实现: `request()` 添加 AbortController + setTimeout(20s) + AbortError 友好提示
  - 默认超时: 20秒，可通过 options.timeout 覆盖

- [x] ~~**大量消息渲染性能优化**~~ ✅ 已完成 (2026-04-03)
  - 文件: `frontend/modules/chat.js`
  - 实现: `renderHistory()` 使用 DocumentFragment 批量渲染
  - 效果: N条消息只触发1次 reflow，跳过N-1次 scrollToBottom

### 安全加固

- [ ] **日志中间件敏感信息过滤** (风险: 低)
  - 文件: `backend/main.py`
  - 问题: `log_requests` 记录完整请求路径，可能泄露 token 等参数
  - 建议: 过滤 URL 中敏感字段

- [ ] **订单创建幂等性** (风险: 中)
  - 文件: `backend/routers/billing.py`
  - 问题: 快速双击可能创建重复订单
  - 建议: 增加去重检查

---

## 🟢 P3 优先级（低优先级）

### 代码风格

- [ ] **统一代码格式** (风险: 低)
  - 工具: black, isort
  - 任务: 配置 pre-commit hook
  - 文件: `.pre-commit-config.yaml`（新建）

- [ ] **添加代码质量检查** (风险: 低)
  - 工具: pylint, flake8, mypy
  - 任务: 配置 CI/CD 流程
  - 文件: `.github/workflows/ci.yml`（新建）

### 文档补充

- [ ] **创建开发指南** (风险: 低)
  - 文件: `docs/DEVELOPMENT_GUIDE.md`（新建）
  - 内容:
    - 本地开发环境搭建
    - 常用开发命令
    - 调试技巧
    - 常见问题解答

- [ ] **创建 API 使用示例** (风险: 低)
  - 目录: `docs/examples/`（新建）
  - 内容: 各个 API 的实际使用示例代码

### 性能优化

- [ ] **添加性能监控** (风险: 低)
  - 工具: 考虑使用 APM 工具（如 New Relic, DataDog）
  - 任务: 添加关键路径的性能埋点
  - 文件: `backend/middleware/performance.py`（新建）

- [ ] **优化静态资源加载** (风险: 低)
  - 目录: `frontend/`
  - 任务: 压缩 CSS/JS 文件
  - 任务: 添加资源缓存策略

---

## 📊 代码质量指标

### 当前状态评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 安全性 | 7/10 | 已修复主要安全问题，但需要持续关注 |
| 可维护性 | 6/10 | 部分文件过长，需要重构 |
| 可测试性 | 8/10 | 已建立 265 个单元测试（8 Python + 1 JS），覆盖 9 个核心模块；生产 bug 修复后补充验证 |
| 文档完整性 | 7/10 | 有基础文档，持续同步更新中 |
| 代码规范 | 7/10 | 整体规范，但缺少自动化检查 |
| 性能 | 7/10 | 基本满足需求，有优化空间 |

### 改进目标

| 维度 | 当前评分 | 目标评分 | 关键任务 |
|------|----------|----------|----------|
| 安全性 | 7/10 | 9/10 | 完成 P0 安全性检查 |
| 可维护性 | 6/10 | 8/10 | 完成 P1 代码重构 |
| **可测试性** | **7/10** | **8/10** | ~~完成 P2 测试覆盖~~ ✅ 已完成 |
| 文档完整性 | 7/10 | 8/10 | 完成 P1 文档更新 |
| 代码规范 | 7/10 | 8/10 | 完成 P3 代码风格统一 |
| 性能 | 7/10 | 8/10 | 完成 P1 性能优化 |

---

## 🎯 执行建议

### 第一阶段（1-2天）
1. 完成所有 P0 任务
2. 开始 P1 文档更新任务

### 第二阶段（3-5天）
1. 完成 P1 代码质量任务
2. 完成 P1 性能优化任务

### 第三阶段（1-2周）
1. 完成 P2 任务
2. 根据实际情况选择性完成 P3 任务

### 注意事项
- 所有高风险改动必须先创建分支
- 改动前确保有回退点（Git tag）
- 改动后必须进行充分测试
- 遵循 `docs/dev_rules.md` 中的规则

---

## 📝 更新日志

### 2026-03-31
- 创建初始版本
- 完成代码库全面评估
- 列出所有优化项并分类

---

## 🔗 相关文档

- [开发规则](./dev_rules.md)
- [部署检查清单](./DEPLOYMENT_CHECKLIST.md)
- [后端 API 文档](./backend_api.md)
- [角色导入 SOP](./CHARACTER_IMPORT_SOP.md)
