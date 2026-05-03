# 上线检查清单

## 配置

- [ ] `backend/.env` 已配置并在服务器生效
- [ ] `ALLOWED_ORIGINS` 已替换为生产域名（`https://lunawhisp.com`）
- [ ] `DATABASE_URL` 指向正确 Supabase 实例
- [ ] `ADMIN_EMAILS` 包含管理员邮箱
- [ ] 邮件服务已配置（SMTP 或 Resend API）
- [ ] `AIFRIEND_API_KEY` 已设置为有效的 AI 模型密钥
- [ ] `ENV=production` + `DEBUG=false`

## 数据库

- [ ] 已执行 `alembic upgrade head` 完成全部迁移
- [ ] 确认 `001_initial_schema.py` 已创建全部 18 张表
- [ ] 确认 `002_text_to_timestamptz_jsonb.py` 已将时间列转为 timestamptz、JSON 列转为 jsonb
- [ ] 确认 `003_add_reset_code_attempt_count.py` 已添加 attempt_count 列（幂等）
- [ ] `chat_messages.versions` 字段存在（基线迁移已包含）

## 代码质量门禁

- [ ] `python3 -m pytest ../tests/ -q --ignore=../tests/integration` 通过
- [ ] `node tests/test_frontend_utils.js` 通过
- [ ] `node tests/check_admin_actions.js --strict --allow-list=tests/admin_action_allowlist.json` 通过

## 安全

- [ ] 所有用户输入有长度/格式限制（Pydantic Field max_length）
- [ ] 管理后台所有端点使用 `get_admin_user` 鉴权
- [ ] 无 `assert` 用于运行时校验
- [ ] 无硬编码密钥/API Key
- [ ] Cookie `Secure` 标志在生产环境生效
- [ ] 限流配置在高压下有效

## 缓存一致性

- [ ] 用户密码修改后 `invalidate_user()` 已调用
- [ ] 订单状态变更后 `invalidate_user()` 已调用
- [ ] 管理后台用户编辑后 `invalidate_user()` 已调用

## 服务与路由

- [ ] 访问 `/api/health` 返回 `status=ok` 或可解释的 `degraded`
- [ ] 访问 `/` 正常打开前端
- [ ] 访问 `/admin.html` 正常打开后台
- [ ] 关键 API 路由可访问（auth/chat/characters/billing）

## 运维

- [ ] 部署前已自动或手动备份当前版本
- [ ] 可查看运行日志：`/var/log/aifriend.log`
- [ ] 日志轮转已配置（`/etc/logrotate.d/aifriend`）
- [ ] 已验证回滚步骤可执行（`bash rollback.sh`）
- [ ] systemd 服务已启用（`sudo systemctl enable aifriend`）
- [ ] 部署后健康检查门禁通过

## 上线后抽检

- [ ] 注册/登录/登出链路正常
- [ ] 聊天流式响应正常
- [ ] 管理后台用户与角色管理页面可用
- [ ] 订单创建/列表/取消流程可用
- [ ] 修改密码后用户信息即时更新（缓存失效）
