# 上线检查清单

## 配置

- [ ] `backend/.env` 已配置并在服务器生效
- [ ] `ALLOWED_ORIGINS` 已替换为生产域名
- [ ] `DATABASE_URL` 指向正确 Supabase 实例
- [ ] `ADMIN_EMAILS` 包含管理员邮箱

## 数据库

- [ ] 已执行 `docs/supabase_schema.sql`
- [ ] 已执行 `docs/migrations/001_add_message_versions.sql`
- [ ] `chat_messages.versions` 字段存在

## 代码质量门禁

- [ ] `python3 -m pytest ../tests/ -q` 通过
- [ ] `node tests/test_frontend_utils.js` 通过
- [ ] `node tests/check_admin_actions.js --strict --allow-list=tests/admin_action_allowlist.json` 通过

## 服务与路由

- [ ] 访问 `/api/health` 返回 `status=ok` 或可解释的 `degraded`
- [ ] 访问 `/` 正常打开前端
- [ ] 访问 `/admin.html` 正常打开后台
- [ ] 关键 API 路由可访问（auth/chat/characters/billing）

## 运维

- [ ] 部署前已自动或手动备份当前版本
- [ ] 可查看运行日志：`/var/log/aifriend.log`
- [ ] 已验证回滚步骤可执行

## 上线后抽检

- [ ] 注册/登录/登出链路正常
- [ ] 聊天流式响应正常
- [ ] 管理后台用户与角色管理页面可用
- [ ] 订单创建/列表/取消流程可用

