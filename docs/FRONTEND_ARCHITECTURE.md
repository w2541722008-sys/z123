# 前端架构（当前版本）

## 总体结构

- 用户前台：`index.html` + `frontend/modules/*.js`
- 管理后台：`frontend/admin/index.html` + `frontend/admin/js/*.js`
- 共享工具：`frontend/shared/shared-utils.js`

前台与后台均使用原生 JavaScript + IIFE 模块组织，不依赖前端框架。

## 前台模块（`frontend/modules/`）

核心职责分层：

- 配置与工具：`config.js`、`utils.js`
- API 与认证：`api.js`、`auth.js`
- 业务主流程：`app.js`、`chat.js`、`chat-menu.js`、`chat-status-panel.js`
- 页面能力：`char-detail.js`、`greeting-select.js`
- UI 与启动：`ui.js`、`error-boundary.js`、`init.js`

## 后台模块（`frontend/admin/js/`）

后台采用"入口瘦身 + 模块分域"组织：

- 基础层：`utils.js`、`api.js`、`state.js`、`config.js`、`normalizers.js`
- 分域层：`overview.js`、`char-list.js`、`char-crud.js`、`char-editor.js`、`char-advanced.js`、`membership.js`、`dashboard.js`、`audit-log.js`、`prompt-preview.js`
- 编排层：`bootstrap.js`、`actions.js`、`main.js`

## 事件模型

- 后台交互以 `data-action` + 事件委托为主
- `actions.js` 维护 action 分发映射
- `bootstrap.js` 负责统一绑定与启动流程

## 脚本加载顺序

- 后台页面脚本顺序由 `frontend/admin/index.html` 固定管理
- 任何新增模块都应遵守"被依赖模块先加载"的规则

## 质量门禁

- 前端单测：`node tests/test_frontend_utils.js`
- 后台 action 校验：`node tests/check_admin_actions.js --strict --allow-list=tests/admin_action_allowlist.json`
