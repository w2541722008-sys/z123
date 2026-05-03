#!/usr/bin/env bash

set -Eeuo pipefail

SERVER_IP="${DEPLOY_SERVER_IP:-124.156.199.146}"
SERVER_USER="${DEPLOY_SERVER_USER:-ubuntu}"
SERVER_DIR="/opt/aifriend"
SSH_KEY="${DEPLOY_SSH_KEY:-$HOME/.ssh/id_ed25519_aifriend}"
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
  step "步骤 2/7: 执行本地门禁"
  pushd "$LOCAL_DIR/backend" >/dev/null

  local failed=0
  python3 -m pytest ../tests/ -q --ignore=../tests/integration || failed=1
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
  step "步骤 3/7: 备份服务器当前版本"
  ssh "${SSH_OPTS[@]}" "$SERVER_USER@$SERVER_IP" << 'ENDSSH'
set -Eeuo pipefail

backup_name="backup_$(date +%Y%m%d_%H%M%S)"

# 在项目目录内创建备份（/opt 可能只有 root 可写）
cd /opt/aifriend
cp -r . "../aifriend_$backup_name" 2>/dev/null || \
  cp -r . "$HOME/aifriend_$backup_name"
echo "备份完成: aifriend_$backup_name"

# 只保留最新1份备份，删除旧的
ls -d /opt/aifriend_backup_* /opt/aifriend_20* "$HOME"/aifriend_20* 2>/dev/null | sort | head -n -1 | xargs rm -rf 2>/dev/null || true
ENDSSH
  echo "✅ 备份完成（旧备份已自动清理）"
  echo
}

sync_files() {
  step "步骤 4/7: 同步文件"
  rsync -avz --delete --checksum \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='.ruff_cache' \
    --exclude='*.pyc' \
    --exclude='node_modules' \
    --exclude='.env' \
    --exclude='.env.*' \
    --exclude='.venv*' \
    --exclude='venv' \
    --exclude='*.log' \
    --exclude='.DS_Store' \
    --exclude='.trae' \
    --exclude='.codebuddy' \
    --exclude='.server_config' \
    --exclude='.coverage' \
    --exclude='*.tar.gz' \
    --exclude='admin.yaml' \
    --exclude='aifriend.conf' \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    "$LOCAL_DIR/" \
    "$SERVER_USER@$SERVER_IP:$SERVER_DIR/"
  echo "✅ 同步完成"
  echo
}

restart_remote() {
  step "步骤 5/7: 重启服务"
  ssh "${SSH_OPTS[@]}" "$SERVER_USER@$SERVER_IP" << 'ENDSSH'
set -Eeuo pipefail

cd /opt/aifriend
find backend -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

cd backend
if [[ -f requirements.txt ]]; then
  pip3 install -r requirements.txt --quiet --break-system-packages 2>/dev/null || \
  pip3 install -r requirements.txt --quiet 2>/dev/null || true
fi

# 执行数据库迁移（Alembic）
if [[ -f alembic.ini ]]; then
  echo "🔄 执行数据库迁移..."
  /opt/aifriend/backend/venv/bin/python3 -m alembic upgrade head 2>/dev/null || \
  python3 -m alembic upgrade head 2>/dev/null || \
  echo "⚠️ 数据库迁移失败，请手动检查"
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
ENDSSH
  echo
}


health_check() {
  step "步骤 6/7: 健康检查门禁"
  local http_code
  http_code=$(ssh "${SSH_OPTS[@]}" "$SERVER_USER@$SERVER_IP" \
    'curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health 2>/dev/null || echo "000"')

  if [[ "$http_code" == "200" ]]; then
    echo "✅ 健康检查通过 (HTTP $http_code)"
  else
    echo "❌ 健康检查失败 (HTTP $http_code)"
    echo "⚠️  服务可能需要更多时间启动，等待 10 秒后重试..."
    sleep 10
    http_code=$(ssh "${SSH_OPTS[@]}" "$SERVER_USER@$SERVER_IP" \
      'curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health 2>/dev/null || echo "000"')
    if [[ "$http_code" == "200" ]]; then
      echo "✅ 健康检查通过 (HTTP $http_code)"
    else
      echo "❌ 健康检查持续失败 (HTTP $http_code)"
      echo "⚠️  建议执行回滚: bash rollback.sh"
      echo "⚠️  查看日志: ssh $SERVER_USER@$SERVER_IP 'tail -50 /var/log/aifriend.log'"
      return 1
    fi
  fi
  echo
}

print_finish() {
  step "步骤 7/7: 输出结果"
  echo "✅ 部署完成"
  echo "🌐 访问: https://lunawhisp.com/"
  echo "🔍 健康检查: https://lunawhisp.com/api/health"
  echo "📋 日志: ssh $SERVER_USER@$SERVER_IP 'tail -f /var/log/aifriend.log'"
  echo "⏪ 回滚: bash rollback.sh"
}

main() {
  print_header
  check_prerequisites
  check_ssh
  run_local_checks
  backup_remote
  sync_files
  restart_remote
  health_check
  print_finish
}

main "$@"
