# 前端架构文档

> **最后更新**: 2026-04-03
> **前端技术**: 原生 HTML/CSS/JS（无框架）
> **架构模式**: IIFE 模块化（11 个模块，全局对象通信）
> **新增功能**: 头像系统（用户上传/默认头像）、P2 优化（SSE abort / fetch 超时 / 批量渲染）

---

## 一、架构概览

### 从单文件到模块化的演进

项目最初使用单文件 `frontend/app.js`（~1957 行）承载所有前端逻辑。2026-04-01 完成重构，**删除了旧的单文件**，拆分为 **11 个 IIFE 模块**，按职责清晰分离：

| 维度 | 重构前 | 重构后 |
|------|--------|--------|
| 文件数 | 1 个（app.js ~1957行） | 11 个模块 |
| 模式 | 单文件内按注释分区 | IIFE + 全局对象 |
| 加载方式 | 单个 `<script>` 标签 | 11 个 `<script>` 按依赖顺序加载 |
| 可维护性 | 低（文件过长） | 高（每个模块职责单一） |

---

## 二、目录结构

```
frontend/
├── index.html                   # 主入口 HTML（Lunar 品牌）
├── style.css                    # 全局样式（深色毛玻璃风格，~2000行）
├── forgot-password.html         # 密码重置页
├── forgot-password.js           # 密码重置逻辑
│
├── assets/                      # 静态资源
│   └── default-avatar.png       # 默认头像
│
└── modules/                     # 前端 JS 模块（IIFE 模式）
    ├── init.js                  # 初始化入口（最后加载，启动应用）
    ├── app.js                   # 应用主逻辑（页面路由、状态管理、事件绑定）
    ├── chat.js                  # 聊天核心（SSE 流式、regenerate、continue）
    ├── chat-menu.js             # 聊天菜单（清空记录等操作）
    ├── api.js                   # API 封装（统一 fetch、token 注入、SSE 处理）
    ├── auth.js                  # 认证逻辑（登录/注册/token 管理/游客模式）
    ├── ui.js                    # UI 组件（Toast、Modal、加载动画）
    ├── utils.js                 # 工具函数（时间格式化、HTML 转义、文本渲染）
    ├── config.js                # 配置常量（API 地址、导航配置）
    ├── char-detail.js           # 角色详情页
    └── greeting-select.js       # 开场白选择弹窗
```

---

## 三、模块依赖关系与加载顺序

`index.html` 中 **11 个 `<script>` 标签必须严格按以下顺序加载**：

```
index.html
  │
  ├─ 1. ui.js          → window.UI        （无依赖）
  ├─ 2. config.js      → window.Config     （无依赖）
  ├─ 3. utils.js       → window.Utils      （无依赖）
  ├─ 4. api.js         → window.API        （依赖 Config）
  │
  ├─ 5. app.js         → window.App        （依赖 API, Utils, UI）
  ├─ 6. auth.js        → window.Auth       （依赖 API, UI）
  │
  ├─ 7. chat.js        → window.Chat       （依赖 API, UI, Auth）← 最大模块 ~970行
  ├─ 8. chat-menu.js   → （注册事件，依赖 Chat）
  │
  ├─ 9. char-detail.js → （注册事件，依赖 API）
  ├─ 10. greeting-select.js → （注册事件，依赖 API, UI）
  │
  └─ 11. init.js       → 执行启动逻辑      （依赖以上所有）
```

**关键规则**：`function` 声明不会跨 `<script>` 标签提升，所以被依赖的模块必须先加载。

---

## 四、各模块详细说明

### 4.1 init.js — 初始化入口

- **职责**：应用启动的最后一环，绑定全局事件、初始化页面状态
- **暴露对象**：无（执行副作用，不暴露全局对象）
- **调用时机**：DOM ready 后自动执行

### 4.2 app.js — 应用主逻辑

- **职责**：页面路由切换（section 显示/隐藏）、全局状态管理、导航绑定
- **核心功能**：
  - `showPage(pageId)` / `hideAllPages()` — 页面路由
  - 角色广场数据加载和渲染
  - 全局事件委托（返回按钮、导航链接等）
- **暴露对象**：`window.App`

### 4.3 chat.js — 聊天核心（最大模块）

