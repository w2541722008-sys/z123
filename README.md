# aifriend — 女性向 AI 男友 H5 聊天应用

> **给接手这个项目的一句话**：这是一个面向女性用户的 AI 角色扮演聊天 H5 应用（前端品牌名 Lunar），主打沉浸感和长期记忆。后端 Python FastAPI + Supabase (PostgreSQL)，前端纯原生 HTML/JS，通过 SillyTavern 兼容的 PNG 角色卡驱动 AI 角色。

---

## 先用大白话理解这个项目

如果你现在对项目还不熟，可以先把它理解成下面 5 句话：

1. **前台就是一个聊天网页**：用户在 `index.html + frontend/modules/`（11 个 IIFE 模块）里选角色、聊天、登录、看历史。
2. **后台就是一个角色配置台**：你在 `frontend/admin/` 里改角色资料、开场白、记忆、剧情线、事件和后置规则。
3. **后端像"总调度"**：FastAPI 负责收消息、查数据库、拼 Prompt、调模型、保存聊天记录。
4. **数据库是 Supabase (PostgreSQL)**：所有用户、角色、聊天记录、关系状态、长期记忆摘要都存在云端，支持多设备同步。
5. **角色卡不是直接拿来就聊**：PNG 角色卡先导入数据库，再由后台继续补展示字段和高级配置，最后才给用户使用。

一句话版流程就是：

**用户发消息 → 后端查角色配置和历史 → 拼成 Prompt → 调 AI → 保存回复和状态 → 下次继续接着聊。**

---

## 目录

