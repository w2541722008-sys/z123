# VPS 部署完整教程

> 本教程基于**实际部署经验**编写，每一步都经过验证。预计完成时间：1-2 小时
> **文档更新时间**: 2026-04-03（新增 SSE 流式配置 + 图片长期缓存规则）

## 📋 实际部署方案

- **服务器**: VPS（新加坡机房，1核 1GB+ 内存）
- **管理面板**: 1Panel（中文图形化界面，端口 10086）
- **Web 服务器**: **OpenResty（Docker 容器）** — 1Panel 内置，注意与系统 Nginx 不同
- **后端服务**: **Uvicorn**（Python ASGI 服务器）— 通过 systemd 管理开机自启
- **数据库**: Supabase（PostgreSQL 云数据库）
- **域名**: 自有域名（如 Spaceship.com）
- **SSL**: Let's Encrypt 免费证书（certbot + webroot 模式）
- **成本**: 约 $6-8/月

> ⚠️ **重要提示**：本项目的部署有几个**容易踩的坑**，都在下方标注了。

---

## 第一步：购买 VPS 服务器

### 1.1 注册 Vultr 账号

1. 访问 [Vultr 官网](https://www.vultr.com/)
2. 点击右上角 "Sign Up" 注册账号
3. 使用邮箱注册（建议用 Gmail）
4. 验证邮箱

### 1.2 充值

1. 登录后，点击左侧 "Billing" → "Add Funds"
2. 最低充值 $10（可以用 2 个月）
3. 支付方式：信用卡、PayPal、支付宝

### 1.3 创建服务器

1. 点击左侧 "Products" → "Deploy New Server"
2. 选择配置：
   - **Server Type**: Cloud Compute - Shared CPU
   - **Location**: Singapore（新加坡，国内访问快）
   - **Operating System**: Ubuntu 22.04 LTS x64
   - **Server Size**: 1 CPU, 1GB Memory, 25GB SSD ($6/月)
   - **Additional Features**: 不需要勾选
   - **Server Hostname**: 随便填，比如 `aifriend-prod`
3. 点击 "Deploy Now"
4. 等待 2-3 分钟，服务器创建完成

### 1.4 获取服务器信息

创建完成后，点击服务器名称，你会看到：
- **IP Address**: 你的服务器 IP（比如 `123.45.67.89`）
- **Username**: `root`
- **Password**: 点击眼睛图标查看密码（复制保存好）

---

## 第二步：安装 1Panel 管理面板

### 2.1 连接服务器

**方法 1：使用 Vultr 网页控制台（最简单）**
1. 在 Vultr 服务器页面，点击右上角的 "View Console"
2. 会打开一个黑色的命令行窗口
3. 输入用户名 `root`，按回车
4. 输入密码（粘贴刚才复制的密码），按回车
   - 注意：输入密码时不会显示任何字符，这是正常的

**方法 2：使用 SSH 客户端（Mac/Linux）**
1. 打开终端（Terminal）
2. 输入：`ssh root@你的服务器IP`
3. 输入密码

### 2.2 安装 1Panel

连接成功后，复制粘贴以下命令（一次一行）：

```bash
# 下载安装脚本
curl -sSL https://resource.fit2cloud.com/1panel/package/quick_start.sh -o quick_start.sh

# 运行安装脚本
bash quick_start.sh
```

安装过程中会询问：
1. **是否同意协议**：输入 `y`，按回车
2. **安装目录**：直接按回车（使用默认）
3. **端口**：直接按回车（使用默认 10086）
4. **面板用户名**：输入你想要的用户名（比如 `admin`）
5. **面板密码**：输入你想要的密码（至少 8 位，记住它！）

安装完成后，会显示：
```
=================感谢您的耐心等待，安装已经完成==================
 
面板地址: http://你的服务器IP:10086/安全入口
面板用户: admin
面板密码: 你设置的密码
 
================================================================
```

**重要：复制保存这些信息！**

### 2.3 登录 1Panel

1. 在浏览器打开：`http://你的服务器IP:10086/安全入口`
2. 输入用户名和密码登录
3. 首次登录会要求修改安全入口，建议修改（比如改成 `/myentry`）

---

## 第三步：配置 Supabase 数据库

### 3.1 注册 Supabase

1. 访问 [Supabase 官网](https://supabase.com/)
2. 点击 "Start your project"
3. 使用 GitHub 账号登录（如果没有，先注册 GitHub）

### 3.2 创建项目

1. 点击 "New Project"
2. 填写信息：
   - **Name**: `aifriend-db`（随便填）
   - **Database Password**: 设置一个强密码（记住它！）
   - **Region**: Southeast Asia (Singapore)（选新加坡）
   - **Pricing Plan**: Free（免费）
3. 点击 "Create new project"
4. 等待 2-3 分钟，数据库创建完成

### 3.3 获取数据库连接信息

1. 项目创建完成后，点击左侧 "Settings" → "Database"
2. 找到 "Connection string" 部分
3. 选择 "URI" 模式
4. 复制连接字符串，格式类似：
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.xxx.supabase.co:5432/postgres
   ```
5. 把 `[YOUR-PASSWORD]` 替换成你刚才设置的数据库密码
6. **保存这个连接字符串！**

### 3.4 创建数据库表

1. 点击左侧 "SQL Editor"
2. 点击 "New query"
3. 复制粘贴 `docs/supabase_schema.sql` 的内容（稍后我会创建这个文件）
4. 点击 "Run" 执行
5. 如果成功，会显示 "Success. No rows returned"

---

## 第四步：部署应用

### 4.1 上传代码到服务器

**重要提示**：由于项目文件较多，需要先压缩再上传。

**步骤 1：在本地压缩项目**

在你的电脑上，打开终端（Mac）或命令提示符（Windows），进入项目目录：

```bash
# Mac/Linux
cd /path/to/aifriend
tar -czf aifriend.tar.gz \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='.git' \
  --exclude='*.pyc' \
  --exclude='backend/data/*.db*' \
  --exclude='.DS_Store' \
  .

# Windows (使用 PowerShell)
# 先安装 7-Zip，然后：
7z a -ttar -so aifriend.tar . -xr!node_modules -xr!__pycache__ -xr!.git -xr!*.pyc -xr!backend/data/*.db* | 7z a -si aifriend.tar.gz
```

这会创建一个 `aifriend.tar.gz` 压缩包，排除了不必要的文件。

**步骤 2：上传压缩包**

1. 在 1Panel 左侧菜单，点击 "文件"
2. 进入 `/opt` 目录
3. 点击 "上传" → "上传文件"
4. 选择刚才创建的 `aifriend.tar.gz` 文件
5. 等待上传完成

**步骤 3：解压文件**

1. 在 1Panel 文件管理中，找到 `aifriend.tar.gz`
2. 右键点击，选择 "解压"
3. 解压到当前目录
4. 解压完成后，会看到 `aifriend` 文件夹
5. 可以删除 `aifriend.tar.gz` 压缩包了

**方法 2：使用 Git（推荐，如果代码在 GitHub）**

在 1Panel 的 "终端" 中执行：
```bash
cd /opt
git clone https://github.com/你的用户名/aifriend.git
cd aifriend
```

这种方法更简单，而且方便后续更新代码。

### 4.2 安装 Python 环境

1. 在 1Panel 左侧菜单，点击 "应用商店"
2. 搜索 "Python"
3. 安装 "Python 3.11"
4. 等待安装完成

### 4.3 配置环境变量

1. 在 1Panel 文件管理中，进入 `/opt/aifriend/backend`
2. 找到 `.env.example` 文件
3. 点击 "复制"，重命名为 `.env`
4. 点击 `.env` 文件，选择 "编辑"
5. 修改以下内容：

```env
# === 环境与调试 ===
ENV=production
DEBUG=false

# === 数据库配置（Supabase）===
DATABASE_URL=postgresql://postgres:你的密码@db.xxx.supabase.co:5432/postgres

# === AI 模型配置 ===
# 使用 MiniMax API（OpenAI 兼容格式）
AIFRIEND_API_KEY=你的MiniMax_API密钥
AIFRIEND_BASE_URL=https://api.minimaxi.com/v1
AIFRIEND_MODEL=MiniMax-M2.5

# === CORS 跨域配置 ===
# 上线后必须改为你的真实域名！
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# === 邮件服务（密码重置）===
RESEND_API_KEY=你的Resend_API密钥

# === 管理员邮箱（逗号分隔）===
ADMIN_EMAILS=你的管理员邮箱

# === JWT 密钥 ===
JWT_SECRET_KEY=随机生成一个32位以上的复杂字符串

# === 限流配置（可选，默认值即可）===
TOKEN_EXPIRE_DAYS=30
```

> **环境变量完整说明**：参考 `backend/.env.example` 文件，里面有详细注释和可选配置。

6. 保存文件

### 4.4 安装依赖

1. 在 1Panel 左侧菜单，点击 "终端"
2. 执行以下命令：

```bash
cd /opt/aifriend/backend
pip3 install -r requirements.txt
```

等待安装完成（约 2-3 分钟）

### 4.5 建表初始化

首次部署需要在 Supabase 中创建数据库表：

1. 登录 [Supabase 控制台](https://supabase.com)
2. 进入你的项目 → **SQL Editor**
3. 点击 **New query**
4. 复制粘贴项目中的 `docs/supabase_schema.sql` 内容
5. 点击 **Run** 执行
6. 如果成功，会显示 "Success. No rows returned"

### 4.7 创建系统服务（重要！）

> ⚠️ **踩坑**：不要用 `python3 -m uvicorn` 直接启动，因为：
> 1. 无法开机自启
> 2. 崩溃后不会自动重启
> 3. 虚拟环境路径必须写完整（包括 venv/bin/）

```bash
cat > /etc/systemd/system/aifriend.service << 'EOF'
[Unit]
Description=AIFriend Backend (Uvicorn)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/aifriend_deploy_你的时间戳/backend
ExecStart=/opt/aifriend_deploy_你的时间戳/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=ENV=production

[Install]
WantedBy=multi-user.target
EOF
```

2. 启动并设为开机自启：

```bash
systemctl daemon-reload
systemctl start aifriend
systemctl enable aifriend

# 验证
systemctl status aifriend
# 应该显示 "active (running)"
curl http://127.0.0.1:8000/api/health
# 应该返回 {"status":"ok","database":true,"config":true}
```

---

## 第五步：配置 OpenResty 反向代理（⚠️ 踩坑重灾区）

> ⚠️ **1Panel 的 OpenResty 是 Docker 容器**，和系统 Nginx 完全不同！
> - 配置文件在：`/opt/1panel/apps/openresty/openresty/conf/conf.d/`
> - 主配置在：`/opt/1panel/apps/openresty/openresty/conf/nginx.conf`
> - **容器内只能看到 docker-compose.yml 声明的卷目录**
> - 重启命令：`cd /opt/1panel/apps/openresty/openresty && docker compose restart`

### 5.1 确认 OpenResty 状态

```bash
# 查看容器是否运行
docker ps | grep openresty

# 查看容器内的卷挂载
cat /opt/1panel/apps/openresty/openresty/docker-compose.yml | grep volumes -A 10
```

关键卷挂载：
```yaml
volumes:
  - ./conf/conf.d:/usr/local/openresty/nginx/conf/conf.d/   # ← 你的网站配置放这里
  - ./www:/www                                                   # ← 静态文件放这里（容器内路径）
```

### 5.2 ⚠️ 踩坑1：WAF 导致所有请求 500

**现象**：配置正确但所有请求返回 HTTP 500

**原因**：1Panel OpenResty 主配置引用了不存在的 WAF 文件：
```nginx
# /usr/local/openresty/nginx/conf/nginx.conf 第42行
include /usr/local/openresty/1pwaf/data/conf/waf.conf;  # ← 文件不存在！
```

**修复**：
```bash
# 注释掉 WAF 行
sed -i 's|include /usr/local/openresty/1pwaf/data/conf/waf.conf;|# DISABLED|' \
  /opt/1panel/apps/openresty/openresty/conf/nginx.conf

# 重启
cd /opt/1panel/apps/openresty/openresty && docker compose restart
```

### 5.3 ⚠️ 踩坑2：Docker 容器看不到宿主机文件

**现象**：Nginx 配置 `root /opt/aifriend_deploy_xxx` 但返回 404

**原因**：容器只能访问 `./www` 映射的 `/www`，看不到 `/opt/` 其他路径

**修复**：
```bash
# 把前端文件复制到 www 目录（已挂载到容器）
cp -r /opt/aifriend_deploy_xxx/* /opt/1panel/apps/openresty/openresty/www/
cp -r /opt/aifriend_deploy_xxx/frontend/admin /opt/1panel/apps/openresty/openresty/www/

# Nginx 配置中 root 用容器内路径
root /www;    # 不是 /opt/aifriend_deploy_xxx
```

### 5.4 ⚠️ 踩坑3：默认站点拦截你的域名

**现象**：访问域名返回的是 Nginx 默认页面而不是你的应用

**原因**：`00.default.conf` 和 `default.conf` 的 `server_name _` 通配符优先匹配了

**修复**：
```bash
# 禁用默认站点
cd /opt/1panel/apps/openresty/openresty/conf/conf.d/
mv 00.default.conf 00.default.conf.disabled
mv default.conf default_conf.disabled
docker compose restart
```

### 5.5 创建网站配置

在 `/opt/1panel/apps/openresty/openresty/conf/conf.d/` 下创建 `aifriend.conf`：

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com 你的服务器IP;

    root /www;
    index index.html;

    # Let's Encrypt ACME（必须在安全规则之前）
    location ^~ /.well-known/acme-challenge/ {
        allow all;
        try_files $uri =404;
    }

    # 安全：屏蔽隐藏文件
    location ~ /\.\. {
        deny all;
        return 404;
    }

    # 屏蔽敏感目录
    location ~ ^/(backend|docs|tests|data|venv)/ {
        deny all;
        return 404;
    }

    # 后台管理页面 → 后端动态路由
    location = /admin.html {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # 前端 SPA
    location / {
        try_files $uri $uri/ /index.html;
        expires 7d;
    }

    # API 反向代理
    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 流式输出必须关闭缓冲（否则 Nginx 会攒着数据一起发）
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }

    # 图片资源长期缓存（头像、封面等）
    location ~* \.(png|jpg|jpeg|webp|gif|ico|svg)$ {
        try_files $uri =404;
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }
}
```

### 5.6 重启并验证

```bash
cd /opt/1panel/apps/openresty/openresty && docker compose restart
sleep 2

# 验证
curl -sI http://127.0.0.1:80/          # 应该返回 200
curl -s http://127.0.0.1:80/api/health  # 应该返回 {"status":"ok",...}
```

---

## 第六步：配置域名和 SSL（HTTPS）

### 6.1 配置 DNS

1. 登录域名注册商后台（如 Spaceship.com、Namesilo 等）
2. 找到你的域名，点击 "Manage DNS"
3. 添加 A 记录：
   - **Type**: A
   - **Host**: @（表示根域名）
   - **Value**: 你的服务器 IP
   - **TTL**: 3600
4. 添加 www 记录：
   - **Type**: CNAME
   - **Host**: www
   - **Value**: 你的域名
   - **TTL**: 3600
5. 保存，等待 10-30 分钟 DNS 生效

验证：`dig yourdomain.com` 应该返回你的服务器 IP

### 6.2 ⚠️ 踩坑4：Let's Encrypt 证书 + Docker 容器

> **问题**：Let's Encrypt 证书是**符号链接**（symlink），Docker 容器内无法跟随解析

**解决方案**：把实际证书文件复制到已挂载的 www 目录

```bash
# 1. 安装 certbot
apt-get install -y certbot python3-certbot-nginx

# 2. 申请证书（webroot 模式）
certbot certonly --webroot -w /opt/1panel/apps/openresty/openresty/www \
  -d yourdomain.com -d www.yourdomain.com \
  --non-interactive --agree-tos --email your@email.com

# 3. 复制证书到容器可访问的路径
mkdir -p /opt/1panel/apps/openresty/openresty/www/ssl
cp -L /etc/letsencrypt/live/yourdomain.com/fullchain.pem \
  /opt/1panel/apps/openresty/openresty/www/ssl/fullchain.pem
cp -L /etc/letsencrypt/live/yourdomain.com/privkey.pem \
  /opt/1panel/apps/openresty/openresty/www/ssl/privkey.pem
```

### 6.3 配置 HTTPS

更新 `aifriend.conf`（在 `conf.d/` 下），添加 SSL server 块：

```nginx
# HTTP → HTTPS 重定向
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    return 301 https://yourdomain.com$request_uri;
}

# HTTPS 主配置
server {
    listen 443 ssl;
    server_name yourdomain.com www.yourdomain.com;

    # 证书路径（容器内路径！）
    ssl_certificate /www/ssl/fullchain.pem;
    ssl_certificate_key /www/ssl/privkey.pem;

    # ... 其余配置同上（root, location 等） ...
}
```

重启 OpenResty：`docker compose restart`

### 6.4 验证 HTTPS

```bash
curl -skI https://yourdomain.com/       # HTTP 200
curl -skI http://yourdomain.com/        # 301 → https://
curl -sk https://yourdomain.com/api/health  # {"status":"ok",...}
```

### 6.5 设置证书自动续期

Let's Encrypt 证书有效期为 90 天。设置 cron 自动续期：

```bash
# 编辑 crontab
crontab -e

# 每月1号凌晨3点续期并复制到www目录
0 3 1 * * certbot renew --quiet && \
  cp -L /etc/letsencrypt/live/yourdomain.com/*.pem \
     /opt/1panel/apps/openresty/openresty/www/ssl/ && \
  cd /opt/1panel/apps/openresty/openresty && docker compose restart
```

---

## 第七步：配置 Cloudflare CDN（可选但推荐）

### 7.1 注册 Cloudflare

1. 访问 [Cloudflare](https://www.cloudflare.com/)
2. 注册账号（免费）

### 7.2 添加网站

1. 点击 "Add a Site"
2. 输入你的域名
3. 选择 "Free" 计划
4. 点击 "Continue"

### 7.3 修改域名服务器

1. Cloudflare 会显示两个域名服务器（Nameservers），比如：
   ```
   ns1.cloudflare.com
   ns2.cloudflare.com
   ```
2. 回到你的域名注册商后台
3. 找到 "Nameservers" 设置
4. 把原来的域名服务器替换成 Cloudflare 的
5. 保存

等待 24 小时，DNS 完全生效。

### 7.4 配置 Cloudflare

1. 在 Cloudflare 控制台，点击你的域名
2. 点击 "SSL/TLS" → 选择 "Full (strict)"
3. 点击 "Speed" → "Optimization"
   - 开启 "Auto Minify"（HTML, CSS, JS）
   - 开启 "Brotli"
4. 点击 "Caching" → "Configuration"
   - Cache Level: Standard
   - Browser Cache TTL: 4 hours

现在你的网站已经通过 Cloudflare CDN 加速了！

---

## 第八步：验证部署

### 8.1 基础检查

```bash
# 1. 后端服务状态
systemctl status aifriend
# 应该显示 "active (running)"

# 2. 后端健康检查
curl http://127.0.0.1:8000/api/health
# 应该返回 {"status":"ok","database":true,"config":true}

# 3. OpenResty 状态
docker ps | grep openresty

# 4. HTTP 访问（前端）
curl -sI http://yourdomain.com/
# 应该返回 301 → https:// 或 200

# 5. HTTPS 访问
curl -skI https://yourdomain.com/
# 应该返回 200 OK

# 6. API 代理
curl -sk https://yourdomain.com/api/health
# 应该返回 {"status":"ok",...}
```

### 8.2 浏览器访问

打开浏览器，访问：

| 地址 | 预期结果 |
|------|----------|
| `https://yourdomain.com` | 主页正常加载 |
| `https://yourdomain.com/admin.html` | 后台管理页面 |
| `https://yourdomain.com/api/health` | `{"status":"ok",...}` |

### 8.3 功能测试清单

- [ ] 注册新用户 → 收到验证邮件
- [ ] 登录 → 进入主页
- [ ] 选择角色 → 打开对话框
- [ ] 发送消息 → AI 正常回复（SSE 流式输出）
- [ ] 刷新页面 → 聊天记录保留
- [ ] 管理员登录后台 → 能看到仪表盘

---

## 第九步：配置自动备份

### 9.1 创建备份脚本

在 1Panel 终端执行：

```bash
cat > /opt/aifriend/backend/backup_supabase.sh << 'EOF'
#!/bin/bash

# 备份目录
BACKUP_DIR="/opt/aifriend/backups"
mkdir -p $BACKUP_DIR

# 备份文件名（带时间戳）
BACKUP_FILE="$BACKUP_DIR/backup_$(date +%Y%m%d_%H%M%S).sql"

# 从 .env 读取数据库连接信息
source /opt/aifriend/backend/.env

# 执行备份
pg_dump $DATABASE_URL > $BACKUP_FILE

# 压缩备份
gzip $BACKUP_FILE

# 删除 7 天前的备份
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete

echo "备份完成: $BACKUP_FILE.gz"
EOF

chmod +x /opt/aifriend/backend/backup_supabase.sh
```

### 8.2 配置定时任务

1. 在 1Panel 左侧菜单，点击 "计划任务"
2. 点击 "创建任务"
3. 填写信息：
   - **任务名称**: 数据库备份
   - **任务类型**: Shell 脚本
   - **执行周期**: 每天 3:00
   - **脚本内容**: `/opt/aifriend/backend/backup_supabase.sh`
4. 点击 "确定"

现在系统会每天凌晨 3 点自动备份数据库！

---

## 第九步：配置监控告警

### 9.1 使用 UptimeRobot（免费）

1. 访问 [UptimeRobot](https://uptimerobot.com/)
2. 注册账号（免费）
3. 点击 "Add New Monitor"
4. 填写信息：
   - **Monitor Type**: HTTP(s)
   - **Friendly Name**: AIFriend 网站
   - **URL**: https://你的域名
   - **Monitoring Interval**: 5 minutes
5. 点击 "Create Monitor"

### 9.2 配置告警

1. 点击 "Alert Contacts"
2. 添加邮箱或手机号
3. 当网站宕机时，会自动发送通知

---

## 📋 故障排查（基于实际部署经验）

> 以下问题都是**实际踩过的坑**，按出现频率排序

### 问题1：所有请求返回 HTTP 500

**现象**：Nginx 配置正确，但访问任何路径都返回 500

**原因**：1Panel OpenResty WAF 文件不存在
```bash
# 检查
docker exec <容器名> tail -5 /var/log/nginx/error.log
# 如果看到: open() "/usr/local/openresty/1pwaf/data/conf/waf.conf" failed (No such file)
```

**修复**：注释掉 WAF include 行（见上方 5.2 节）

---

### 问题2：Nginx 返回 404 但文件确实存在

**现象**：`root /opt/aifriend_deploy_xxx` 配置正确，文件存在但 404

**原因**：Docker 容器内看不到宿主机 `/opt/` 路径（卷未挂载）

**修复**：把文件复制到 `./www/` 目录（容器已挂载的路径），见上方 5.3 节

---

### 问题3：访问域名显示 Nginx 默认页面

**现象**：DNS 已生效，但显示的是 Nginx 的 Welcome 页面

**原因**：默认站点配置的 `server_name _` 通配符拦截了请求

**修复**：禁用 `00.default.conf` 和 `default.conf`（见上方 5.4 节）

---

### 问题4：HTTPS 证书配置后容器崩溃循环

**现象**：加了 SSL 配置后 `docker compose restart` 容器一直 Restarting

**原因**：Let's Encrypt 证书是符号链接（symlink），Docker 容器内无法解析

**错误日志**：`docker logs <容器名>` 显示 `cannot load certificate`
**修复**：复制证书到 www/ssl/ 目录（见上方 6.2 节）

---

### 问题5：后台管理页面 403/404 或显示主页

**现象**：访问 `/admin.html` 返回主页或 404

**原因**：
- admin 文件夹未复制到 www 目录 → SPA 路由回退到 index.html
- 安全规则屏蔽了隐藏文件（`.well-known` 等）

**修复**：
```bash
cp -r frontend/admin /opt/1panel/apps/openresty/openresty/www/admin/
# 确保配置中有 location = /admin.html { proxy_pass ...; }
```

---

### 问题6：头像/封面图片不显示

**现象**：角色卡片上没有图片，或浏览器加载失败

**原因**：
- 后端 `get_avatar()` / `get_cover()` 接口报错（`get_db()` 用法错误）
- 数据库只有 avatar 没有 cover 文件（首页优先用 cover）

**检查**：
```bash
curl http://127.0.0.1:8000/api/avatar/<character_id>
# 如果返回 500，查看后端日志
journalctl -u aifriend -n 20
```

**修复**：确保代码使用 `with get_db() as conn:` 而非 `conn = get_db()`

---

### 问题7：后端启动失败 "Could not import module 'main'"

**现象**：systemd 启动 uvicorn 报错找不到 main.py

**原因**：systemd 服务中 `WorkingDirectory` 应指向 `backend/` 子目录而非项目根目录

**修复**：
```
WorkingDirectory=/opt/aifriend_deploy_xxx/backend   # 不是 /opt/aifriend_deploy_xxx/
ExecStart=.../backend/venv/bin/uvicorn main:app ...
```

---

### 问题8：管理员无法访问后台

**现象**：登录后在 `/admin.html` 提示"没有权限"或 500 错误

**原因链**：
1. `/api/auth/me` 返回 500 → CurrentUser 缺少 `avatar_url` 字段
2. Token 中 is_admin=false → .env ADMIN_EMAILS 未正确加载
3. 前端 JS API 地址错误 → 走了错误的端口

**诊断**：打开 F12 Console 查看 `[Admin Debug]` 日志和具体错误信息

---

## 🎉 部署完成！

现在你可以：
1. 访问 `https://你的域名` 使用应用
2. 访问 `https://你的域名/admin.html` 管理后台
3. 在 1Panel 查看服务器状态和日志
4. 每天自动备份数据库
5. Let's Encrypt 证书自动续期

---

## 📝 日常维护

### 查看应用日志

1. 在 1Panel 终端执行：
```bash
journalctl -u aifriend -f
```

### 重启应用

1. 在 1Panel 终端执行：
```bash
systemctl restart aifriend
```

或在 1Panel 界面：
1. 点击 "容器" → "应用"
2. 找到 aifriend 服务
3. 点击 "重启"

### 更新代码

1. 在 1Panel 终端执行：
```bash
cd /opt/aifriend
git pull
systemctl restart aifriend
```

### 恢复备份

1. 找到备份文件：
```bash
ls -lh /opt/aifriend/backups/
```

2. 恢复：
```bash
gunzip -c /opt/aifriend/backups/backup_YYYYMMDD_HHMMSS.sql.gz | psql $DATABASE_URL
```

---

## ❓ 常见问题

### 1. 网站打不开

检查步骤：
1. 检查服务是否运行：`systemctl status aifriend`
2. 检查端口是否开放：`netstat -tlnp | grep 8000`
3. 检查防火墙：在 1Panel "安全" → "防火墙" 中开放 80 和 443 端口
4. 检查 DNS 是否生效：`ping 你的域名`

### 2. 数据库连接失败

检查步骤：
1. 确认 `.env` 中的 `DATABASE_URL` 正确
2. 确认 Supabase 项目没有暂停（免费版 7 天不活动会暂停）
3. 在 Supabase 控制台检查数据库状态

### 3. SSL 证书申请失败

可能原因：
1. DNS 还没生效（等待 30 分钟再试）
2. 80 端口没开放（在防火墙中开放）
3. 域名解析不正确（检查 A 记录）

### 4. 应用运行缓慢

优化建议：
1. 升级服务器配置（2核 2GB）
2. 检查数据库查询是否有慢查询
3. 开启 Cloudflare CDN
4. 检查日志是否有错误

---

## 📞 获取帮助

如果遇到问题：
1. 查看应用日志：`journalctl -u aifriend -n 100`
2. 查看 Nginx 日志：在 1Panel "网站" → 你的网站 → "日志"
3. 在项目 GitHub Issues 提问
4. 发邮件给开发者

---

**祝你部署顺利！🚀**