- **职责**：聊天功能的核心实现，是整个前端最复杂的模块（~1150 行）
- **核心功能**：
  - `sendMessage()` — 发送消息 + SSE 流式接收
  - `regenerateMessage(messageId, rowEl, bubbleEl)` — 重新生成（↻ 按钮）
  - `continueMessage(messageId, rowEl, bubbleEl)` — 继续生成（▶ 按钮）
  - `renderTextWithLineBreaks()` — 消息渲染（支持换行符转 `<br>`）
  - `appendMsg()` / `createStreamRow()` / `showTyping()` — 消息 DOM 构建
  - `createMsgAvatar(type, charData)` — 头像元素创建（角色/用户，支持图片+首字母回退）
  - `renderHistory()` — 加载历史消息（DocumentFragment 批量渲染优化）
  - `_lastMsgTimestamp` / `shouldShowTime()` / `formatSmartTime()` — 智能时间戳（>5分钟间隔显示）
- **P2-SSE 连接管理**：
  - `_streamController` — 模块级 AbortController 实例
  - `abortStream()` — 中断当前活跃的 SSE 连接
  - 每次 send/regenerate/continue 前自动调用 `abortStream()` + 创建新 Controller
  - 所有 4 处流式 API 调用传递 `signal` 参数（guestStreamMessage/streamMessage/regenerateMessage/continueMessage）
- **P2-批量渲染**：
  - `_batchContainer` — DocumentFragment 实例，用于 `renderHistory()` 批量模式
  - 批量模式下所有 DOM 节点先写入 Fragment，最后一次性挂载到 chat-messages 容器
  - N 条历史消息仅触发 1 次 reflow，跳过 N-1 次 scrollToBottom
- **Regenerate 流程**：
  1. 点击 ↻ 按钮 → 按钮添加 `.loading` 类（CSS spinner 动画，居中显示在按钮内）
  2. POST `/api/chat/regenerate` → SSE 流式接收 chunk
  3. 每个 chunk 直接写入原气泡 `bubbleEl.innerHTML`
  4. done 事件 → 更新本地 history 数组（反向查找匹配 messageId）
  5. finally → 移除 loading 状态，恢复按钮图标
- **Continue 流程**：
  1. 点击 ▶ 按钮 → 显示 typing 指示器（"..."跳动点）
  2. 隐藏原气泡的操作按钮
  3. POST `/api/chat/continue` → SSE 流式接收
  4. 首个 chunk 到达时 → 在原气泡下方创建全新的 row + bubble
  5. 每个 chunk 写入新气泡
  6. done 事件 → 使用 `payload.appended_text`（仅新增部分）渲染新气泡内容
  7. 为新气泡绑定独立的 regenerate/continue 按钮
- **并发控制**：`isSending` 标志位，操作中禁用所有相关按钮
- **暴露对象**：`window.Chat`

### 4.4 api.js — API 封装

- **职责**：统一 HTTP 请求处理、Token 注入、SSE 流式解析
- **核心接口**：
  - `API.post(url, body)` — 普通 POST 请求
  - `API.streamMessage(payload, handlers, signal?)` — SSE 流式请求（支持 AbortController signal）
  - `API.guestStreamMessage(payload, handlers, signal?)` — 游客流式请求
  - `API.regenerateMessage(payload, handlers, signal?)` — regenerate 代理
  - `API.continueMessage(payload, handlers, signal?)` — continue 代理
  - `API.uploadAvatar(file)` — 用户头像上传（FormData，multipart）
  - `API.get(url)` — GET 请求
- **P2-fetch 超时控制**：
  - `request()` 函数内置 AbortController + setTimeout(20s) 默认超时
  - 超时时返回友好错误提示 `'请求超时，请检查网络后重试'`
  - 可通过 `{ timeout: 30000 }` 覆盖默认超时时间
  - `finally` 中 `clearTimeout(timer)` 防止内存泄漏
- **SSE 解析**：统一处理 `event: chunk` / `event: done` / `event: error`
- **暴露对象**：`window.API`

### 4.5 auth.js — 认证逻辑

- **职责**：登录/注册/登出、Token 管理、用户头像、游客模式判断
- **核心功能**：
  - `Auth.login(email, password)` / `Auth.register()`
  - `Auth.isLoggedIn()` / `Auth.getToken()` / `Auth.getUser()`
  - `Auth.logout()` — 清除本地存储
  - `Auth.uploadAvatar(file)` — 上传用户头像（调用 API + 更新本地状态 + 刷新 Profile）
  - `Auth.renderProfile()` — 渲染"我的"页面用户信息（含头像显示+点击上传）
  - `Auth.bootstrap()` — 页面加载时恢复登录态（仅认证失败时清 token，不因网络误退出）
- **暴露对象**：`window.Auth`

### 4.6 ui.js — UI 组件

