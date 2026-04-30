# 快速部署（当前项目）

本项目的标准部署方式是直接执行根目录脚本：

```bash
cd /Users/jjj/aifriend
bash deploy.sh
```

## deploy.sh 实际流程

1. 校验 SSH 连通性（目标：`root@45.76.182.245`）
2. 运行本地门禁：
   - `python3 -m pytest ../tests/ -q`
   - `node ../tests/test_frontend_utils.js`
   - `node ../tests/check_admin_actions.js --strict --allow-list=../tests/admin_action_allowlist.json`
3. 远端创建备份：`/opt/backup_时间戳`
4. 使用 rsync 同步到 `/opt/aifriend`
5. 远端执行 `restart.sh`，并做健康检查 `http://localhost:8000/api/health`

## 失败处理

- 若测试失败，脚本会询问是否继续部署。
- 若重启脚本失败，会自动 fallback 到手动拉起 uvicorn。

## 推荐操作

- 部署前先确认工作区变更可追踪（已提交或已备份）。
- 部署后检查：
  - 线上健康检查：`https://lunawhisp.com/api/health`
  - 服务日志：`tail -f /var/log/aifriend.log`
- 可选执行服务器巡检脚本：
  - `ssh root@45.76.182.245 "cd /opt/aifriend && bash verify_server.sh"`

## 脚本说明

- `deploy.sh`：主部署脚本（唯一推荐入口）
- `restart.sh`：服务重启脚本，支持 `backend|frontend|all`
- `verify_server.sh`：服务器状态与健康检查脚本
- `deploy_to_server.sh`：兼容入口，内部转发到 `deploy.sh`

更多细节见：`DEPLOYMENT_GUIDE_VPS.md` 与 `DEPLOYMENT_CHECKLIST.md`。
