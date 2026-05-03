# 快速部署

```bash
bash deploy.sh
```

## deploy.sh 流程

1. 检查 SSH 连接
2. 本地门禁（pytest + 前端测试）
3. 远端备份（自动清理旧备份）
4. rsync 同步到 `/opt/aifriend`
5. 远端 Alembic 迁移 + 重启 uvicorn
6. 健康检查门禁（失败提示回滚）
7. 输出结果

## 脚本说明

- `deploy.sh`：主部署脚本（唯一入口）
- `restart.sh`：服务重启，支持 `backend|frontend|all`
- `rollback.sh`：回滚到指定备份
- `setup_server.sh`：服务器首次初始化
- `verify_server.sh`：服务器状态巡检

## 部署后检查

- 健康检查：`https://lunawhisp.com/api/health`
- 服务日志：`tail -f /var/log/aifriend.log`
- systemd 状态：`sudo systemctl status aifriend`

## 失败处理

- 测试失败：脚本询问是否继续
- 迁移失败：002/003 幂等设计，可重跑 `alembic upgrade head`
- 重启失败：自动 fallback 到手动拉起 uvicorn
- 回滚：`bash rollback.sh`

详见：`DEPLOYMENT_GUIDE_VPS.md` 与 `DEPLOYMENT_CHECKLIST.md`。