- **职责**：通用 UI 组件，纯展示逻辑
- **核心组件**：
  - `UI.toast(msg, type)` — Toast 提示（success/error/warning）
  - `UI.showModal(options)` / `UI.hideModal()` — 模态对话框
  - `UI.showTyping()` / `UI.removeTyping()` — 打字指示器
  - `UI.setSending(flag)` — 全局发送状态
- **暴露对象**：`window.UI`

### 4.7 utils.js — 工具函数

- **职责**：纯函数工具集，无副作用
- **核心函数**：
  - `Utils.formatTime(isoStr)` — ISO 时间 → 友好显示
  - `Utils.escapeHtml(str)` — XSS 防护
  - `Utils.renderTextWithLineBreaks(el, text, append)` — 文本渲染
  - `Utils.truncate(str, len)` — 文本截断
- **暴露对象**：`window.Utils`

### 4.8 config.js — 配置常量

- **职责**：集中管理配置常量
- **内容**：API_BASE_URL、角色卡片默认配置、导航映射等
- **暴露对象**：`window.Config`

### 4.9 chat-menu.js — 聊天菜单

- **职责**：聊天页面的操作菜单（清空记录、切换剧情线等）
- **触发方式**：点击聊天页顶部菜单图标
- **暴露对象**：无（通过 DOM 事件绑定）

### 4.10 char-detail.js — 角色详情

- **职责**：角色详情页的数据加载和展示
- **暴露对象**：无（通过 DOM 事件绑定）

### 4.11 greeting-select.js — 开场白选择

- **职责**：多剧情线开场白选择弹窗
- **交互**：弹窗列表展示 → 选择后清空当前对话并切换剧情线
- **暴露对象**：无（通过 DOM 事件绑定）

### 4.12 头像系统（跨模块协作）

头像功能涉及多个模块协同工作：

**用户头像（Profile 页 + 聊天消息）**
- `auth.js:renderProfile()` — "我的"页面显示用户头像，点击触发上传
- `auth.js:uploadAvatar(file)` — 调用 API 上传 → 更新本地状态 → 刷新渲染
- `api.js:uploadAvatar(file)` — FormData multipart POST 到 `/api/user/avatar`
- `init.js` — 绑定隐藏 `<input type="file">` 的 change 事件
- `main.py` (后端) — POST/GET `/api/user/avatar` + `/avatars` 静态挂载

**角色头像（聊天消息）**
- `chat.js:createMsgAvatar('char', charData)` — 创建角色头像元素
- 支持图片 URL（avatarImg/coverImg）→ 首字母+渐变回退
- AI 消息行左侧显示角色头像，用户消息行右侧显示用户头像

**样式规范**
- `.msg-avatar`: 36px 正方形 (`aspect-ratio: 1/1`, `overflow: hidden`)
- `.profile-avatar`: 56px 正方形（Profile 页面）
- 所有头像强制正方形，防止图片变形

### 4.13 智能时间戳系统

微信风格的时间戳显示逻辑：

```
规则：
  - 首条消息 / 新对话：始终显示
  - 间隔 < 5 分钟：不显示
  - 间隔 ≥ 5 分钟：居中显示时间分割线
格式：
  - 今天：HH:mm（如 "15:30"）
  - 昨天："昨天 HH:mm"
  - 更早："MM月DD日 HH:mm"
```

涉及函数：
- `_lastMsgTimestamp` — 模块级变量，记录上一条消息时间戳
- `shouldShowTime(timestamp)` — 判断是否需要显示时间
- `formatSmartTime(date)` — 格式化为友好字符串
- 在 `appendMsg()`、`createStreamRow()`、`continueMessage()` 中统一调用

---

## 五、管理后台（frontend/admin/）

管理后台采用类似的模块化设计，10 个 JS 文件：

```
frontend/admin/
├── index.html                # 后台入口
├── style.css                 # 后台样式
└── js/
    ├── utils.js              # 工具函数
    ├── api.js                # API 封装
    ├── main.js               # 主逻辑（路由、初始化、Tab 切换）
    ├── dashboard.js          # 仪表盘
    ├── char-editor.js        # 角色基础信息编辑器
    ├── char-advanced.js      # 高级配置（记忆/开场白/剧情线/事件/规则）
    ├── membership.js         # 会员管理
    ├── prompt-preview.js     # Prompt 预览
    ├── state.js              # 角色状态查看
    └── audit-log.js          # 审计日志
```

后台访问地址：`https://yourdomain.com/admin.html`
需使用 `ADMIN_EMAILS` 中配置的管理员邮箱登录。

---

## 六、样式系统（style.css）

