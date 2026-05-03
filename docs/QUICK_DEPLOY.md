# 快速部署

```bash
cd /Users/jjj/aifriend
bash deploy.sh
```

## deploy.sh 流程

1. 检查 SSH 连接
2. 本地门禁（pytest + 前端测试）
3. 远端备份（自动清理旧备份，只保留最新1份）
4. rsync 同步到 `/opt/aifriend`
5. 远端执行 Alembic 数据库迁移
6. 远端重启 uvicorn + 健康检查

## 脚本说明

- `deploy.sh`：主部署脚本（唯一入口）
- `restart.sh`：服务重启脚本，支持 `backend|frontend|all`
- `verify_server.sh`：服务器状态与健康检查脚本
- `setup_server.sh`：服务器首次初始化脚本

## 部署后检查

- 健康检查：`https://lunawhisp.com/api/health`
- 服务日志：`ssh ubuntu@124.156.199.146 'tail -f /var/log/aifriend.log'`
- 服务器巡检：`ssh ubuntu@124.156.199.146 "cd /opt/aifriend && bash verify_server.sh"`
- systemd 状态：`ssh ubuntu@124.156.199.146 'sudo systemctl status aifriend'`

## 失败处理

- 测试失败：脚本会询问是否继续
- 迁移失败：002 迁移为幂等设计，可重跑 `alembic upgrade head`
- 重启失败：自动 fallback 到手动拉起 uvicorn
- 回滚：见 `DEPLOYMENT_GUIDE_VPS.md`

更多细节见：`DEPLOYMENT_GUIDE_VPS.md` 与 `DEPLOYMENT_CHECKLIST.md`。
