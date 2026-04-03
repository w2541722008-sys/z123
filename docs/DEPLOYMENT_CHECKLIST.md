# 🚀 上线检查清单

在将应用部署到生产环境之前，请逐项检查以下内容。

---

## 📋 第一部分：环境配置（必须完成）

### 1. 环境变量配置

参考 `backend/.env.example`，确保以下环境变量已正确设置：

- [ ] **AIFRIEND_API_KEY** - 已设置为生产环境的真实 API Key
- [ ] **AIFRIEND_BASE_URL** - 已设置为正确的 AI 模型接口地址
- [ ] **AIFRIEND_MODEL** - 已设置为生产环境使用的模型名称
- [ ] **DATABASE_URL** - 已设置为 Supabase PostgreSQL 连接字符串
- [ ] **ALLOWED_ORIGINS** - 已改为生产域名（不是 localhost）
  - 示例：`https://yourdomain.com,https://www.yourdomain.com`
- [ ] **RESEND_API_KEY** - 邮件服务 API Key 已设置
- [ ] **ADMIN_EMAILS** - 管理员邮箱已设置

### 2. 验证配置

启动应用后检查日志：

```bash
cd backend
python main.py
```

- [ ] 启动时没有出现 "⚠️ 检测到缺失的生产环境配置" 警告
- [ ] 访问 `http://localhost:8000/api/health` 返回：
  ```json
  {
    "status": "ok",
    "database": true,
    "config": true
  }
  ```

---

## 🔒 第二部分：安全检查（必须完成）

### 3. 敏感文件保护

- [ ] `.env` 文件已添加到 `.gitignore`（不要提交到 Git）
- [ ] `backend/data/app_secret.txt` 已添加到 `.gitignore`
- [ ] 数据库文件 `backend/data/*.db` 已添加到 `.gitignore`
- [ ] `avatars/` 目录已添加到 `.gitignore`（不提交用户上传的头像文件）

### 4. 调试功能

- [ ] **DEBUG 模式已关闭** - 环境变量 `DEBUG=false`（生产环境必须）
- [ ] 所有调试端点已移除（`/api/debug/*`）
- [ ] 生产环境不输出详细的错误堆栈信息
- [ ] **HTTPS/SSL 已配置** - Let's Encrypt 证书有效且未过期
- [ ] **HTTP → HTTPS 自动跳转** - Nginx/OpenResty 配置了 301 重定向

### 5. CORS 配置

- [ ] `ALLOWED_ORIGINS` 只包含真实的生产域名
- [ ] 不包含 `localhost` 或 `*`

---

## 📊 第三部分：功能测试（强烈建议）

### 6. 核心功能测试

在生产环境（或与生产环境相同的配置）中测试：

- [ ] 用户注册功能正常
- [ ] 邮箱验证码能正常接收
- [ ] 用户登录功能正常
- [ ] 聊天功能正常（已登录用户）
- [ ] 游客试聊功能正常
- [ ] 管理后台能正常访问（使用管理员邮箱登录）

### 7. 限流测试

- [ ] 登录接口限流生效（10 分钟内最多 15 次）
- [ ] 游客聊天限流生效（10 分钟内最多 12 次）

---

## 💾 第四部分：数据备份（强烈建议）

### 8. 备份策略

- [ ] 测试备份脚本：`bash backend/backup_supabase.sh`
- [ ] 设置定时备份（推荐使用 cron 或 1Panel 计划任务）：
  ```bash
  # 编辑 crontab
  crontab -e

  # 添加每天凌晨 3 点备份
  0 3 * * * /opt/aifriend/backend/backup_supabase.sh >> /opt/aifriend/logs/backup.log 2>&1
  ```
- [ ] 确认备份文件保存在 `/opt/aifriend/backups/`
- [ ] 参考 `docs/DATABASE_BACKUP_GUIDE.md` 了解更多

---

## 🌐 第五部分：部署准备（根据部署方式）

### 9. 服务器配置

- [ ] Python 3.10+ 已安装
- [ ] 依赖包已安装：`pip install -r backend/requirements.txt`
  - 注意：头像上传功能需要额外安装 `python-multipart`（已包含在 requirements.txt 中）
- [ ] 防火墙已开放必要端口（80, 443, 8000）
- [ ] `avatars/` 目录已创建且权限正确（应用需要读写权限）
- [ ] `covers/` 目录已创建（角色封面存储）
- [ ] **systemd 服务已配置**（推荐）或进程管理工具已设置
- [ ] **OpenResty/Nginx 配置**：
  - [ ] 静态文件 root 指向正确目录
  - [ ] `/api` 反向代理到 `:8000`
  - [ ] **安全规则**：隐藏文件（`.`开头）已被屏蔽
  - [ ] **敏感目录**（backend/, docs/, tests/等）已被屏蔽
  - [ ] **WAF 状态正常**（如使用 1Panel OpenResty，确认 WAF 文件存在或已禁用）
  - [ ] **Docker 卷挂载**：前端文件在容器可访问的路径下
  - [ ] **SSE 流式输出**：`/api` location 已设置 `proxy_buffering off; proxy_cache off;`
  - [ ] **图片缓存**：静态图片资源已配置长期缓存（30d + `Cache-Control: public, immutable`）

### 10. 进程管理（推荐）

使用进程管理工具保持应用运行：

**选项 A：使用 systemd（Linux）**
```bash
# 创建服务文件
sudo nano /etc/systemd/system/aifriend.service
```

**选项 B：使用 PM2（跨平台）**
```bash
npm install -g pm2
pm2 start "python backend/main.py" --name aifriend
pm2 save
pm2 startup
```

**选项 C：使用 screen（简单方式）**
```bash
screen -S aifriend
cd backend && python main.py
# 按 Ctrl+A 然后 D 退出 screen
```

---

## 📈 第六部分：监控和日志（可选但推荐）

### 11. 日志管理

- [ ] 确认日志正常输出
- [ ] 定期检查日志文件大小
- [ ] 考虑使用日志轮转（logrotate）

### 12. 监控

- [ ] 设置健康检查监控（定期访问 `/api/health`）
- [ ] 监控服务器资源使用（CPU、内存、磁盘）
- [ ] 监控数据库文件大小

---

## ✅ 上线后验证

部署完成后，立即进行以下验证：

1. [ ] 访问前端页面，确认能正常加载
2. [ ] 注册一个测试账号，确认邮件能收到
3. [ ] 登录并测试聊天功能
4. [ ] 使用管理员账号登录后台
5. [ ] 检查 `/api/health` 端点状态
6. [ ] 查看服务器日志，确认没有错误

---

## 🆘 常见问题

### Q1: 启动时提示缺少环境变量怎么办？
A: 检查 `backend/.env` 文件，参考 `.env.example` 补充缺失的配置。

### Q2: 邮件发送失败怎么办？
A: 检查 `RESEND_API_KEY` 是否正确，Resend 免费版每天限制 100 封邮件。

### Q3: CORS 错误怎么办？
A: 确认 `ALLOWED_ORIGINS` 包含了前端的真实域名（包括协议和端口）。

### Q4: 如何查看日志？
A: 日志会输出到控制台，建议使用进程管理工具重定向到文件。

---

## 📞 需要帮助？

如果遇到问题，请检查：
1. 服务器日志输出
2. `/api/health` 端点返回的状态
3. 浏览器控制台的错误信息

祝你上线顺利！🎉
