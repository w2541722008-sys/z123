#!/usr/bin/env bash

set -Eeuo pipefail

SERVER_IP="45.76.182.245"
SERVER_USER="root"
SERVER_DIR="/opt/aifriend"
SSH_KEY="/Users/jjj/.ssh/id_ed25519_aifriend"
LOCAL_DIR="/Users/jjj/aifriend"

SSH_OPTS=(-i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no)

print_header() {
  echo "=========================================="
  echo "🚀 AIFriend 一键部署工具"
  echo "=========================================="
  echo
}

step() {
  echo "📌 $1"
}

check_prerequisites() {
  local missing=()
  for cmd in ssh rsync python3 node; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
  done
  if ((${#missing[@]} > 0)); then
    echo "❌ 缺少依赖命令: ${missing[*]}"
    exit 1
  fi
}

check_ssh() {
  step "步骤 1/6: 检查服务器连接"
  if ssh "${SSH_OPTS[@]}" "$SERVER_USER@$SERVER_IP" "echo ok" >/dev/null 2>&1; then
    echo "✅ 服务器连接正常"
  else
    echo "❌ 无法连接服务器: $SERVER_USER@$SERVER_IP"
    exit 1
  fi
  echo
}

run_local_checks() {
  step "步骤 2/6: 执行本地门禁"
  pushd "$LOCAL_DIR/backend" >/dev/null

  local failed=0
  python3 -m pytest ../tests/ -q || failed=1
  node ../tests/test_frontend_utils.js || failed=1
  node ../tests/check_admin_actions.js --strict --allow-list=tests/admin_action_allowlist.json || failed=1

  popd >/dev/null

  if [[ "$failed" -eq 0 ]]; then
    echo "✅ 本地门禁通过"
  else
    echo "⚠️ 本地门禁失败，是否继续部署？(y/n)"
    read -r confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
      echo "部署已取消"
      exit 1
    fi
  fi
  echo
}

backup_remote() {
  step "步骤 3/6: 备份服务器当前版本"
  local backup_name="backup_$(date +%Y%m%d_%H%M%S)"
  ssh "${SSH_OPTS[@]}" "$SERVER_USER@$SERVER_IP" "cd /opt && cp -r aifriend $backup_name && echo 备份完成:$backup_name"
  echo "✅ 备份完成"
  echo
}

sync_files() {
  step "步骤 4/6: 同步文件"
  rsync -avz --delete \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='*.pyc' \
    --exclude='node_modules' \
    --exclude='.env' \
    --exclude='venv' \
    --exclude='*.log' \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    "$LOCAL_DIR/" \
    "$SERVER_USER@$SERVER_IP:$SERVER_DIR/"
  echo "✅ 同步完成"
  echo
}

restart_remote() {
  step "步骤 5/6: 重启服务"
  ssh "${SSH_OPTS[@]}" "$SERVER_USER@$SERVER_IP" << 'ENDSSH'
set -Eeuo pipefail

cd /opt/aifriend
find backend -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

cd backend
if [[ -f requirements.txt ]]; then
  pip3 install -r requirements.txt --quiet --break-system-packages 2>/dev/null || \
  pip3 install -r requirements.txt --quiet 2>/dev/null || true
fi

cd /opt/aifriend
if ! bash restart.sh; then
  echo "restart.sh 执行失败，使用降级重启逻辑"
  pkill -f uvicorn || true
  sleep 2
  cd /opt/aifriend/backend
  nohup /opt/aifriend/backend/venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 > /var/log/aifriend.log 2>&1 &
fi

sleep 3
echo "=== 服务状态 ==="
ps aux | grep uvicorn | grep -v grep | head -1 || echo "❌ 服务未启动"
echo "=== 健康检查 ==="
curl -s http://localhost:8000/api/health || echo "❌ 健康检查失败"
ENDSSH
  echo
}

print_finish() {
  step "步骤 6/6: 输出结果"
  echo "✅ 部署完成"
  echo "🌐 访问: https://lunawhisp.com/"
  echo "🔍 健康检查: https://lunawhisp.com/api/health"
  echo "📋 日志: ssh root@45.76.182.245 'tail -f /var/log/aifriend.log'"
}

main() {
  print_header
  check_prerequisites
  check_ssh
  run_local_checks
  backup_remote
  sync_files
  restart_remote
  print_finish
}

main "$@"
