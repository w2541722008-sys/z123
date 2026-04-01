# 前端架构文档

> **最后更新**: 2026-04-01
> **前端技术**: 原生 HTML/CSS/JS（无框架）

---

## 目录结构

```
frontend/
├── app.js                        # 主前端逻辑（~1957 行，单文件 SPA）
├── style.css                     # 全局样式（~1851 行，深色毛玻璃风格）
├── forgot-password.html          # 密码重置页
├── forgot-password.js            # 密码重置逻辑
│
└── admin/                        # 管理后台（模块化设计）
    ├── index.html                # 后台入口（~769 行）
    ├── style.css                 # 后台样式
    └── js/                       # 后台 JS 模块（10 个文件）
        ├── main.js               # 主逻辑（路由、初始化、Tab 切换）
        ├── api.js                # API 封装（所有后端请求）
        ├── char-editor.js        # 角色基础信息编辑器
        ├── char-advanced.js      # 高级配置（记忆/开场白/剧情线/事件/规则）
        ├── dashboard.js          # 仪表盘（用户统计、最近活动）
        ├── membership.js         # 会员管理（套餐、订单、手动调级）
        ├── prompt-preview.js     # Prompt 预览（查看 AI 实际收到的内容）
        ├── state.js              # 角色状态查看
        ├── audit-log.js          # 审计日志
        └── utils.js              # 工具函数（Toast、格式化等）
```

---

## 主应用（frontend/app.js）

### 架构

主应用是**单文件 SPA**（~1957 行），通过显示/隐藏不同 `<section>` 实现页面切换。没有使用任何前端框架（无 React/Vue/等），纯原生 JavaScript。

### 页面（Section）路由

| Section ID | 说明 |
|-----------|------|
| `#page-home` | 首页（品牌主视觉 + 产品卖点） |
| `#page-square` | 角色广场（按 card_type 分区展示） |
| `#page-chat` | 聊天页（SSE 流式输出、状态栏、好感度进度条） |
| `#page-mine` | 我的（登录状态、设置、长期记忆说明） |

### 核心功能模块（内聚在单文件中）

虽然都在一个文件里，但代码按功能区域组织：

| 功能区域 | 职责 |
|---------|------|
| **配置常量** | API 基地址、角色配置、导航配置 |
| **本地存储** | LocalStorage 封装（token、用户信息、缓存） |
| **API 调用** | fetch 封装，统一错误处理和 token 注入 |
| **认证** | 登录/注册/登出、token 管理 |
| **角色广场** | 角色列表渲染、分区展示、筛选 |
| **聊天核心** | 消息发送/接收、SSE 流式处理、状态更新解析 |
| **UI 交互** | Toast 提示、确认对话框、加载动画 |
| **Markdown** | 简易 Markdown 渲染（代码块、加粗、斜体等） |

### SSE 流式聊天

```javascript
// 前端通过 POST /api/chat/stream 建立 SSE 连接
// 事件格式：
// data: {"type":"chunk","content":"文本片段"}\n\n
// data: {"type":"done","reply":"完整回复","state_update":{...}}\n\n

// 使用 fetch + ReadableStream 处理流式响应
const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}` },
    body: JSON.stringify({ character_id, message })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
// 循环读取 chunk，实时更新聊天界面
```

### 游客模式

- 未登录用户可直接走游客聊天（`POST /api/chat/guest-stream`）
- 聊天页顶部显示"游客体验额度"进度条
- 额度用完后引导登录/注册

### 加载方式

在 `index.html` 中通过单个 `<script>` 标签加载：

```html
<script src="/frontend/app.js?v=2026032901"></script>
```

版本号 `v=` 参数用于缓存刷新，每次更新前端文件时需要手动更新。

---

## 管理后台（frontend/admin/）

### 架构

管理后台采用**模块化设计**，与主应用不同。10 个 JS 文件通过 `<script>` 按顺序加载，每个文件暴露自己的全局对象（如 `window.AdminAPI`、`window.CharEditor`）。

### 加载顺序

```html
<script src="/frontend/admin/js/utils.js"></script>        <!-- 1. 工具函数 -->
<script src="/frontend/admin/js/api.js"></script>          <!-- 2. API 封装 -->
<script src="/frontend/admin/js/main.js"></script>         <!-- 3. 主逻辑 -->
<script src="/frontend/admin/js/dashboard.js"></script>    <!-- 4. 仪表盘 -->
<script src="/frontend/admin/js/char-editor.js"></script>  <!-- 5. 角色编辑 -->
<script src="/frontend/admin/js/char-advanced.js"></script><!-- 6. 高级配置 -->
<script src="/frontend/admin/js/membership.js"></script>   <!-- 7. 会员管理 -->
<script src="/frontend/admin/js/prompt-preview.js"></script><!-- 8. Prompt预览 -->
<script src="/frontend/admin/js/state.js"></script>        <!-- 9. 角色状态 -->
<script src="/frontend/admin/js/audit-log.js"></script>    <!-- 10. 审计日志 -->
```

### 功能分布

| 文件 | 职责 |
|------|------|
| `utils.js` | Toast 通知、确认对话框、日期格式化、文件大小格式化 |
| `api.js` | 所有管理后台 API 请求封装，统一认证 header |
| `main.js` | 初始化、Tab 切换路由、角色列表管理、通用 CRUD 操作 |
| `dashboard.js` | 用户统计、最近活动、系统状态概览 |
| `char-editor.js` | 角色基础信息编辑（名称、描述、标签、头像、封面等） |
| `char-advanced.js` | 高级配置：记忆条目(WI)、分类、开场白、剧情线、后置规则、剧情事件 |
| `membership.js` | 会员套餐管理、用户订单查看、手动设置会员等级 |
| `prompt-preview.js` | 查看发给 AI 的完整 Prompt（调试用） |
| `state.js` | 查看用户与角色的关系状态（好感度、阶段、心情） |
| `audit-log.js` | 查看管理操作审计日志 |

### 访问方式

- 后台入口：`http://你的域名/admin.html`
- 需要使用 `ADMIN_EMAILS` 中配置的管理员邮箱登录
- 登录后在顶部 Tab 切换：仪表盘 / 角色管理 / 会员管理 / 审计日志

---

## 样式（frontend/style.css）

### 设计风格

- **深色毛玻璃主题**：深色背景 + 半透明卡片
- **移动端优先**：基于 `max-width` 媒体查询适配
- **渐变和光效**：按钮、背景使用 CSS 渐变
- **加载动画**：聊天中显示打字机效果的加载指示

### 管理后台样式（frontend/admin/style.css）

- 独立于主应用的样式文件
- 表格、表单、Tab 切换的样式
- 响应式布局适配

---

## 开发指南

### 修改主应用（app.js）

1. 打开 `frontend/app.js`
2. 按功能区域找到对应代码（文件内有注释分隔）
3. 修改后更新 `index.html` 中的版本号 `?v=2026032901`

### 修改管理后台

1. 确定修改的功能属于哪个模块文件
2. 在对应的 JS 文件中修改
3. 管理后台目前没有版本号机制，刷新即可

### 调试技巧

- 使用浏览器开发者工具（F12）查看 Console 和 Network
- 主应用的所有 API 调用都有统一错误处理，错误会显示 Toast
- 管理后台的 API 错误会弹出红色 Toast

---

## 更新记录

- **2026-04-01**: 重写架构文档，反映实际的单文件 SPA + 模块化后台结构
- **2026-03-29**: 管理后台从单文件 `admin.html` 重构为 `frontend/admin/` 模块化方案
