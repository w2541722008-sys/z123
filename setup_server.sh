#!/usr/bin/env bash
# ============================================================
# AIFriend 腾讯云新加坡服务器初始化脚本
# 使用方法：
#   1. 先重置密码或配置 SSH Key
#   2. ssh ubuntu@124.156.199.146 'bash -s' < setup_server.sh
#   3. 或者先 SSH 登录，再上传运行
# ============================================================
set -Eeuo pipefail

echo "=========================================="
echo "🚀 AIFriend 服务器初始化"
echo "=========================================="
echo

# ----------------------------------------------------------
# 1. 系统更新 & 基础依赖
# ----------------------------------------------------------
echo "📌 步骤 1/7: 系统更新 & 安装基础依赖"
sudo apt-get update -y
sudo apt-get upgrade -y
sudo apt-get install -y \
  build-essential libpq-dev python3 python3-pip python3-venv \
  nginx certbot python3-certbot-nginx \
  git curl wget htop tmux unzip
echo "✅ 系统更新完成"
echo

# ----------------------------------------------------------
# 2. 创建项目目录
# ----------------------------------------------------------
echo "📌 步骤 2/7: 创建项目目录"
sudo mkdir -p /opt/aifriend
sudo chown -R "$(whoami)": "$(whoami)" /opt/aifriend
echo "✅ 目录创建完成: /opt/aifriend"
echo

# ----------------------------------------------------------
# 3. 创建 Python 虚拟环境
# ----------------------------------------------------------
echo "📌 步骤 3/7: 创建 Python 虚拟环境"
cd /opt/aifriend
python3 -m venv backend/venv 2>/dev/null || true
echo "✅ 虚拟环境就绪"
echo

# ----------------------------------------------------------
# 4. 配置 Nginx
# ----------------------------------------------------------
echo "📌 步骤 4/7: 配置 Nginx 反向代理"
sudo tee /etc/nginx/sites-available/aifriend > /dev/null << 'EOF'
# AIFriend - Nginx 反向代理配置
# 域名: lunawhisp.com

server {
    listen 80;
    server_name lunawhisp.com www.lunawhisp.com;

    # 前端静态文件
    location / {
        root /opt/aifriend/frontend;
        index index.html;
        try_files $uri $uri/ /index.html;

        # 静态资源缓存
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
            expires 7d;
            add_header Cache-Control "public, immutable";
        }
    }

    # 后端 API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 流式响应支持
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        chunked_transfer_encoding on;

        # WebSocket 支持（如需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # 健康检查不写日志
    location /api/health {
        proxy_pass http://127.0.0.1:8000;
        access_log off;
    }

    # 管理后台
    location /admin {
        root /opt/aifriend/frontend;
        try_files $uri $uri/ /admin/index.html;
    }

    # 安全头
    add_header X-Frame-Options SAMEORIGIN;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";

    # 日志
    access_log /var/log/nginx/aifriend_access.log;
    error_log /var/log/nginx/aifriend_error.log;
}
EOF

sudo ln -sf /etc/nginx/sites-available/aifriend /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl enable nginx && sudo systemctl restart nginx
echo "✅ Nginx 配置完成"
echo

# ----------------------------------------------------------
# 5. 创建 systemd 服务
# ----------------------------------------------------------
echo "📌 步骤 5/7: 配置 systemd 服务"
sudo tee /etc/systemd/system/aifriend.service > /dev/null << 'EOF'
[Unit]
Description=AIFriend Backend (FastAPI + uvicorn)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/aifriend/backend
EnvironmentFile=/opt/aifriend/backend/.env
ExecStart=/opt/aifriend/backend/venv/bin/python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5
StandardOutput=append:/var/log/aifriend.log
StandardError=append:/var/log/aifriend.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable aifriend
echo "✅ systemd 服务配置完成"
echo

# 日志轮转
if [[ -f /opt/aifriend/deploy/logrotate.conf ]]; then
  sudo cp /opt/aifriend/deploy/logrotate.conf /etc/logrotate.d/aifriend
  sudo chmod 644 /etc/logrotate.d/aifriend
  echo "✅ 日志轮转配置完成"
else
  echo "⚠️ 未找到 logrotate.conf，跳过日志轮转配置"
fi
echo

# ----------------------------------------------------------
# 6. 防火墙
# ----------------------------------------------------------
echo "📌 步骤 6/7: 配置防火墙"
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
echo "✅ 防火墙配置完成"
echo

# ----------------------------------------------------------
# 7. 创建 swap（2G 内存加个 swap 更稳妥）
# ----------------------------------------------------------
echo "📌 步骤 7/7: 创建 swap"
if [[ ! -f /swapfile ]]; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
  sudo sysctl vm.swappiness=10
  echo "✅ Swap 2G 创建完成"
else
  echo "✅ Swap 已存在，跳过"
fi
echo

# ----------------------------------------------------------
# 完成
# ----------------------------------------------------------
echo "=========================================="
echo "✅ 服务器初始化完成！"
echo "=========================================="
echo
echo "📋 后续步骤："
echo "  1. 创建 backend/.env 文件（参考 backend/.env.example）"
echo "  2. 运行 bash deploy.sh 部署项目"
echo "  3. 配置 SSL: sudo certbot --nginx -d lunawhisp.com（如尚未配置）"
echo
echo "🔍 有用的命令："
echo "  查看服务状态: sudo systemctl status aifriend"
echo "  查看日志:     tail -f /var/log/aifriend.log"
echo "  重启服务:     sudo systemctl restart aifriend"
echo "  Nginx 日志:   tail -f /var/log/nginx/aifriend_error.log"
echo
