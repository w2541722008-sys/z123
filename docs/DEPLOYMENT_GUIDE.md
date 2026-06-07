# 部署指南

## 本地开发

### 1. 环境准备

```bash
# 安装依赖
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入数据库连接、API Key 等
```

### 2. 数据库初始化

```bash
cd backend
python3 -m alembic upgrade head
```

### 3. 启动服务

```bash
# 开发模式（热重载）
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 访问
# - 用户端: http://localhost:8000/
# - 管理后台: http://localhost:8000/admin.html
# - API 文档: http://localhost:8000/docs
```

---

## 生产部署

### 前置条件

- Ubuntu 20.04+ 服务器
- Python 3.10+
- PostgreSQL 数据库（推荐 Supabase）
- 域名已解析到服务器 IP

### 一键部署

```bash
# 本地执行（会自动同步代码、运行测试、重启服务）
bash deploy.sh
```

部署脚本会自动执行：
1. 检查服务器连接
2. 运行本地测试门禁
3. 备份服务器当前版本
4. 同步代码到服务器
5. 执行数据库迁移
6. 重启服务
7. 健康检查

### 手动部署步骤

#### 1. 服务器环境配置

```bash
# SSH 登录服务器
ssh ubuntu@your-server-ip

# 安装依赖
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nginx

# 创建项目目录
sudo mkdir -p /opt/aifriend
sudo chown ubuntu:ubuntu /opt/aifriend
```

#### 2. 配置环境变量

```bash
cd /opt/aifriend/backend
nano .env
```

必需配置：
```bash
ENV=production
DEBUG=false
DATABASE_URL=postgresql://user:pass@host:5432/dbname
ALLOWED_ORIGINS=https://your-domain.com
AIFRIEND_API_KEY=your-api-key
ADMIN_EMAILS=admin@example.com

# 邮件配置（二选一）
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-password
# 或
RESEND_API_KEY=re_xxx
```

#### 3. 数据库迁移

```bash
cd /opt/aifriend/backend
source .venv/bin/activate
python3 -m alembic upgrade head
```

#### 4. 配置 systemd 服务

```bash
sudo nano /etc/systemd/system/aifriend.service
```

```ini
[Unit]
Description=AIFriend Backend
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/aifriend/backend
Environment="PATH=/opt/aifriend/backend/.venv/bin"
ExecStart=/opt/aifriend/backend/.venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable aifriend
sudo systemctl start aifriend
```

#### 5. 配置 Nginx

```bash
sudo nano /etc/nginx/sites-available/aifriend
```

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/chat/stream {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/aifriend /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 6. 配置 HTTPS（Let's Encrypt）

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## 部署检查清单

### 配置检查
- [ ] `.env` 已配置并生效
- [ ] `ALLOWED_ORIGINS` 为生产域名
- [ ] `DATABASE_URL` 正确
- [ ] `ADMIN_EMAILS` 已设置
- [ ] 邮件服务已配置（SMTP 或 Resend）
- [ ] `ENV=production` + `DEBUG=false`

### 数据库检查
- [ ] `alembic upgrade head` 已执行
- [ ] 所有表已创建（18 张）
- [ ] 访问 `/api/health` 返回 `status=ok`

### 测试检查
- [ ] 本地测试通过（`bash deploy.sh` 会自动运行）
- [ ] 前端冒烟测试通过
- [ ] 后端单元测试通过

### 服务检查
- [ ] systemd 服务已启用并运行
- [ ] Nginx 配置正确
- [ ] HTTPS 证书已配置
- [ ] 日志可查看：`/var/log/aifriend.log`

### 功能检查
- [ ] 注册/登录正常
- [ ] 聊天流式响应正常
- [ ] 管理后台可访问
- [ ] 订单创建正常

---

## 回滚

```bash
bash rollback.sh
```

---

## 常见问题

### 服务无法启动
```bash
# 查看日志
sudo journalctl -u aifriend -n 50
tail -f /var/log/aifriend.log
```

### 数据库连接失败
- 检查 `DATABASE_URL` 格式
- 确认数据库允许服务器 IP 访问
- 测试连接：`psql $DATABASE_URL`

### 静态文件 404
- 确认 `frontend/` 目录已同步到服务器
- 检查 Nginx 配置中的 `proxy_pass`

### SSE 流式响应中断
- 检查 Nginx 配置中的 `proxy_buffering off`
- 确认 `proxy_http_version 1.1`

## Supabase 免费版注意事项

### 防止项目休眠

Supabase 免费版在 **连续 7 天无数据库活动** 后会自动暂停项目，届时服务将完全中断，需要登录 Supabase 控制台手动恢复。

本服务内置了 **keep-alive 守护线程**，每 5 分钟自动执行一次 `SELECT 1` 查询，无需额外配置即可防止休眠。你可以在启动日志中看到：

```
✅ 数据库 keep-alive 守护线程已启动（间隔 300 秒）
```

间隔可通过 `DB_KEEPALIVE_INTERVAL_SECONDS` 环境变量调整（默认 300 秒）。

### 双重保障：UptimeRobot 外部监控

如需双重保障（监控服务可用性 + 额外保活信号），可添加免费的 UptimeRobot 监控：

1. 注册 [UptimeRobot](https://uptimerobot.com/)（免费方案支持 50 个监控）
2. 点击 **Add New Monitor** → 类型选 **HTTP(s)**
3. URL 填 `https://你的域名/api/health`
4. 监控间隔设为 **5 分钟**
5. 告警联系人设为你的邮箱或手机

这样即使内置守护线程意外退出，UptimeRobot 的定期请求也会通过健康检查的 `SELECT 1` 查询让数据库保持活跃。

### 存储容量监控

免费版数据库上限 **500 MB**。登录管理后台 → 仪表盘，可以看到存储用量进度条：
- 🟢 绿色：60% 以下，正常
- 🟡 黄色：60-80%，需关注
- 🔴 红色：80% 以上，尽快处理
- 🔴 闪烁：90% 以上，即将写满中断

接近上限时可升级到 Pro 方案（$25/月，8 GB 存储），同一连接字符串无缝切换。
