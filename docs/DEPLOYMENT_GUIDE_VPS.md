# VPS 部署完整教程

> 本教程适合代码新手，每一步都有详细说明。预计完成时间：1-2 小时

## 📋 部署方案概览

- **服务器**：Vultr VPS（新加坡机房）
- **配置**：1核 1GB 内存，25GB SSD
- **管理面板**：1Panel（中文图形化界面）
- **数据库**：Supabase（PostgreSQL 云数据库）
- **域名**：.xyz 或其他便宜域名
- **CDN**：Cloudflare（免费加速）
- **成本**：约 $6-8/月

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

> 如果本地已有角色数据需要迁移，请参考 Supabase 控制台的数据导入功能。

### 4.6 创建系统服务

1. 在 1Panel 终端执行：

```bash
cat > /etc/systemd/system/aifriend.service << 'EOF'
[Unit]
Description=AIFriend Backend Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/aifriend/backend
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

2. 启动服务：

```bash
systemctl daemon-reload
systemctl start aifriend
systemctl enable aifriend
```

3. 检查服务状态：

```bash
systemctl status aifriend
```

如果看到 "active (running)"，说明启动成功！

---

## 第五步：配置 Nginx 反向代理

### 5.1 安装 Nginx

1. 在 1Panel 应用商店搜索 "OpenResty"
2. 点击安装
3. 等待安装完成

### 5.2 创建网站

1. 在 1Panel 左侧菜单，点击 "网站"
2. 点击 "创建网站"
3. 填写信息：
   - **域名**: 你的域名（比如 `aifriend.xyz`）或暂时用 IP
   - **类型**: 反向代理
   - **代理地址**: `http://127.0.0.1:8000`
4. 点击 "确定"

### 5.3 配置静态文件

1. 点击刚创建的网站，选择 "配置"
2. 在配置文件中，找到 `location /` 部分
3. 在前面添加静态文件配置：

```nginx
# 静态文件
location / {
    root /opt/aifriend;
    try_files $uri $uri/ /index.html;
}

# API 代理
location /api {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}

# WebSocket 支持（流式响应）
location /api/chat/stream {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 300s;
}
```

4. 保存配置
5. 点击 "重载配置"

---

## 第六步：配置域名和 SSL

### 6.1 购买域名

1. 访问 [Namesilo](https://www.namesilo.com/) 或 [Namecheap](https://www.namecheap.com/)
2. 搜索你想要的 .xyz 域名
3. 加入购物车，结账（约 $1-2/年）
4. 完成购买

### 6.2 配置 DNS

1. 登录域名注册商后台
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
5. 保存

等待 10-30 分钟，DNS 生效。

### 6.3 配置 SSL 证书

1. 在 1Panel 网站列表，点击你的网站
2. 点击 "SSL" 标签
3. 选择 "Let's Encrypt"
4. 点击 "申请证书"
5. 等待 1-2 分钟，证书申请成功
6. 勾选 "强制 HTTPS"

现在你的网站已经支持 HTTPS 了！

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

## 第八步：配置自动备份

### 8.1 创建备份脚本

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

## 🎉 部署完成！

现在你可以：
1. 访问 `https://你的域名` 使用应用
2. 访问 `https://你的域名/frontend/admin/` 管理后台
3. 在 1Panel 查看服务器状态和日志
4. 每天自动备份数据库

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