### 设计风格

- **深色毛玻璃主题**：深色背景（`#0a0e1a`）+ 半透明卡片（`backdrop-filter: blur`）
- **移动端优先**：基于 `max-width: 768px` 媒体查询适配
- **渐变和光效**：品牌紫色/粉色渐变，背景星尘光效动画
- **字体**：Google Fonts（Inter + Noto Sans SC）

### 关键样式区域

| 区域 | 说明 |
|------|------|
| `.phone-shell` | 手机外壳容器（桌面端居中显示） |
| `.msg-bubble` | 聊天气泡（user / ai 双向样式） |
| `.msg-action-btn` | AI 消息操作按钮（↻ 重新生成 / ▶ 继续生成） |
| `.msg-action-btn.loading` | 按钮加载状态（spinner 居中旋转动画） |
| `.guest-trial-bar` | 游客体验额度提示条 |
| `.greeting-modal` | 开场白选择弹窗 |

### 版本号机制

`index.html` 中 CSS 和 JS 引用带版本号参数：
```html
<link rel="stylesheet" href="frontend/style.css?v=20260402v21" />
<script src="frontend/modules/chat.js?v=24"></script>
<script src="frontend/modules/api.js?v=3"></script>
```
每次修改对应文件后必须手动更新版本号，否则浏览器可能使用缓存。

---

## 七、开发指南

### 修改聊天功能

1. 打开 `frontend/modules/chat.js`
2. 找到对应函数（文件内有清晰的函数定义）
3. 修改后更新 `index.html` 中 `chat.js?v=` 的版本号
4. Cmd+Shift+R 强制刷新测试

### 修改其他模块

1. 确定目标模块（见第三节模块说明）
2. 在对应的 `.js` 文件中修改
3. 更新 `index.html` 中该文件的版本号

### 新增模块

1. 在 `frontend/modules/` 下新建 `xxx.js`
2. 使用 IIFE 包装：`const Xxx = (() => { ... return { ... }; })();`
3. 在 `index.html` 的 `<script>` 列表中按依赖顺序插入
4. 确保不破坏已有模块的全局对象

### 调试技巧

- 浏览器开发者工具 F12 → Console 查看 `window.Chat`、`window.API` 等全局对象
- Network 面板查看 SSE 流（Filter: `event-stream`）
- 所有 API 错误会显示红色 Toast
- 后端 chat.py 的日志可帮助排查上下文问题

---

## 八、SSE 事件协议

### 标准聊天流（/api/chat/stream）

```
event: chunk
data: {"type":"chunk","text":"片段内容"}

event: done
data: {"type":"done","reply":"完整回复","character_state":{...},"message_id":"uuid"}
```

### 重新生成（/api/chat/regenerate）

```
event: chunk
data: {"type":"chunk","text":"片段内容"}

event: done
data: {"type":"done","reply":"完整替换内容","message_id":"uuid","operation":"regenerate"}
```

### 继续生成（/api/chat/continue）

```
event: chunk
data: {"type":"chunk","text":"片段内容"}

event: done
data: {"type":"done","reply":"原始+追加完整内容","appended_text":"仅新增部分","message_id":"uuid","operation":"continue"}
```

> **注意**：continue 的 done 事件包含两个字段：
> - `reply`：拼接后的完整内容（用于数据库保存）
> - `appended_text`：仅新增的部分（用于前端新气泡渲染）

### 错误事件

```
event: error
data: {"type":"error","message":"错误描述"}
```

---

## 九、更新记录

- **2026-04-03**: 补充头像系统（4.12）、智能时间戳（4.13）章节；更新模块接口描述（auth.js 新增 uploadAvatar/renderProfile/getUser/isLoggedIn，api.js 新增 uploadAvatar，chat.js 新增 createMsgAvatar/智能时间戳）；更新版本号
- **2026-04-03（P2）**: 新增 P2-SSE 连接管理章节（chat.js _streamController/abortStream/4处 signal 传递）；新增 P2-fetch 超时控制章节（api.js AbortController 20s 超时）；新增 P2-批量渲染章节（renderHistory DocumentFragment）；更新 api.js 接口签名（signal 可选参数）；更新版本号至 chat.js v24 / api.js v3
- **2026-04-02**: 完全重写架构文档，反映 11 模块 IIFE 架构；补充 Regenerate/Continue 功能文档
- **2026-04-01**: 前端从单文件 app.js 重构为 11 个 IIFE 模块
- **2026-03-29**: 管理后台从单文件 admin.html 重构为 frontend/admin/ 模块化方案
