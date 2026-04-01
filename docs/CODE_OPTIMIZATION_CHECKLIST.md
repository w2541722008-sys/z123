# AIFriend 代码优化清单

> ⚠️ **本文档为历史存档**（2026-03-31 评估记录）
> SQLite → Supabase 迁移后，部分条目已过时。当前代码状态请以实际代码为准。
> 数据库相关优化项（如 backup_db.py）已不适用，项目已使用 `backup_supabase.sh`。

**文档版本**: v1.0  
**创建日期**: 2026-03-31  
**最后更新**: 2026-04-01（标记为历史存档）  
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

## ✅ 已完成的优化（2026-03-31）

### 1. 安全性修复
- ✅ 移除了 `.env` 文件的 Git 跟踪
- ✅ 创建了 `.env.example` 和 `.env.production.example` 模板
- ✅ 更新了 `.gitignore`，增强了敏感信息保护
- ✅ 创建了部署检查清单 `docs/DEPLOYMENT_CHECKLIST.md`

### 2. 文件组织
- ✅ 删除了废弃的备份文件（`backend/auth.py.bak`）
- ✅ 创建了数据库备份脚本 `backend/backup_supabase.sh`（替代旧版 backup_db.py）
- ✅ 创建了数据库监控服务 `backend/services/db_monitor.py`
- ✅ 创建了缓存服务 `backend/services/cache_service.py`

### 3. 代码质量提升（第一批）
- ✅ `backend/model_adapter.py`: 提取了硬编码常量，补充了类型注解
- ✅ `backend/services/usage_guard.py`: 提取了错误消息截断常量

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

- [ ] **重构 `backend/prompt_assembler.py`** (风险: 高)
  - 问题: 文件过长（800+行），职责过多
  - 建议: 拆分成多个模块
    - `prompt_assembler.py`: 主入口和协调逻辑
    - `token_budget.py`: Token 预算管理
    - `message_builder.py`: 消息构建逻辑
    - `macro_expander.py`: 宏展开逻辑
    - `world_info_processor.py`: World Info 处理
  - 注意: 这是高风险改动，需要充分测试

- [ ] **提取 `backend/routers/chat.py` 中的重复代码** (风险: 中)
  - 问题: `chat_stream` 和 `chat_guest_stream` 有大量重复的流式处理逻辑
  - 建议: 提取公共的流式处理函数
  - 文件: `backend/routers/chat.py`
  - 预计改动: 50-100 行

### 文档更新

- [ ] **更新 `docs/backend_api.md`** (风险: 低)
  - 任务: 检查所有 API 端点是否与实际代码一致
  - 任务: 补充缺失的 API 文档
  - 任务: 更新请求/响应示例
  - 重点检查:
    - 管理员相关接口
    - 支付相关接口
    - 聊天相关接口

- [ ] **创建架构文档** (风险: 低)
  - 文件: `docs/ARCHITECTURE.md`（新建）
  - 内容:
    - 项目整体架构图
    - 模块依赖关系
    - 数据流向
    - 关键设计决策

### 性能优化

- [ ] **优化数据库查询** (风险: 中)
  - 文件: `backend/services/chat_service.py`, `backend/prompt_assembler.py`
  - 问题: 部分查询可能存在 N+1 问题
  - 任务: 使用 `EXPLAIN QUERY PLAN` 分析慢查询
  - 任务: 添加必要的索引
  - 任务: 考虑使用连接查询替代多次单独查询

---

## 🟡 P2 优先级（中等问题）

### 代码质量

- [ ] **补充类型注解** (风险: 低)
  - 文件: 多个文件
  - 任务: 为缺少类型注解的函数补充注解
  - 重点文件:
    - `backend/card_import.py`
    - `backend/card_analyze.py`
    - `backend/routers/admin.py`

- [ ] **简化过长函数** (风险: 中)
  - 文件: `backend/routers/chat.py`
  - 问题: `chat_send`, `chat_stream`, `chat_guest_stream` 函数过长（>100行）
  - 建议: 提取辅助函数，提高可读性

- [ ] **统一错误处理** (风险: 中)
  - 问题: 不同模块的错误处理方式不一致
  - 建议: 创建统一的错误处理中间件
  - 文件: `backend/middleware/error_handler.py`（新建）

### 测试覆盖

- [ ] **添加单元测试** (风险: 低)
  - 目录: `backend/tests/`（新建）
  - 优先测试:
    - `backend/auth.py`: 鉴权逻辑
    - `backend/services/chat_service.py`: 聊天服务
    - `backend/model_adapter.py`: 模型适配器
  - 框架建议: pytest

- [ ] **添加集成测试** (风险: 低)
  - 目录: `backend/tests/integration/`（新建）
  - 测试场景:
    - 用户注册登录流程
    - 聊天完整流程
    - 支付回调流程

### 配置管理

- [ ] **配置文件结构化** (风险: 中)
  - 文件: `backend/config.py`
  - 问题: 配置项较多，可读性不够好
  - 建议: 使用 Pydantic 创建配置类
  - 好处: 类型检查、验证、文档生成

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
| 可测试性 | 3/10 | 缺少单元测试和集成测试 |
| 文档完整性 | 6/10 | 有基础文档，但需要更新和补充 |
| 代码规范 | 7/10 | 整体规范，但缺少自动化检查 |
| 性能 | 7/10 | 基本满足需求，有优化空间 |

### 改进目标

| 维度 | 目标评分 | 关键任务 |
|------|----------|----------|
| 安全性 | 9/10 | 完成 P0 安全性检查 |
| 可维护性 | 8/10 | 完成 P1 代码重构 |
| 可测试性 | 7/10 | 完成 P2 测试覆盖 |
| 文档完整性 | 8/10 | 完成 P1 文档更新 |
| 代码规范 | 8/10 | 完成 P3 代码风格统一 |
| 性能 | 8/10 | 完成 P1 性能优化 |

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
