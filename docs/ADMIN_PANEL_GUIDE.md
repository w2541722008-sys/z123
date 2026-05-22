# 管理后台指南

## 入口

- 管理后台入口：`frontend/admin/index.html`
- 通过 Nginx 反向代理访问：`https://你的域名/admin`

## 前端模块结构

当前后台 JS 模块共 18 个（`frontend/admin/js/`）：

- `utils.js`
- `api.js`
- `state.js`
- `config.js`
- `normalizers.js`
- `main.js`
- `bootstrap.js`
- `actions.js`
- `overview.js`
- `char-list.js`
- `char-crud.js`
- `char-editor.js`
- `char-editor-affection.js`
- `char-advanced.js`
- `membership.js`
- `dashboard.js`
- `audit-log.js`
- `prompt-preview.js`

## 权限模型

- 后台接口统一受管理员依赖保护：`Depends(get_admin_user)`
- 非管理员访问后台 API 会返回 403

## 关键功能区

- 仪表盘：统计与趋势
- 用户与会员：查询、编辑、批量档位
- 角色管理：基础信息、开场白、记忆、剧情线、规则、事件
- 审计日志：后台操作追踪

## 接口前缀

- 后台 API 统一挂载在 `/api/admin/*`

## 开发注意

- 交互事件统一走 `data-action` + 委托分发
- 新增 action 需通过 `tests/check_admin_actions.js --strict`
- 页面脚本顺序在 `frontend/admin/index.html` 已定义，调整时需同步验证
