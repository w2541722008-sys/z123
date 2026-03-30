# aifriend — 女性向 AI 男友 H5 聊天应用

> **给接手 AI 的一句话**：这是一个面向女性向音频粉丝的 AI 角色扮演聊天 H5 应用，主打沉浸感和长期记忆。后端 Python FastAPI + SQLite，前端纯原生 HTML/JS，通过 SillyTavern 兼容的 PNG 角色卡驱动 AI 角色。

---

## 先用大白话理解这个项目

如果你现在对项目还不熟，可以先把它理解成下面 5 句话：

1. **前台就是一个聊天网页**：用户在 `index.html + frontend/app.js` 里选角色、聊天、登录、看历史。
2. **后台就是一个角色配置台**：你在 `admin.html` 里改角色资料、开场白、记忆、剧情线、事件和后置规则。
3. **后端像“总调度”**：FastAPI 负责收消息、查数据库、拼 Prompt、调模型、保存聊天记录。
4. **数据库像“长期存档”**：SQLite 保存角色、用户、聊天记录、关系状态、长期记忆摘要。
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
13. [当前在库角色](#13-当前在库角色)
14. [后台配置怎么填](#14-后台配置怎么填给不熟悉项目的人)
15. [已知待办和安全注意事项](#15-已知待办和安全注意事项)
16. [维护优先原则（给代码小白接手）](#16-维护优先原则给代码小白接手)

---

## 1. 项目定位

| 维度 | 说明 |
|------|------|
| **目标用户** | 女性向音频 / 二次元粉丝（B站、云do圈子用户） |
| **核心功能** | AI 角色扮演聊天、长期记忆、多条剧情线、好感度系统 |
| **定位** | 正式产品，非玩具原型。代码简洁优雅、模块清晰，借鉴 SillyTavern 设计思路 |
| **当前阶段** | MVP，本地可跑，支持手机端访问（ngrok 穿透） |

---

## 2. 技术架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                       用户（浏览器/手机）                      │
│           访问 http://127.0.0.1:8000  或  ngrok URL          │
└─────────────────────┬───────────────────────────────────────┘
                      │  HTTP / SSE 流式
┌─────────────────────▼───────────────────────────────────────┐
│                  FastAPI 后端 (Python 3.x)                   │
│  端口 8000，host 0.0.0.0                                     │
│                                                             │
│  ┌─────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ main.py │  │prompt_assembler│  │  model_adapter.py   │   │
│  │ 路由/鉴权│  │  Prompt分层  │  │  AI API 适配层       │   │
│  └─────────┘  └──────────────┘  └──────────────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           SQLite  backend/data/aifriend.db           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  静态文件 serve（GET /  GET /admin.html  /frontend/*）       │
└─────────────────────────────────────────────────────────────┘

前端文件位置（由后端直接 serve）：
  aifriend/index.html        ← 主 H5 应用入口
  aifriend/admin.html        ← 后台管理（角色卡管理）
  aifriend/frontend/app.js   ← 所有前端逻辑（原生 JS）
  aifriend/frontend/style.css ← 全局样式（深色毛玻璃风格）

AI 接口：
  MiniMax M2.5（国内版 minimaxi.com）
  接口兼容 OpenAI Chat Completions 格式
  支持 SSE 流式输出
```

---

## 3. 目录结构

```
aifriend/
├── index.html              # H5 主应用入口（SPA，含4个页面 section）
├── admin.html              # 后台角色卡管理界面
├── generate_avatars.py     # 可选工具：批量生成测试头像，不参与主聊天链路
│
├── frontend/
│   ├── app.js              # 全部前端逻辑（原生 JS，无框架）
│   └── style.css           # 全局样式（深色毛玻璃，CSS 变量系统）
│
├── backend/
│   ├── main.py             # FastAPI 主程序（挂载路由、静态文件、媒体访问）
│   ├── prompt_assembler.py # Prompt 分层组装 + Token 预算系统
│   ├── model_adapter.py    # AI API 调用封装（支持 sync/stream 两种模式）
│   ├── card_asset_parser.py # PNG 角色卡解析（读取 SillyTavern 嵌入 JSON）
│   ├── card_import.py      # 手动导卡工具（CLI，支持 --list/--path/--dry-run）
│   ├── card_analyze.py     # AI 分析工具（自动生成 subtitle/tags/opening_message）
│   ├── card_feature_mapper.py # 卡片特征映射（card_type 路由）
│   ├── card_text_utils.py  # 文本处理工具函数
│   ├── requirements.txt    # 依赖：fastapi==0.116.1 uvicorn==0.35.0
│   ├── .env                # 环境变量（API Key，不在 git 里）
│   ├── .env.example        # 环境变量模板
│   ├── AFFECTION_SYSTEM.md # 好感度系统设计文档
│   └── data/
│       ├── aifriend.db     # 实际 SQLite 数据库（角色卡+用户+聊天记录）
│       └── app_secret.txt  # Token 签名密钥（首次启动自动生成）
│
├── 角色卡/                 # SillyTavern 格式 PNG 角色卡（包含嵌入 JSON）
│   ├── 85e1ec18737cb1e8.png  # 高凌枫（在库，intimate）
│   ├── 2.png                  # 路少晖（在库，scenario）
│   ├── c03daced8f60c6c5.png  # 姜禾（在库，intimate）
│   ├── fbc1d38e68bbe4d3.png  # 陆清商（在库，intimate）
│   ├── db61100778f10e10.png  # 白邬（在库，intimate）
│   └── 陈序.png               # 陈序（在库，intimate，不在主广场）
│
└── docs/
    ├── backend_api.md          # 后端 API 文档
    ├── CHARACTER_IMPORT_SOP.md # 角色卡导入标准流程
    └── supabase_schema.sql     # 上线用 Supabase schema（备用）
```

---

## 4. 快速启动

### 前提条件

- Python 3.10+（项目用 3.14 开发，3.10+ 均可）
- 有 MiniMax API Key（国内版 [minimaxi.com](https://www.minimaxi.com)）

### Step 1：安装依赖

```bash
cd /Users/jjj/aifriend/backend

# 创建虚拟环境（推荐，避免污染系统 Python）
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖（只有两个包）
pip install -r requirements.txt
```

### Step 2：配置环境变量

```bash
# 复制模板，填入真实 API Key
cp backend/.env.example backend/.env
# 编辑 .env，填写 AIFRIEND_API_KEY
```

`.env` 内容格式：
```
AIFRIEND_API_KEY=your_minimax_api_key_here
AIFRIEND_BASE_URL=https://api.minimaxi.com/v1
AIFRIEND_MODEL=MiniMax-M2.5
```

如果后面要做分档会员，推荐直接改成三套模型配置：

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

如果这三组不填，系统会自动回退到最上面的 `AIFRIEND_API_KEY / AIFRIEND_BASE_URL / AIFRIEND_MODEL` 通用配置。

### Step 3：启动后端

```bash
cd /Users/jjj/aifriend/backend
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

首次启动会自动：
- 建表（`init_db()`）
- 创建 `app_secret.txt`（Token 签名密钥）
- 不会自动导角色卡（需手动用 card_import.py）

### Step 4：访问

| 地址 | 说明 |
|------|------|
| `http://127.0.0.1:8000` | 主 H5 应用 |
| `http://127.0.0.1:8000/admin.html` | 后台管理界面 |
| `http://127.0.0.1:8000/api/health` | 健康检查 |

### Step 5：手机测试（可选）

```bash
# 另开终端，启动 ngrok 穿透
ngrok http 8000
# 复制 ngrok 给出的 https://xxx.ngrok-free.dev 地址，手机直接访问
```

### 导入角色卡（首次需要）

```bash
cd /Users/jjj/aifriend/backend
source .venv/bin/activate

# 查看可导入的角色卡
python card_import.py --list

# 导入指定卡
python card_import.py --path ../角色卡/85e1ec18737cb1e8.png

# AI 自动分析并生成 subtitle/tags/opening_message
python card_analyze.py --list
python card_analyze.py --name 高凌枫
```

---

## 5. API 路由一览

### 页面 serve
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 返回 index.html（主应用） |
| GET | `/admin.html` | 返回 admin.html（后台） |
| GET | `/api/health` | 健康检查 |

### 鉴权（Auth）
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
| GET | `/api/avatar/{character_id}` | 获取角色头像 PNG |
| GET | `/api/character/profile` | 获取角色详情（含用户备注） |
| POST | `/api/character/profile` | 更新用户对角色的备注 |
| GET | `/api/character/greetings` | 获取角色所有开场白（多剧情线） |
| GET | `/api/character/state` | 获取角色当前状态（好感度等） |
| POST | `/api/character/state/reset` | 重置角色状态 |

### 聊天（Chat）
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/send` | 同步发送消息（非流式） |
| POST | `/api/chat/stream` | SSE 流式发送消息（打字机效果） |
| POST | `/api/chat/guest-stream` | 游客流式聊天（体验额度内，无需登录） |
| GET | `/api/chat/history` | 获取聊天历史记录 |
| POST | `/api/chat/clear` | 清空聊天记录（可指定 greeting_index 切换剧情线） |

### 会员 / 支付预留（Billing）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/billing/plans` | 获取当前可售卖的会员套餐 |
| POST | `/api/billing/orders` | 创建会员订单预留记录 |
| GET | `/api/billing/orders` | 获取当前用户自己的订单列表 |
| GET | `/api/billing/orders/{order_no}` | 获取单个订单详情 |

### 管理（Admin）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/characters` | 管理端获取所有角色 |
| POST | `/api/admin/characters` | 新建角色 |
| GET | `/api/admin/character/{id}` | 获取角色详细信息 |
| DELETE | `/api/admin/character/{id}` | 删除角色 |
| POST | `/api/admin/character/{id}` | 更新角色字段 |
| GET | `/api/admin/character/{id}/config-summary` | 角色配置健康检查摘要 |
| GET | `/api/admin/character/{id}/message-preview` | 管理后台 Prompt 预览 |
| GET | `/api/admin/users` | 查看所有用户和会员档位 |
| POST | `/api/admin/users/{user_id}/plan` | 手动设置用户会员等级 |
| GET | `/api/admin/orders` | 查看最近会员订单 |

> 高级配置（记忆 / 分类 / 开场白 / 剧情线 / 后置规则 / 剧情事件）都挂在 `/api/admin/character/{id}/...` 下面。

### 调试（Debug，⚠️ 上线前删除）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/debug/card` | 查看角色卡原始 JSON |
| GET | `/api/debug/cards` | 列出所有角色卡 |
| GET | `/api/debug/message-preview` | 预览实际发给 AI 的消息结构 |

---

## 6. 核心模块详解

### backend/main.py

FastAPI 主程序，包含：
- **DB 初始化** `init_db()`：建表、字段迁移（UPSERT 安全）
- **Token 鉴权**：`create_token()` / `get_current_user()`，随机 Bearer Token + SHA-256 哈希存储 + 过期时间校验
- **角色系统**：`/api/characters` 返回带类型分区的角色列表
- **聊天核心**：`event_generator()` SSE 流，调用 `build_layered_chat_messages()` 组装 prompt，调用 `stream_chat_completion()` 获取流式响应
- **好感度解析**：AI 回复末尾 `[STATE_UPDATE]` 标签解析，更新 `character_states` 表
- **前端 serve**：`GET /` 和 `GET /admin.html` 直接返回 HTML 文件，`/frontend/*` 挂载 StaticFiles

### backend/prompt_assembler.py

Prompt 分层组装引擎：

```
最终发给 AI 的消息结构：
[system × 1（合并所有设定）]
  └── 主 System Prompt
  └── 角色底稿（card description/personality）
  └── 性格/场景/世界规则
  └── World Info before（关键词命中的词条）
  └── 示例对话
  └── World Info after
[assistant（长期记忆摘要）]
[历史消息（最近 N 条，含 depth_prompt 插入）]
[user（post_history 提醒）]
[最新用户消息]
```

**Token 预算系统**（`TokenBudget` 类）：
- 换算比：1600字 ≈ 1000 token
- 总预算 64K context，保留 2048
- 分层：system 55% / 历史 30% / 记忆 8% / World Info 25%
- 历史消息贪心填充（从新到旧）

### backend/model_adapter.py

AI API 适配层，兼容 OpenAI 格式接口：
```python
get_ai_config()          # 从环境变量读取 API Key/URL/Model
request_chat_completion()  # 同步调用
stream_chat_completion()   # 流式调用（yield chunks）
```

支持任何 OpenAI Chat Completions 兼容接口（MiniMax / OpenAI / DeepSeek 等）。

### backend/card_asset_parser.py（44KB）

PNG 角色卡解析器，读取 SillyTavern 格式嵌入数据：
- 解析 PNG tEXt chunk 中的 `chara` 字段（base64 + JSON）
- 提取 `name` / `description` / `personality` / `scenario` / `first_mes` / `mes_example` / `character_book`（world info）等标准字段
- `character_book` 词条按 `constant` / `insertion_order` / `position` 分流注入

### backend/card_import.py（CLI 工具）

```bash
python card_import.py --list                   # 列出角色卡目录里的所有 PNG
python card_import.py --path ../角色卡/xx.png  # 导入指定卡（import_locked=0）
python card_import.py --dry-run --path xxx.png  # 试跑不写库
```

### backend/card_analyze.py（CLI 工具）

调用 AI 分析角色卡 raw JSON，自动生成展示字段：
```bash
python card_analyze.py --list              # 列出所有未分析的卡
python card_analyze.py --name 高凌枫       # 分析指定角色
python card_analyze.py --force --name 陈序  # 强制重新分析（已锁定的也重新生成）
```
生成后设置 `import_locked=1`，重启不会被 PNG 覆盖。

---

## 7. 数据库 Schema

数据库文件：`backend/data/aifriend.db`（SQLite）

### characters 表（角色卡）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | 文件名 hash（如 `85e1ec18737cb1e8`） |
| name | TEXT | 角色名 |
| subtitle | TEXT | 一行简介（展示用） |
| tags | TEXT | 标签（JSON 数组字符串） |
| opening_message | TEXT | 开场白（多条用 `|||` 分隔） |
| description | TEXT | 角色底稿（from PNG） |
| personality | TEXT | 性格设定 |
| scenario | TEXT | 场景设定 |
| mes_example | TEXT | 示例对话 |
| system_prompt | TEXT | 系统 Prompt（覆盖默认） |
| post_history_instructions | TEXT | 历史消息之后插入的提示 |
| character_book | TEXT | World Info（JSON 字符串） |
| raw_card_json | TEXT | PNG 解析出的完整 JSON |
| asset_type | TEXT | `text`/`hybrid`（有无媒体资源） |
| card_type | TEXT | `intimate`/`scenario`/`world` |
| is_visible | INTEGER | 是否在广场显示（0/1） |
| home_priority | INTEGER | 首页排序权重 |
| import_locked | INTEGER | 1=锁定，重启不被 PNG 覆盖 |
| embedded_format | TEXT | 嵌入格式标记 |

### users 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| email | TEXT UNIQUE | 邮箱（兼作用户名） |
| password_hash | TEXT | bcrypt 哈希（兼容旧版 SHA-256 登录后自动升级） |
| plan_type | TEXT | `free / vip / svip` |
| plan_expires_at | TEXT | 会员到期时间，空字符串表示普通用户 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 最近更新时间 |

### messages 表（聊天记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| user_id | INTEGER | 关联 users |
| character_id | TEXT | 关联 characters |
| role | TEXT | `user`/`assistant` |
| content | TEXT | 消息内容 |
| created_at | TEXT | 时间戳 |

### character_states 表（好感度 / 状态）

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | INTEGER | 联合主键 |
| character_id | TEXT | 联合主键 |
| affection | REAL | 好感度（0.0 ~ 100.0） |
| stage | TEXT | 阶段（stranger/acquaintance/friend/lover） |
| mood | TEXT | 当前心情 |
| last_updated | TEXT | 最后更新时间 |
| custom_state | TEXT | 自定义状态 JSON（扩展字段） |

### user_character_profiles 表（用户对角色的备注）

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | INTEGER | 联合主键 |
| character_id | TEXT | 联合主键 |
| user_nickname | TEXT | 用户给自己取的昵称（该角色专用） |

---

## 8. 角色卡系统

### 卡片格式

使用 **SillyTavern 兼容 PNG 格式**：
- PNG 文件的 `tEXt` chunk 里嵌入 base64 编码的 JSON
- JSON 结构遵循 [TavernAI V2 卡片规范](https://github.com/malfoyslastname/character-card-spec-v2)
- 主要字段：`name` / `description` / `personality` / `scenario` / `first_mes` / `alternate_greetings` / `mes_example` / `character_book`

### 卡片类型（card_type）

| 类型 | 说明 | Prompt 路由 |
|------|------|------------|
| `intimate` | 亲密陪伴型（主要） | 走 asset_type 路由（hybrid/text builder） |
| `scenario` | 剧情沙盒型 | 走 scenario builder |
| `world` | 世界书型 | 走 world/system builder |

### 导入流程

```
PNG 文件
  ↓ card_import.py（解析 + 写库，import_locked=0）
  ↓ card_analyze.py（AI 分析，生成 subtitle/tags/opening，import_locked=1）
  ↓ 人工复核（admin.html 编辑 is_visible/home_priority）
  ↓ 在广场显示
```

### World Info（character_book）

每张卡的 `character_book` 包含若干词条，结构：
```json
{
  "entries": {
    "0": {
      "keys": ["触发关键词"],
      "content": "词条内容（注入到 prompt 的文本）",
      "constant": false,
      "position": "before_char",
      "insertion_order": 100
    }
  }
}
```
- `constant=true`：每轮都注入
- `constant=false`：关键词命中才注入
- `position`：`before_char`（system 最前）或 `after_char`（system 最后）

---

## 9. Prompt 分层架构

### MiniMax 单-system 兼容方案

MiniMax 要求 system 消息只有一条，所有设定层合并：

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

[assistant]  ← 长期记忆摘要（结构化：用户画像/偏好/近期事件/关系状态）

[历史消息]   ← 最近 N 条，贪心填充 Token 预算
  ↑ depth_prompt 插入点（按 insertion_order 排列）

[user]       ← post_history 提醒（如输出格式要求）

[最新用户消息]
```

### Token 预算（TokenBudget 类）

```python
context_size = 64000        # 模型 context 窗口
output_reserve = 2048       # 保留给 AI 回复
available = 61952

system_budget    = 55%  # ~34000 tokens
history_budget   = 30%  # ~18500 tokens
memory_budget    = 8%   # ~4900  tokens
world_info_extra = 25%  # ~15000 tokens（叠加在 system 里）

换算比：1600 中文字 ≈ 1000 token
```

---

## 10. 好感度 / 状态系统

详见 `backend/AFFECTION_SYSTEM.md`。

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
- **角色自定义规则**：可覆盖全局规则（存于 `character_states.custom_state`）
- **三防机制**：Cooldown（CD 冷却）/ Daily Cap（每日上限）/ Diminishing Returns（递减效益）
- **阶段系数**：好感度高时涨得慢跌得快（lover 阶段：涨×0.4 / 跌×1.5）

### 好感度阶段

| 阶段 | 好感度区间 | 说明 |
|------|-----------|------|
| stranger | 0~20 | 陌生人 |
| acquaintance | 20~40 | 普通朋友 |
| friend | 40~70 | 亲密朋友 |
| lover | 70~100 | 恋人 |

---

## 11. 前端页面结构

单文件 SPA（`index.html` + `frontend/app.js`），无框架，原生 JS。

### 页面（section）

| ID | 说明 |
|----|------|
| `#page-home` | 首页（主视觉文案 + 产品卖点） |
| `#page-square` | 角色广场（按 card_type 分三区：💞亲密/🎭剧情/🌐世界） |
| `#page-chat` | 聊天页（打字机流式输出、状态栏、好感度进度条） |
| `#page-mine` | 我的（登录状态、试聊说明、长期记忆说明） |

### 底部导航

`NAV_CONFIG` 数组数据驱动，动态渲染 `#bottom-nav`。

### API_BASE 动态计算

```javascript
const API_BASE = (() => {
  const { protocol, hostname, port } = location;
  // 8000 / 空端口 / 443 / 80 → 同源（后端直接 serve 场景）
  if (port === '8000' || port === '' || port === '443' || port === '80') {
    return `${protocol}//${hostname}${port ? ':' + port : ''}/api`;
  }
  // 开发模式：页面在 3030，后端在 8000
  return `${protocol}//${hostname}:8000/api`;
})();
```

### 聊天流式（SSE）

```javascript
// 前端 POST /api/chat/stream → 接收 SSE 事件
// 事件格式：data: {"type":"chunk","content":"..."}\n\n
//           data: {"type":"done","reply":"完整回复"}\n\n
```

### 游客模式

- 未登录用户可直接走游客聊天（POST `/api/chat/guest-stream`）
- 聊天页顶部会显示一条简洁的“游客体验额度”提示
- 游客体验额度用完后，引导登录 / 注册继续聊天并保存记录

---

## 12. 环境变量配置

`backend/.env` 格式（参考 `.env.example`）：

```bash
# AI 接口通用兜底配置（至少填这一组）
AIFRIEND_API_KEY=your_api_key_here
AIFRIEND_BASE_URL=https://api.minimaxi.com/v1
AIFRIEND_MODEL=MiniMax-M2.5

# basic：游客 + 注册免费用户
AIFRIEND_BASIC_API_KEY=
AIFRIEND_BASIC_BASE_URL=
AIFRIEND_BASIC_MODEL=

# vip：VIP 用户
AIFRIEND_VIP_API_KEY=
AIFRIEND_VIP_BASE_URL=
AIFRIEND_VIP_MODEL=

# svip：SVIP 用户
AIFRIEND_SVIP_API_KEY=
AIFRIEND_SVIP_BASE_URL=
AIFRIEND_SVIP_MODEL=

# 会员与额度相关环境变量
FREE_DAILY_TOKEN_LIMIT=180000
VIP_DAILY_TOKEN_LIMIT=450000
SVIP_DAILY_TOKEN_LIMIT=900000

VIP_PLAN_PRICE_CENTS=2990
SVIP_PLAN_PRICE_CENTS=5990
VIP_PLAN_DURATION_DAYS=30
SVIP_PLAN_DURATION_DAYS=30

# 其他常用配置
GUEST_DAILY_TOKEN_LIMIT=40000
AI_CHAT_MAX_OUTPUT_TOKENS=768
TOKEN_EXPIRE_DAYS=30

# 其他 OpenAI 兼容接口示例：
# AIFRIEND_BASE_URL=https://api.openai.com/v1
# AIFRIEND_MODEL=gpt-4o
```

`model_adapter.py` 从环境变量读取配置，后端启动时自动加载 `.env`。

说明：

- 如果 `AIFRIEND_BASIC_* / AIFRIEND_VIP_* / AIFRIEND_SVIP_*` 没填，系统会自动回退到最上面的通用 `AIFRIEND_*` 配置。
- 角色访问权限由 `required_plan` 控制；用户实际走哪套模型，由当前生效档位 `effective_plan` 决定。
- 真网页支付还没接入，本轮只是先把会员档位、订单表和预下单接口搭起来。

---

## 13. 当前在库角色

以下角色已导入数据库并通过 AI 分析，可直接使用：

| 角色 | 文件名 | card_type | 说明 | home_priority |
|------|--------|-----------|------|---------------|
| 高凌枫 | `85e1ec18737cb1e8.png` | intimate | 对话陪伴男性向 | 1 |
| 路少晖 | `2.png` | scenario | 剧情沙盒，6条剧情线+世界书 | 3 |
| 姜禾 | `c03daced8f60c6c5.png` | intimate | 女团爱豆（女性角色） | 5 |
| 陆清商 | `fbc1d38e68bbe4d3.png` | intimate | 32岁职场御姐 | 6 |
| 白邬 | `db61100778f10e10.png` | intimate | 27岁御姐 | 7 |
| 陈序 | `陈序.png` | intimate | 备用，不在主广场 | 999 |

**广场优先展示逻辑**（`FEATURED_HOME_CARD_KEYWORDS`）：在 `main.py` 顶部定义，匹配关键词决定哪些卡出现在首页广场。

---

## 14. 后台配置怎么填（给不熟悉项目的人）

如果你只想先把一张角色卡配到“能用、顺、像真人”，建议按这个顺序来：

### 第一步：先填基础展示信息
- `角色名 / 副标题 / 标签 / 开场白`
- 这一层决定用户第一眼会不会点进来。

### 第二步：再看角色内容详情（runtime_layers）
- 最重要的是 `base_profile`、`examples`、`scenario`。
- 可以把它理解成：
  - `base_profile` = 这个人到底是谁
  - `examples` = 他说话像什么样
  - `scenario` = 你们现在处在什么关系 / 场景里

### 第三步：补高级配置里的“记忆条目”
- 至少准备 3 条高频记忆。
- 每条记忆最好只负责一件事，不要一条里塞一大堆设定。

### 第四步：补“开场白”
- 至少做两档：`陌生人` 和 `熟人`。
- 如果角色主打剧情差异，再继续补剧情线专属开场。

### 第五步：再考虑剧情线 / 后置规则 / 剧情事件
- 剧情线 = 角色的几种玩法
- 后置规则 = 每轮回复前最后再提醒模型一次的约束
- 剧情事件 = 好感度推进后的关键节点

### 第六步：最后一定看 Prompt 预览
- 这一步最重要，因为它会告诉你：AI 实际收到的内容到底是什么。
- 如果用户觉得角色前后不一致、剧情接不上、像机器人，通常都能在这里找到原因。

---

## 15. 已知待办和安全注意事项

### ⚠️ 上线前必须修复（P0 安全）

| 问题 | 位置 | 修复方案 |
|------|------|---------|
| CORS `allow_origins=["*"]` + credentials=True | main.py | 改为指定域名 |
| `/api/debug/*` 接口暴露内部数据 | main.py | 删除或加管理员鉴权 |

### P1 逻辑漏洞

- 用户消息先存库再调 AI，失败会产生孤儿消息
- 游客聊天 IP 计数依赖 header（可伪造）

### 下一步功能规划

| 优先级 | 功能 |
|--------|------|
| P0 | 状态栏剥离（AI 回复尾部状态栏隐藏到折叠面板，气泡只显示正文） |
| P1 | 手机/通讯模拟系统（关键词触发进入"微信对话框"UI） |
| P1 | P0 安全修复 |
| P2 | 向量语义匹配替代关键词触发 World Info |
| P2 | Supabase 上线（跨设备同步） |

### 已完成的基础稳定性改造

- ✅ 密码已切到 **bcrypt**，旧 SHA-256 用户会在下次登录时自动升级
- ✅ 登录 Token 已支持 **过期时间**（默认 30 天）
- ✅ 登录 / 聊天 / 游客试聊 已加上 **基础限流**（轻量内存版）
- ✅ 已加 **P0 成本防护**：每日 token 预算、单次输出上限、请求消耗日志

> 说明：当前限流是“单机单进程友好”的轻量方案，适合这个项目现在的部署方式；如果后面真的进入多实例部署，再升级到 Redis / 网关层限流即可。

### 成本防护现在怎么工作

当前聊天链路会做 3 层控制：

1. **基础限流**：短时间高频请求直接拦截
2. **每日 token 预算**：按字符数估算 token，超预算直接拦截
3. **单次最大输出上限**：限制单轮回复最长输出，避免一次回复特别贵

相关配置都可以在 `backend/.env` 调：

- `AI_CHAT_MAX_OUTPUT_TOKENS`
- `FREE_DAILY_TOKEN_LIMIT`
- `VIP_DAILY_TOKEN_LIMIT`
- `SVIP_DAILY_TOKEN_LIMIT`
- `GUEST_DAILY_TOKEN_LIMIT`

后台还会把每次聊天请求写入 `ai_request_logs`，方便后续排查：

- 谁最耗 token
- 游客 IP 有没有恶意刷
- 哪个接口最费钱
- 是否频繁触发 fallback

### 已完成的会员基础结构（本轮新增）

- ✅ 已支持 **4 档访问体系**：游客 / 注册用户 / VIP / SVIP
- ✅ 已支持 **3 套模型策略**：`basic / vip / svip`
- ✅ 角色已支持 `required_plan`，可直接做 **SVIP 专属角色**
- ✅ 已新增 `membership_orders` 订单表，先把网页支付主链路预留出来
- ✅ 后台已可直接手动把某个用户设置为 `free / vip / svip`

> 当前网页支付还属于“预留接口阶段”：前台/后端订单链路已铺好，但还没有接入真实支付平台的回调签名校验。也就是说，现在可以联调下单流程，但还不能直接真收款上线。

---

## 16. 维护优先原则（给代码小白接手）

如果你后面是“自己盯线上 + 主要靠 AI 帮你改代码”，那建议把下面这些当成**硬规则**，优先级比“多做几个新功能”更高。

### 1）以后默认遵循：**先稳定，再加功能**

新增功能只有同时满足下面 5 条时，才值得继续保留：

1. **出问题时容易关掉**：最好只是一个独立按钮、独立接口、独立配置，而不是改动整条聊天主链路。
2. **接口含义清楚**：前端怎么调、后端怎么收、返回什么，文档里能一眼看明白。
3. **有兜底逻辑**：即使接口失败，也不能把整页搞崩。
4. **管理后台可解释**：字段不是只有 AI 看得懂，人也能看懂它是干什么的。
5. **不引入额外部署复杂度**：能不新加中间件、队列、外部服务，就先别加。

如果一个功能“看起来很强”，但你自己半年后都不敢碰，那它对你来说就不算好功能。

### 2）每次改代码，只允许做“小步修改”

建议遵守下面的工作方式：

- **一次只改一个目标**：比如只改开场白选择、只改备注、只改后台某个面板。
- **改动尽量集中在 1~2 个文件**，不要一口气动 6 个模块。
- **先改文案和文档，再改逻辑**，这样你自己更容易复盘。
- **改完必须做最小自检**：
  - 后端能启动
  - 前台能进首页
  - 能选角色
  - 能发一条消息
  - 后台能打开并保存一次

一句话：**宁可慢一点，也不要让项目复杂度突然上升。**

### 3）真正要优先保住的，不是“高级功能”，而是这 6 条主链路

当用户多起来时，你最该先确保的是：

1. 后端能启动
2. 登录能成功
3. 角色列表能拉到
4. 聊天能正常发出并收到回复
5. 聊天记录不会莫名其妙丢失
6. 管理后台至少还能编辑角色基础信息

只要这 6 条还活着，项目就还能继续运营；
哪怕某些高级功能临时失效，也不至于全盘崩掉。

### 4）出 bug 时，按这个顺序排查，不容易慌

建议固定按下面顺序看：

#### 第一步：先看服务是不是活着

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

如果 8000 没进程，说明后端根本没起来。

#### 第二步：看健康检查

打开：

```text
http://127.0.0.1:8000/api/health
```

如果这个都不通，优先处理后端启动问题，不要先怀疑前端。

#### 第三步：判断是“前端问题”还是“后端问题”

- **首页都打不开**：先看后端/静态文件
- **首页能开，但角色列表空白**：先看 `/api/characters`
- **能进聊天，但发不出去消息**：先看 `/api/chat/stream`
- **后台能打开，但保存失败**：先看 `/api/admin/character/{id}` 相关接口

#### 第四步：先回退到“最近一次明确可用”的状态

如果你不确定是不是新改动导致的，最稳妥的方式不是继续硬修，而是：

- 先备份当前文件
- 回退最近一小步修改
- 确认主链路恢复
- 再重新分小步改

### 5）数据库一定先备份，再动结构或批量数据

当前核心数据都在：

```text
backend/data/aifriend.db
```

任何下面这些操作前，都建议先复制一份：

- 改表结构
- 批量导卡
- 删除角色
- 清大量聊天记录
- 让 AI 批量改配置

最简单的备份方式：

```bash
cp /Users/jjj/aifriend/backend/data/aifriend.db /Users/jjj/aifriend/backend/data/aifriend.backup.db
```

### 6）后面如果只能做 3 件稳定性工作，优先做这 3 个

这三个比花里胡哨的新功能重要得多：

1. **密码改成 bcrypt**（已完成）
2. **Token 增加过期时间**（已完成）
3. **给登录和聊天接口加限流 / 防刷**（已完成基础版）

因为用户一多，最先把你拖垮的，通常不是“功能不够多”，而是：

- 安全问题
- 异常请求
- 出 bug 后你自己不敢改

### 7）适合你的长期策略：少功能、强说明、可回退

按你现在的情况，最适合这个项目的方向不是“越来越像大厂系统”，而是：

- 功能数量**适中**
- 每个功能都**写清楚用途**
- 管理后台尽量**说人话**
- 每次改动都能**快速回退**
- 文档始终和代码保持同步

如果后续继续让 AI 帮你开发，也建议默认带上这句要求：

> **优先保证易维护、低耦合、可回退、出错有兜底，不要为了炫技增加复杂度。**

---

## 开发约定

1. **所有文件统一放在** `/Users/jjj/aifriend/`
2. **不自动导卡**：系统启动不扫描目录，手动用 `card_import.py` 导
3. **import_locked**：`card_analyze.py` 分析后锁定，防止重启覆盖展示字段
4. **版本号**：`index.html` 里 `?v=20260327f` 要每次改前端文件时更新
5. **实际数据库**在 `backend/data/aifriend.db`
6. **后端必须用 0.0.0.0**：`uvicorn main:app --host 0.0.0.0 --port 8000`，否则手机/ngrok 访问不到

---

*文档生成时间：2026-03-29*
