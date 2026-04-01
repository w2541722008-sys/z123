# 管理后台使用指南

## 📍 统一入口

**唯一管理后台入口：** `/frontend/admin/index.html`

访问地址：`http://your-domain.com/frontend/admin/index.html`

## 🗂️ 文件结构

```
frontend/admin/
├── index.html          # 主入口文件
├── style.css           # 样式文件
└── js/
    ├── main.js         # 主逻辑
    ├── api.js          # API 调用
    ├── state.js        # 状态管理
    ├── utils.js        # 工具函数
    ├── dashboard.js    # 仪表盘
    ├── audit-log.js    # 操作日志
    ├── membership.js   # 会员管理
    ├── char-editor.js  # 角色编辑器
    ├── char-advanced.js # 角色高级设置
    └── prompt-preview.js # 提示词预览
```

## ✨ 功能特性

### 1. 仪表盘
- 实时统计数据
- 用户增长趋势
- 系统健康状态

### 2. 用户管理
- 用户列表（分页、搜索）
- 批量操作（启用/禁用、删除）
- 用户详情弹窗
- 导出 CSV

### 3. 会员管理
- 会员列表（搜索、筛选）
- 批量设置会员档位
- 订单详情查看

### 4. 角色管理
- 角色编辑器
- 高级设置
- 提示词预览

### 5. 操作日志
- 完整的操作记录
- 日志筛选和搜索

## 📝 历史说明

- **2026-04-01**: 统一管理后台入口，废弃根目录的 `admin.html`
- 旧版 `admin.html` 已备份为 `admin.html.backup`（功能较简单，不推荐使用）

## 🚀 部署注意事项

确保 Web 服务器配置正确映射 `/frontend/admin/` 目录下的所有静态资源。