1. [项目定位](#1-项目定位)
2. [技术架构总览](#2-技术架构总览)
3. [目录结构](#3-目录结构)
4. [快速启动](#4-快速启动)
5. [API 路由一览](#5-api-路由一览)
6. [核心模块详解](#6-核心模块详解)
7. [数据库 Schema](#7-数据库-schema)
8. [角色卡系统](#8-角色卡系统)
9. [Prompt 分层架构](#9-prompt-分层架构)
10. [好感度 / 状态系统](#10-好感度--状态系统)
11. [前端页面结构](#11-前端页面结构)
12. [环境变量配置](#12-环境变量配置)
13. [部署上线](#13-部署上线)
14. [开发规范与维护原则](#14-开发规范与维护原则)

---

## 1. 项目定位

| 维度 | 说明 |
|------|------|
| **目标用户** | 女性向音频 / 二次元粉丝（B站、云do圈子用户） |
| **核心功能** | AI 角色扮演聊天、长期记忆、多条剧情线、好感度系统 |
| **定位** | 正式产品，非玩具原型。代码简洁优雅、模块清晰，借鉴 SillyTavern 设计思路 |
| **当前阶段** | MVP，已上线部署（VPS + Supabase），支持手机端访问 |

---

## 2. 技术架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                       用户（浏览器/手机）                      │
│                  访问 https://yourdomain.com                 │
│                  （生产环境必须 HTTPS，                     │
│                   Nginx/OpenResty 反向代理 + SSL 证书）       │
└─────────────────────┬───────────────────────────────────────┘
                      │  HTTP / SSE 流式
┌─────────────────────▼───────────────────────────────────────┐
│                  FastAPI 后端 (Python 3.10+)                  │
│  Uvicorn + OpenResty(Docker) 反向代理                        │
│                                                             │
│  ┌───────────┐  ┌────────────────┐  ┌───────────────────┐  │
│  │  main.py  │  │prompt_assembler│  │ model_adapter.py  │  │
│  │ 路由/鉴权  │  │  Prompt分层    │  │ AI API 适配层     │  │
│  └───────────┘  └────────────────┘  └───────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │        Supabase PostgreSQL（云端数据库）               │  │
│  │        psycopg2 连接池，ConnWrapper 兼容层            │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  静态文件 serve（GET /  GET /admin.html  /frontend/*）       │
└─────────────────────────────────────────────────────────────┘

前端文件位置（由后端直接 serve）：
  aifriend/index.html             ← 主 H5 应用入口（Lunar 品牌）
  aifriend/frontend/admin/        ← 后台管理
  aifriend/frontend/modules/      ← 前端 JS 模块（11 个 IIFE 模块，原生 JS）
  aifriend/frontend/style.css     ← 全局样式（深色毛玻璃风格）

AI 接口：
  MiniMax M2.7（国内版 minimaxi.com）
  接口兼容 OpenAI Chat Completions 格式
  支持 SSE 流式输出
  三套模型策略：Basic / VIP / SVIP
```

### 技术栈一览

| 层 | 技术 | 说明 |
|----|------|------|
| 后端 | Python FastAPI + uvicorn/gunicorn | 轻量高性能 |
| 数据库 | Supabase (PostgreSQL) | 云端托管，psycopg2 连接池 |
| 前端 | 原生 HTML/CSS/JS | 无框架，单页应用 |
| AI | MiniMax API | OpenAI 兼容格式 |
| 邮件 | Resend API | 密码重置验证码 |
| 部署 | VPS + OpenResty(Docker) + Uvicorn + Let's Encrypt SSL | 生产环境 |

---

## 3. 目录结构

```
aifriend/
├── README.md                    # 本文件
├── index.html                   # 前端入口页（Lunar 品牌）
├── deploy.sh                    # 部署打包脚本
├── avatars/                     # 角色头像存储目录（运行时生成）
├── covers/                      # 角色封面存储目录（运行时生成）
│   └── .gitkeep                 # 占位文件
│
├── backend/                     # Python 后端
│   ├── main.py                  # FastAPI 主入口，路由挂载、静态文件、头像 API
│   ├── config.py                # 配置管理（环境变量读取）
│   ├── database.py              # Supabase (PostgreSQL) 连接池 + ConnWrapper
│   ├── auth.py                  # 认证核心（密码hash、token、CurrentUser类）
│   ├── model_adapter.py         # AI模型适配器（Basic/VIP/SVIP 三套策略）
│   ├── prompt_assembler.py      # Prompt 拼装（TokenBudget 预算 + World Info 关键词触发）
│   ├── models.py                # Pydantic 数据模型
│   ├── card_asset_parser.py     # 角色卡资源解析（SillyTavern 格式）
│   ├── card_feature_mapper.py   # 角色特征映射
│   ├── card_text_utils.py       # 文本处理工具
│   │
│   └── cli/                     # CLI 工具目录
│       ├── __init__.py          # 包初始化
│       ├── card_import.py       # PNG 角色卡导入
│       └── card_analyze.py      # 角色卡 AI 分析
│   ├── backup_supabase.sh       # Supabase 数据库备份脚本
│   ├── .env.example             # 环境变量配置模板
│   ├── requirements.txt         # Python 依赖
│   │
│   ├── routers/                 # API 路由
│   │   ├── auth.py              # 认证路由（注册/登录/登出/密码重置）
│   │   ├── chat.py              # 聊天路由（发送/流式/试聊/历史）
│   │   ├── characters.py        # 角色路由（列表/详情/状态）
│   │   ├── admin/               # 管理后台路由包（按业务域拆分）
│   │   │   ├── __init__.py      # 包入口，聚合 4 个子模块路由
│   │   │   ├── _shared.py       # 共享常量 + 事务工具 + 审计日志
│   │   │   ├── characters.py    # 角色管理（34 路由：CRUD + 记忆/开场白/剧情线/规则/事件）
│   │   │   ├── users.py         # 用户管理（7 路由：用户 CRUD + 会员操作）
│   │   │   ├── orders.py        # 订单管理（3 路由：订单列表/导出/详情）
│   │   │   └── dashboard.py     # 仪表盘（5 路由：统计/趋势图/审计日志）
│   │   └── billing.py           # 计费路由（会员计划/订单）
│   │
│   ├── services/                # 业务逻辑
│   │   ├── chat_service.py      # 聊天核心（上下文准备、开场白、回复保存）
│   │   ├── memory_service.py    # 记忆管理（摘要生成、消息整理、状态标签解析）
│   │   ├── character_state.py   # 角色状态（好感度、剧情阶段、事件触发）
│   │   ├── usage_guard.py       # 用量控制（token 预估、日限额检查、请求日志）
│   │   ├── plan_service.py      # 会员计划服务
│   │   ├── rate_limit.py        # 限流服务
│   │   ├── cache_service.py     # 缓存服务
│   │   ├── db_monitor.py        # 数据库监控
│   │   └── email.py             # 邮件发送（Resend）
│   │
│   ├── models/
│   │   └── character_config.py  # 角色配置数据模型
│   │
│   └── utils/
│       └── json_utils.py        # JSON 工具函数
│
├── frontend/                    # 前端（IIFE 模块化架构，11 个模块）
│   ├── style.css                # 主样式（深色毛玻璃风格）
│   ├── forgot-password.html     # 密码重置页
│   ├── forgot-password.js       # 密码重置逻辑
│   ├── assets/                  # 静态资源（默认头像等）
│   │
│   └── modules/                 # 前端 JS 模块（IIFE 模式）
│       ├── init.js              # 初始化入口（最后加载，启动应用）
│       ├── app.js               # 应用主逻辑（页面路由、状态管理）
│       ├── chat.js              # 聊天核心（SSE 流式、regenerate、continue）
│       ├── chat-menu.js         # 聊天菜单（清空记录等操作）
│       ├── api.js               # API 封装（统一 fetch、token 注入）
│       ├── auth.js              # 认证逻辑（登录/注册/token 管理）
│       ├── ui.js                # UI 组件（Toast、Modal、加载动画）
│       ├── utils.js             # 工具函数（时间格式化、转义等）
│       ├── config.js            # 配置常量（API 地址、导航配置）
│       ├── char-detail.js       # 角色详情页
│       └── greeting-select.js   # 开场白选择弹窗
│
│   └── admin/                   # 管理后台
│       ├── index.html           # 后台入口（~769行）
│       ├── style.css            # 后台样式
│       └── js/                  # 后台 JS 模块
│           ├── main.js          # 后台主逻辑
│           ├── api.js           # API 封装
│           ├── char-editor.js   # 角色编辑器
│           ├── char-advanced.js # 高级配置（记忆/开场白/剧情线/事件/规则）
│           ├── dashboard.js     # 仪表盘
│           ├── membership.js    # 会员管理
│           ├── prompt-preview.js# Prompt 预览
│           ├── state.js         # 角色状态管理
│           ├── audit-log.js     # 审计日志
│           └── utils.js         # 工具函数
│
├── docs/                        # 文档
│   ├── AFFECTION_SYSTEM.md      # 好感度系统说明
│   ├── backend_api.md           # 后端 API 文档
│   ├── supabase_schema.sql      # 数据库建表 SQL（17张表）
│   ├── CHARACTER_IMPORT_SOP.md  # 角色导入 SOP
│   ├── DEPLOYMENT_GUIDE_VPS.md  # VPS 部署指南
│   ├── DEPLOYMENT_CHECKLIST.md  # 部署检查清单
│   ├── DATABASE_BACKUP_GUIDE.md # 数据库备份指南
│   ├── FRONTEND_ARCHITECTURE.md # 前端架构文档
│   ├── QUICK_DEPLOY.md          # 快速部署
│   ├── dev_rules.md             # 开发规范
│   └── CODE_OPTIMIZATION_CHECKLIST.md  # 代码优化清单（历史存档）
│
├── tests/                       # 测试套件（pytest + Node.js）
│   ├── __init__.py              # 包标识
│   ├── conftest.py              # 共享 Mock fixtures + 数据工厂
│   ├── test_auth.py             # 认证模块（20 用例：Token/密码/滑动续期）
│   ├── test_memory_service.py   # SSE 引擎（33 用例：流式解析/状态标签）
│   ├── test_prompt_assembler.py # Prompt 组装（50 用例：Token预算/工具函数/World Info）
│   ├── test_model_adapter.py    # 模型适配器（22 用例：配置读取/payload构建）
│   ├── test_json_utils.py       # JSON 工具（19 用例：安全解析/序列化）
│   ├── test_card_text_utils.py  # 文本处理（48 用例：清洗/XML/模板/截断）
│   ├── test_character_state.py  # 角色状态（22 用例：好感度/三防/阶段推进）
│   └── test_frontend_utils.js   # 前端 JS（31 用例：SSE解析/XSS防护/日期格式化）
│
└── assets/                      # 静态资源（图片等）
```

---

## 4. 快速启动

### 前提条件

- Python 3.10+（项目用 3.14 开发，3.10+ 均可）
- 一个 Supabase 项目（免费套餐即可）
- MiniMax API Key（[minimaxi.com](https://www.minimaxi.com)）
- Resend API Key（用于密码重置邮件，[resend.com](https://resend.com)）

### Step 1：创建 Supabase 项目并建表

1. 去 [supabase.com](https://supabase.com) 创建项目
2. 在 SQL Editor 中执行 `docs/supabase_schema.sql`（一次性建好 17 张表）
3. 记下项目的 **Database URL**（在 Settings → Database → Connection string）

### Step 2：安装依赖

```bash
cd backend

# 创建虚拟环境（推荐，避免污染系统 Python）
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

依赖只有 7 个包，非常轻量：`fastapi`, `uvicorn`, `bcrypt`, `requests`, `psycopg2-binary`, `python-dotenv`, `python-multipart`。

### Step 3：配置环境变量

```bash
# 复制模板，填入真实配置
cp .env.example .env
# 编辑 .env，填写以下必要配置
```

`.env` 最小可运行配置：

```env
# 数据库（Supabase 连接字符串，必填）
DATABASE_URL=postgresql://postgres:[密码]@db.xxx.supabase.co:5432/postgres

# AI 模型（至少填一组通用配置）
AIFRIEND_API_KEY=sk-api-your-api-key-here
AIFRIEND_BASE_URL=https://api.minimaxi.com/v1
AIFRIEND_MODEL=MiniMax-M2.7

# 邮件服务（密码重置需要）
RESEND_API_KEY=re_your_resend_api_key_here

# 管理员邮箱（逗号分隔）
ADMIN_EMAILS=admin@example.com
```

可选：配置三套模型策略（不填则回退到通用配置）：

```env
# 游客 + 注册免费用户
AIFRIEND_BASIC_API_KEY=
AIFRIEND_BASIC_BASE_URL=
AIFRIEND_BASIC_MODEL=

# VIP
AIFRIEND_VIP_API_KEY=
AIFRIEND_VIP_BASE_URL=
AIFRIEND_VIP_MODEL=

# SVIP
AIFRIEND_SVIP_API_KEY=
AIFRIEND_SVIP_BASE_URL=
AIFRIEND_SVIP_MODEL=
```

### Step 4：启动后端

```bash
cd backend
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

首次启动会：
- 初始化 Supabase 连接池（`init_db_pool()`）
- 自动生成 `data/app_secret.txt`（Token 签名密钥）
- 验证生产环境配置（如 `ENV=production` 会严格检查）
- 启动订单清理后台任务

### Step 5：访问

| 地址 | 说明 |
|------|------|
| `http://127.0.0.1:8000` | 主 H5 应用（Lunar 品牌） |
| `http://127.0.0.1:8000/admin.html` | 后台管理界面 |
| `http://127.0.0.1:8000/api/health` | 健康检查 |

> **生产环境**：通过 OpenResty 反向代理 + Let's Encrypt SSL 证书访问：
> | 地址 | 说明 |
> |------|------|
> | `https://yourdomain.com` | 主应用（HTTP 自动跳转 HTTPS） |
> | `https://yourdomain.com/admin.html` | 后台管理界面 |
> | `https://yourdomain.com/api/*` | API 接口（Nginx 代理到 :8000） |

### Step 6：导入角色卡（首次需要）

```bash
cd backend
source .venv/bin/activate

# 查看可导入的角色卡
python cli/card_import.py --list

# 导入指定卡
python cli/card_import.py --path ../角色卡/xxx.png

# AI 自动分析并生成 subtitle/tags/opening_message
python cli/card_analyze.py --list
python cli/card_analyze.py --name 角色名
```

导入后去后台 `/admin.html` 编辑 `is_visible` 和 `home_priority`，让角色在广场显示。

---

## 5. API 路由一览

所有路由挂载在 `/api` 前缀下。

### 页面 serve

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 返回 index.html（主应用） |
| GET | `/admin.html` | 返回管理后台 |
| GET | `/forgot-password.html` | 返回密码重置页 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/avatar/{character_id}` | 获取角色头像 |
| GET | `/api/cover/{character_id}` | 获取角色封面 |
| POST | `/api/user/avatar` | 上传用户头像（JWT 认证，MIME 白名单 + 2MB 限制 + UUID 文件名） |
| GET | `/api/user/avatar` | 获取当前用户头像（返回图片或默认头像） |

### 静态文件挂载

| 路径 | 说明 |
|------|------|
| `/avatars` | 用户上传头像静态目录（StaticFiles） |

### 认证（Auth）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 邮箱注册 |
| POST | `/api/auth/login` | 邮箱登录 |
| GET | `/api/auth/me` | 获取当前登录用户信息 |
| POST | `/api/auth/logout` | 登出 |
| POST | `/api/auth/forgot-password` | 发送密码重置验证码 |
| POST | `/api/auth/verify-code` | 验证重置验证码 |
| POST | `/api/auth/reset-password` | 重置密码 |

> Token 格式：Bearer Token，放 `Authorization` header。服务端只存 token 的 SHA-256 哈希，默认 30 天过期（可通过 `TOKEN_EXPIRE_DAYS` 调整）。

### 角色（Characters）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/characters` | 获取可见角色列表（广场用） |
| GET | `/api/character/profile` | 获取角色详情（含用户备注） |
| POST | `/api/character/profile` | 更新用户对角色的备注 |
| GET | `/api/character/greetings` | 获取角色所有开场白（多剧情线） |
| GET | `/api/character/state` | 获取角色当前状态（好感度等） |
| POST | `/api/character/state/reset` | 重置角色状态 |

### 聊天（Chat）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/chat/guest-quota` | 查询游客剩余额度 |
| POST | `/api/chat/send` | 同步发送消息（非流式） |
| POST | `/api/chat/stream` | SSE 流式发送消息（打字机效果） |
| POST | `/api/chat/regenerate` | 重新生成 AI 回复（替换原内容，SSE 流式） |
| POST | `/api/chat/continue` | 继续生成（在原回复后追加新内容，SSE 流式，新气泡展示） |
| POST | `/api/chat/guest-stream` | 游客流式聊天（无需登录） |
| GET | `/api/chat/history` | 获取聊天历史记录 |
| POST | `/api/chat/clear` | 清空聊天记录（可指定 greeting_index 切换剧情线） |

### 会员 / 计费（Billing）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/billing/plans` | 获取当前可售卖的会员套餐 |
| POST | `/api/billing/orders` | 创建会员订单 |
| GET | `/api/billing/orders` | 获取当前用户订单列表 |
| GET | `/api/billing/orders/{order_no}` | 获取单个订单详情 |
| POST | `/api/billing/orders/{order_no}/cancel` | 取消待支付订单 |

### 管理（Admin）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/characters` | 管理端获取所有角色 |
| POST | `/api/admin/characters` | 新建角色 |
| GET | `/api/admin/character/{id}` | 获取角色详细信息 |
| DELETE | `/api/admin/character/{id}` | 删除角色 |
| POST | `/api/admin/character/{id}` | 更新角色字段 |
| GET | `/api/admin/character/{id}/config-summary` | 角色配置健康检查摘要 |
| GET | `/api/admin/character/{id}/message-preview` | Prompt 预览 |
| GET | `/api/admin/users` | 查看所有用户和会员档位 |
| POST | `/api/admin/users/{user_id}/plan` | 手动设置用户会员等级 |
| GET | `/api/admin/orders` | 查看最近会员订单 |

> 高级配置（记忆 / 分类 / 开场白 / 剧情线 / 后置规则 / 剧情事件）都挂在 `/api/admin/character/{id}/...` 下面，详见 `docs/backend_api.md`。

---

## 6. 核心模块详解

### backend/main.py

FastAPI 主入口，职责清晰：
- 创建应用、配置 CORS、注册路由
- 挂载静态文件（`/` → index.html，`/frontend/*` → 静态资源）
- 启动时初始化连接池、启动订单清理后台任务
- 健康检查端点 `/api/health`
- 角色头像/封面图片服务

### backend/database.py — 数据库连接

使用 psycopg2 连接池 + `ConnWrapper` 兼容层：

```
核心设计：业务代码从 SQLite 迁移过来后无需改动 SQL 语法。

ConnWrapper 包装 psycopg2 原始连接：
  - 提供 SQLite 风格的 .execute() / .commit() / .rollback() / .close()
  - 查询结果自动使用 RealDictCursor，支持 row["column_name"] 字典访问
  - .close() 实际是把连接归还连接池，不是真关闭
```

使用方式：

```python
conn = get_conn()
try:
    row = conn.execute("SELECT * FROM users WHERE id = %s", (1,)).fetchone()
    conn.commit()
finally:
    conn.close()

# 或者用 with 语句自动管理
with get_db() as conn:
    conn.execute("INSERT ...")
```

### backend/prompt_assembler.py — Prompt 编排

Prompt 分层组装引擎 + Token 预算系统：

```
最终发给 AI 的消息结构：
[system × 1（合并所有设定）]
  ├── 主 System Prompt（角色扮演规则 + 输出格式要求）
  ├── World Info before（关键词命中的词条）
  ├── 角色底稿（description）
  ├── 性格（personality）
  ├── 场景（scenario）
  ├── 示例对话（mes_example）
  └── World Info after
[assistant（长期记忆摘要）]
[历史消息（最近 N 条，贪心填充）]
[user（post_history 提醒）]
[最新用户消息]
```

**Token 预算分配**（`TokenBudget` 类）：
- 换算比：1600中文字 ≈ 1000 token
- 总预算 64K context，保留 2048 给输出
- system 55% / 历史 30% / 记忆 8% / World Info 25%

### backend/model_adapter.py — AI 模型适配

兼容 OpenAI Chat Completions 格式接口：

```python
get_ai_config(env, profile)        # 读取 basic/vip/svip 三套模型配置
request_chat_completion(config, messages)   # 同步调用
stream_chat_completion(config, messages)    # 流式调用（yield chunks）
```

三套模型策略会根据用户当前档位（effective_plan）自动选择，未配置则回退到通用 `AIFRIEND_*`。

### backend/services/ — 业务逻辑层

| 文件 | 职责 |
|------|------|
| `chat_service.py` | 聊天核心：上下文准备、开场白选择、回复保存、STATE_UPDATE 标签解析 |
| `memory_service.py` | 长期记忆：摘要生成（24条消息触发）、消息整理、结构化摘要（用户画像/偏好/事件/关系/待跟进） |
| `character_state.py` | 好感度系统：三防机制（CD/日上限/递减）、19种基础事件、阶段自动推进 |
| `usage_guard.py` | 成本防护：token 预估、日限额检查（按 free/vip/svip/guest 四档）、请求日志 |
| `plan_service.py` | 会员计划：档位计算、过期检查 |
| `rate_limit.py` | 限流：登录/注册/聊天/游客 分别限制 |
| `cache_service.py` | 缓存：角色配置等热点数据缓存 |
| `db_monitor.py` | 数据库监控：连接池状态、慢查询 |
| `email.py` | 邮件发送：Resend API，密码重置验证码 |

### backend/routers/ — API 路由层

路由层只负责参数校验和调用 services，不包含业务逻辑。所有管理后台路由额外校验管理员身份（`ADMIN_EMAILS` 白名单）。

---

## 7. 数据库 Schema

数据库：**Supabase (PostgreSQL)**，建表 SQL 在 `docs/supabase_schema.sql`。

共 **17 张表**，按功能分为 6 组：

### 用户相关（3张）

| 表 | 说明 |
|----|------|
| `users` | 用户主表（邮箱、密码、会员档位、过期时间） |
| `auth_tokens` | 登录 Token（SHA-256 哈希存储） |
| `password_reset_codes` | 密码重置验证码 |

### 角色相关（1张）

| 表 | 说明 |
|----|------|
| `characters` | 角色主表（名称、描述、标签、system_prompt、card_type、required_plan 等 20+ 字段） |

### 聊天相关（2张）

| 表 | 说明 |
|----|------|
| `chat_messages` | 聊天记录（用户/助手/系统消息，含摘要标记） |
| `chat_summaries` | 聊天摘要（每用户每角色一条，含 memory_version） |

### 关系状态（2张）

| 表 | 说明 |
|----|------|
| `user_character_profiles` | 用户对角色的备注/签名 |
| `character_states` | 好感度/阶段/心情/自定义变量 + 三防计数器 |

### 会员相关（2张）

| 表 | 说明 |
|----|------|
| `membership_orders` | 会员订单（pending/paid/cancelled/expired） |
| `ai_request_logs` | AI 请求日志（成本监控、用量统计） |

### 角色高级配置（6张）

| 表 | 说明 |
|----|------|
| `memory_categories` | 记忆分类标签（如"日常"、"秘密"） |
| `character_memories` | 关键词触发的记忆条目（World Info） |
| `character_storylines` | 剧情线（多剧情线玩法） |
| `character_greetings` | 多阶段开场白（stranger/acquaintance/friend/lover） |
| `character_post_rules` | 后置规则（AI 回复约束） |
| `story_events` | 剧情事件（好感度解锁） |
| `user_story_progress` | 用户剧情进度（已触发事件、当前剧情线） |

---

## 8. 角色卡系统

### 卡片格式

使用 **SillyTavern 兼容 PNG 格式**：
- PNG 文件的 `tEXt` chunk 里嵌入 base64 编码的 JSON
- JSON 结构遵循 [TavernAI V2 卡片规范](https://github.com/malfoyslastname/character-card-spec-v2)
- 主要字段：`name` / `description` / `personality` / `scenario` / `first_mes` / `alternate_greetings` / `mes_example` / `character_book`

### 卡片类型（card_type）

| 类型 | 说明 | 适用场景 |
|------|------|---------|
| `intimate` | 亲密陪伴型（主要） | 日常聊天、恋爱模拟 |
| `scenario` | 剧情沙盒型 | 多剧情线互动 |
| `world` | 世界书型 | 世界观探索 |
| `divination` | 占卜型 | 轻量互动 |

### 导入流程

```
PNG 文件
  ↓ cli/card_import.py（解析 PNG + 写入 Supabase，import_locked=0）
  ↓ cli/card_analyze.py（AI 分析，生成 subtitle/tags/opening_message，import_locked=1）
  ↓ 人工复核（admin.html 编辑 is_visible/home_priority/required_plan）
  ↓ 在广场显示
```

### World Info（character_book / character_memories）

PNG 卡内的 `character_book` 和后台管理的 `character_memories` 都是关键词触发系统：
- `constant=true` 或 `is_active=1`：每轮都注入
- `constant=false`：关键词命中才注入（支持 any/all 两种逻辑）
- `position`：`before`（system 最前）或 `after`（system 最后）
- 后台管理的 `character_memories` 支持分类、优先级、剧情线关联

---

## 9. Prompt 分层架构

### MiniMax 单-system 兼容方案

MiniMax 要求 system 消息只有一条，所以所有设定层合并为一条 system：

```
[system × 1]
  = 主 Prompt（角色扮演规则 + 输出格式要求）
  + World Info before（关键词命中词条）
  + 角色描述（description）
  + 性格（personality）
  + 场景（scenario）
  + 世界规则补充
  + 示例对话（mes_example）
  + World Info after

[assistant]  ← 长期记忆摘要（结构化：用户画像/偏好/近期事件/关系状态/待跟进）

[历史消息]   ← 最近 N 条，贪心填充 Token 预算

[user]       ← post_history 提醒（如输出格式要求）

[最新用户消息]
```

### Token 预算（TokenBudget 类）

```
context_size = 64000        # 模型 context 窗口
output_reserve = 2048       # 保留给 AI 回复
available = ~61952 tokens

system_budget    = 55%  # ~34K tokens（含 World Info 25% 叠加）
history_budget   = 30%  # ~18K tokens
memory_budget    = 8%   # ~5K tokens

换算比：1600 中文字 ≈ 1000 token
```

---

## 10. 好感度 / 状态系统

详见 `docs/AFFECTION_SYSTEM.md`。

### 核心机制

AI 每次回复末尾输出 `[STATE_UPDATE]` 标签（只给 AI 看，不展示给用户）：

```
[STATE_UPDATE]
events: ["DEEP_CONVERSATION", "RECEIVED_COMPLIMENT"]
mood: 开心
[/STATE_UPDATE]
```

后端解析事件名，查规则表计算好感度变化：
- **全局基础规则**：19 种通用事件（普通对话/深度交流/称赞/冲突等）
- **角色自定义规则**：可覆盖全局规则（存于 `affection_rules_json`）
- **三防机制**：Cooldown（CD 冷却）/ Daily Cap（每日上限 15 点）/ Diminishing Returns（递减效益 [1.0, 0.6, 0.3, 0.0]）
- **阶段系数**：好感度高时涨得慢跌得快（lover 阶段：涨 x0.4 / 跌 x1.5）

### 好感度阶段

| 阶段 | 区间 | 说明 | 解锁内容 |
|------|------|------|---------|
| stranger | 0~20 | 陌生人 | 基础对话 |
| acquaintance | 20~40 | 普通朋友 | 更多个人话题 |
| friend | 40~70 | 亲密朋友 | 深度交流、特殊事件 |
| lover | 70~100 | 恋人 | 恋人专属开场白、隐藏剧情线 |

### 剧情事件系统

通过 `story_events` 表配置好感度阈值事件：
- 当用户好感度达到 `trigger_score` 时触发
- 可解锁：记忆条目、专属开场白、新剧情线
- `user_story_progress` 表追踪每个用户的触发进度

---

## 11. 前端页面结构

IIFE 模块化 SPA（`index.html` + `frontend/modules/` 共 11 个模块），无框架，原生 JS。

### 模块架构

```
index.html（入口）
  └── 按 IIFE 依赖顺序加载 11 个 <script> 标签：
      1. ui.js          → UI 基础组件（无依赖）
      2. config.js      → 配置常量（无依赖）
      3. utils.js       → 工具函数（无依赖）
      4. api.js         → API 封装（依赖 config.js）
      5. app.js         → 应用主逻辑（依赖 api.js, utils.js, ui.js）
      6. auth.js        → 认证逻辑（依赖 api.js, ui.js）
      7. chat.js        → 聊天核心（依赖 api.js, ui.js, auth.js）← 最大模块
      8. chat-menu.js   → 聊天菜单（依赖 chat.js）
      9. char-detail.js → 角色详情（依赖 api.js）
     10. greeting-select.js → 开场白选择（依赖 api.js, ui.js）
     11. init.js        → 初始化入口（依赖以上所有，最后执行启动逻辑）
```

每个模块通过 IIFE（立即执行函数表达式）暴露全局对象（如 `window.Chat`、`window.API`、`window.Auth`），模块间通过全局对象通信。

### 页面（section）

| ID | 说明 |
|----|------|
| `#page-home` | 首页（主视觉文案 + 产品卖点） |
| `#page-square` | 角色广场（按 card_type 分区展示） |
| `#page-chat` | 聊天页（打字机流式输出、状态栏、好感度进度条、regenerate/continue 按钮） |
| `#page-mine` | 我的（登录状态、试聊说明、长期记忆说明） |

### 聊天核心功能（chat.js）

- **SSE 流式聊天**：POST `/api/chat/stream`，chunk-by-chunk 实时渲染
- **重新生成（Regenerate）**：点击 ↻ 按钮 → 按钮转圈 loading → SSE 流式替换原气泡内容
- **继续生成（Continue）**：点击 ▶ 按钮 → typing 指示器 → 在原气泡下方新建气泡展示追加内容
- **智能滚动**：流式输出时用户上滑查看历史自动暂停跟滚，回底 120px 内自动恢复
- **并发控制**：`isSending` 标志位防止重复提交，操作中禁用按钮
- **统一 DOM 结构**：所有 AI 消息使用 `.msg-body` 垂直容器包裹，按钮位置固定在气泡左下角

### 游客模式

- 未登录用户可直接走游客聊天（POST `/api/chat/guest-stream`）
- 聊天页顶部显示"游客体验额度"提示
- 额度用完后引导登录/注册继续聊天

### 管理后台（frontend/admin/）

基于原生 JS 的单文件后台，支持：
- 角色基础信息编辑
- 高级配置：记忆/分类/开场白/剧情线/后置规则/剧情事件
- Prompt 预览（查看 AI 实际收到的内容）
- 用户管理、会员档位手动调整
- 订单管理、审计日志

---

## 12. 环境变量配置

完整配置参考 `backend/.env.example`，以下是按重要性分组的说明：

### 必填配置

```env
# 数据库（Supabase PostgreSQL 连接字符串）
DATABASE_URL=postgresql://postgres:[密码]@db.xxx.supabase.co:5432/postgres

# AI 模型通用兜底配置（至少填这一组）
AIFRIEND_API_KEY=sk-api-your-api-key-here
AIFRIEND_BASE_URL=https://api.minimaxi.com/v1
AIFRIEND_MODEL=MiniMax-M2.7

# 邮件服务（密码重置）
RESEND_API_KEY=re_your_resend_api_key_here

# 管理员邮箱（逗号分隔）
ADMIN_EMAILS=admin@example.com
```

### CORS 与安全

```env
ENV=production
DEBUG=false
ALLOWED_ORIGINS=https://yourdomain.com
TOKEN_EXPIRE_DAYS=30
```

### 会员与额度

```env
FREE_DAILY_TOKEN_LIMIT=180000
GUEST_DAILY_TOKEN_LIMIT=40000
VIP_DAILY_TOKEN_LIMIT=450000
SVIP_DAILY_TOKEN_LIMIT=900000
AI_CHAT_MAX_OUTPUT_TOKENS=768

VIP_PLAN_PRICE_CENTS=2990
SVIP_PLAN_PRICE_CENTS=5990
VIP_PLAN_DURATION_DAYS=30
SVIP_PLAN_DURATION_DAYS=30
```

### 三套模型策略（可选）

不填则自动回退到通用 `AIFRIEND_*` 配置：

```env
AIFRIEND_BASIC_API_KEY=
AIFRIEND_BASIC_BASE_URL=
AIFRIEND_BASIC_MODEL=

AIFRIEND_VIP_API_KEY=
AIFRIEND_VIP_BASE_URL=
AIFRIEND_VIP_MODEL=

AIFRIEND_SVIP_API_KEY=
AIFRIEND_SVIP_BASE_URL=
AIFRIEND_SVIP_MODEL=
```

---

## 13. 部署上线

详细的部署教程见 `docs/DEPLOYMENT_GUIDE_VPS.md`。

### 快速部署流程

```bash
# 1. 打包部署文件
bash deploy.sh

# 2. 上传到服务器
scp aifriend_deploy_xxx.tar.gz root@your-server:/root/

# 3. 服务器上解压
tar -xzf aifriend_deploy_xxx.tar.gz
cd aifriend_deploy_xxx

# 4. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 .env，填入 Supabase URL、API Key 等

# 5. 安装依赖并启动
cd backend
pip install -r requirements.txt

# 方式 A：直接启动（开发用）
uvicorn main:app --host 0.0.0.0 --port 8000

# 方式 B：systemd 服务（生产推荐，见下方说明）
```

### 部署清单

上线前逐项检查（详见 `docs/DEPLOYMENT_CHECKLIST.md`）：

- [ ] Supabase 数据库已建表（`docs/supabase_schema.sql`）
- [ ] `.env` 中 `DATABASE_URL` 已正确配置
- [ ] `.env` 中 `AIFRIEND_API_KEY` 已设置
- [ ] `.env` 中 `RESEND_API_KEY` 已设置
- [ ] `.env` 中 `ALLOWED_ORIGINS` 已改为真实域名
- [ ] `.env` 中 `ADMIN_EMAILS` 已设置
- [ ] `ENV=production` 且 `DEBUG=false`
- [ ] **HTTPS/SSL 证书已配置**（Let's Encrypt + certbot）
- [ ] **systemd 服务已创建并设为开机自启**
- [ ] 数据库备份计划已设置（`backend/backup_supabase.sh` + cron）

### 生产环境 systemd 服务

```bash
# 创建服务文件 /etc/systemd/system/aifriend.service：
[Unit]
Description=AIFriend Backend (Uvicorn)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/aifriend_deploy_xxx/backend
ExecStart=/opt/aifriend_deploy_xxx/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=ENV=production

[Install]
WantedBy=multi-user.target

# 启用服务
systemctl daemon-reload && systemctl enable aifriend && systemctl start aifriend
```

### HTTPS 配置要点（OpenResty Docker 环境）

1. **SSL 证书**：Let's Encrypt 免费证书，需复制到 OpenResty 容器可访问的路径（如 `/www/ssl/`）
2. **HTTP→HTTPS 跳转**：Nginx `return 301 https://$host$request_uri`
3. **ACME 挑战**：`.well-known/acme-challenge/` 必须在安全规则之前放行
4. **WAF 注意**：1Panel OpenResty 内置 WAF 可能导致 500 错误，确认 WAF 文件存在或注释掉
5. **Docker 卷挂载**：容器内只能看到 docker-compose.yml 声明的卷目录
6. **SSE 流式输出**：`/api` location 必须设置 `proxy_buffering off; proxy_cache off;`
7. **图片缓存**：静态图片资源（png/jpg/webp 等）设置 30 天长期缓存 + `Cache-Control: public, immutable`
8. **头像预加载**：前端在角色列表渲染后通过 `new Image()` 预加载所有头像到浏览器缓存

### 数据库备份

```bash
# 手动备份
bash backend/backup_supabase.sh

# 建议设置 cron 自动备份（每天凌晨）
# crontab -e
# 0 3 * * * /path/to/backend/backup_supabase.sh >> /path/to/logs/backup.log 2>&1
```

详见 `docs/DATABASE_BACKUP_GUIDE.md`。

---

## 14. 开发规范与维护原则

### 给代码小白接手的硬规则

如果你后面是"自己盯线上 + 主要靠 AI 帮你改代码"，把下面当成最高优先级：

#### 1. 先稳定，再加功能

新功能只有满足这 5 条才值得保留：
1. 出问题时容易关掉（独立开关/配置）
2. 接口含义清楚（一看就懂）
3. 有兜底逻辑（挂了不影响主流程）
4. 管理后台可解释（人也能看懂）
5. 不引入额外部署复杂度

#### 2. 小步修改，不要一口气动 6 个文件

- 一次只改一个目标
- 改动集中在 1~2 个文件
- 先改文档再改逻辑
- 改完做最小自检：后端能启动 → 前台能进首页 → 能选角色 → 能发消息 → 后台能保存

#### 3. 必须保住的 6 条主链路

1. 后端能启动
2. 登录能成功
3. 角色列表能拉到
4. 聊天能正常发出并收到回复
5. 聊天记录不会丢失
6. 管理后台能编辑角色

#### 4. 出 bug 按这个顺序排查

```
第一步：lsof -nP -iTCP:8000 -sTCP:LISTEN（服务活着没？）
第二步：打开 /api/health（健康检查过没？）
第三步：判断前端还是后端问题（首页打不开→后端；列表空白→API；发不出去→chat）
第四步：回退到最近可用状态（不要硬修，先回退）
```

#### 5. 改数据库前一定先备份

```bash
# Supabase 备份
bash backend/backup_supabase.sh
```

#### 6. 长期策略：少功能、强说明、可回退

功能数量适中，每个功能都写清楚用途，管理后台说人话，每次改动都能快速回退，文档和代码保持同步。

> **给 AI 的持续要求**：优先保证易维护、低耦合、可回退、出错有兜底，不要为了炫技增加复杂度。

### 开发约定

1. **后端绑定 `0.0.0.0`**：`uvicorn main:app --host 0.0.0.0 --port 8000`
2. **不自动导卡**：系统启动不扫描目录，手动用 `cli/card_import.py` 导
3. **import_locked**：`cli/card_analyze.py` 分析后锁定，防止重启覆盖展示字段
4. **版本号**：`index.html` 里前端资源版本号每次改前端文件时更新
5. **SQL 占位符**：使用 `%s`（PostgreSQL 风格），不是 `?`（SQLite 风格）
6. **时间格式**：统一使用 UTC ISO 字符串存储

### 已完成的稳定性改造

- 密码使用 **bcrypt** 哈希，旧 SHA-256 用户登录后自动升级
- 登录 Token 支持 **过期时间**（默认 30 天）
- 登录 / 聊天 / 游客试聊已加 **基础限流**（轻量内存版）
- **P0 成本防护**：每日 token 预算 + 单次输出上限 + 请求消耗日志
- 数据库从 **SQLite 迁移到 Supabase**，支持多设备同步
- 生产环境配置 **强制校验**，缺关键配置拒绝启动
- 前端从单文件 `app.js`（~1957行）**重构为 11 个 IIFE 模块**，职责清晰分离
- 新增 **Regenerate（重新生成）+ Continue（继续生成）** 聊天增强功能，SSE 流式交互
- Regenerate/Continue 后端使用 **时间排序**（`ORDER BY created_at ASC`）解决 UUID v4 上下文错乱问题
- 新增 **用户头像系统**：上传/更换/展示（POST+GET /api/user/avatar，MIME 白名单、2MB 限制、UUID 文件名）
- 聊天消息新增 **角色/用户头像**显示（36px 正方形，微信风格对齐）
- 聊天消息新增 **智能时间戳**（>5 分钟间隔才显示，支持 HH:mm / 昨天 / 日期格式）
- chat.py 提取 `_stream_ai_completion()` 公共函数，消除 4 处 SSE 重复代码
- auth.js bootstrap 改为**仅认证失败时清登录态**，避免网络抖动导致误退出
- **P1-A**: 头像上传自动清理旧文件（防 avatars/ 目录膨胀）
- **P1-B**: SSE 流式响应超时控制（120 秒，防 AI 提供商挂起）
- **P1-C**: Token 滑动续期（剩余 <7 天自动延长，活跃用户不因过期被踢出登录）
- **P1-D**: `admin.py`（2936 行）拆分为 `routers/admin/` 包（4 子模块 + 共享模块）
- **P2-1**: SSE 连接切换自动 abort 旧连接（`_streamController` + `abortStream()`，4 处流式 API 全覆盖）
- **P2-2**: fetch 请求添加 AbortController 超时控制（`api.js request()` 20s 默认超时 + 友好错误提示）
- **P2-3**: 大量消息渲染性能优化（`chat.js renderHistory()` DocumentFragment 批量渲染，N 条消息仅 1 次 reflow）
- **P3-1**: `auth.py` CurrentUser 类补全 `avatar_url` 字段，修复 `/api/auth/me` 500 错误
- **P3-2**: `main.py` 头像/封面接口修复 `get_db()` 上下文管理器用法（`with get_db() as conn:`）
- **生产部署**: HTTPS 配置（Let's Encrypt + OpenResty）、systemd 开机自启、WAF 问题排查与绕过
- **P3-3**: 聊天 UI 按钮位置重构：新增 `.msg-body` 垂直容器，统一 AI 消息 DOM 结构，Regenerate/Continue 按钮固定在气泡左下角
- **P3-4**: 智能滚动：流式输出时用户上滑查看历史自动暂停跟滚，回底后恢复（120px 阈值检测）
- **P3-5**: 角色头像预加载：首页加载角色列表后立即后台预加载所有头像/封面到浏览器缓存（`new Image()`），消除进入聊天页的加载延迟
- **P3-6**: Nginx 图片长期缓存：头像/封面等静态图片资源设置 30 天缓存（`Cache-Control: public, immutable`），减少重复请求

### 单元测试套件

项目已建立完整的单元测试体系，覆盖核心业务逻辑：

| 维度 | 数据 |
|------|------|
| **测试框架** | Python pytest + Node.js 原生 assert |
| **Python 用例** | 234 个（8 个测试文件） |
| **JavaScript 用例** | 31 个（1 个测试文件） |
| **总计** | **265 个用例，100% 通过率** |
| **执行时间** | Python ~2s + JS <0.1s |
| **覆盖模块** | auth / memory_service / prompt_assembler / model_adapter / json_utils / card_text_utils / character_state / utils.js / api.js SSE |

```bash
# 运行全部 Python 测试
cd backend && source venv/bin/activate && python -m pytest tests/ -v

# 运行前端 JS 测试
node tests/test_frontend_utils.js

# 带覆盖率报告
python -m pytest tests/ --cov=backend --cov-report=term-missing
```

**运行命令**：

---

*文档更新时间：2026-04-03（全面审查：新增 P3-3~P3-6 聊天UI重构/智能滚动/头像预加载/Nginx图片缓存）*
