#!/usr/bin/env bash

set -Eeuo pipefail

# ============================================================
# AIFriend 回滚脚本
# 用法：bash rollback.sh [备份目录名]
# 示例：bash rollback.sh backup_20260503_143000
#       bash rollback.sh          # 回滚到最新备份
# ============================================================

SERVER_IP="124.156.199.146"
SERVER_USER="ubuntu"
SERVER_DIR="/opt/aifriend"
SSH_KEY="${HOME}/.ssh/id_ed25519_aifriend"

SSH_OPTS=(-i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no)

TARGET_BACKUP="${1:-}"

print_header() {
  echo "=========================================="
  echo "⏪ AIFriend 回滚工具"
  echo "=========================================="
  echo
}

find_latest_backup() {
  ssh "${SSH_OPTS[@]}" "$SERVER_USER@$SERVER_IP" << 'ENDSSH'
set -Eeuo pipefail
latest=$(ls -d /opt/aifriend_backup_* 2>/dev/null | sort | tail -1)
if [[ -z "$latest" ]]; then
  echo "ERROR:没有找到任何备份" >&2
  exit 1
fi
basename "$latest"
ENDSSH
}

validate_backup() {
  local backup_name="$1"
  ssh "${SSH_OPTS[@]}" "$SERVER_USER@$SERVER_IP" << ENDSSH
set -Eeuo pipefail
if [[ ! -d "/opt/$backup_name" ]]; then
  echo "ERROR:备份目录 /opt/$backup_name 不存在" >&2
  exit 1
fi
echo "✅ 备份目录验证通过: /opt/$backup_name"
ENDSSH
}

do_rollback() {
  local backup_name="$1"
  echo "📌 目标备份: $backup_name"
  echo

  ssh "${SSH_OPTS[@]}" "$SERVER_USER@$SERVER_IP" << ENDSSH
set -Eeuo pipefail
BACKUP_DIR="/opt/$backup_name"
CURRENT_DIR="/opt/aifriend"

if [[ ! -d "\$BACKUP_DIR" ]]; then
  echo "❌ 备份目录不存在: \$BACKUP_DIR"
  exit 1
fi

echo "⏹ 停止当前服务..."
cd /opt/aifriend
if systemctl is-active aifriend >/dev/null 2>&1; then
  sudo systemctl stop aifriend
  echo "✅ systemd 服务已停止"
else
  pkill -f "uvicorn main:app" || true
  sleep 2
  echo "✅ 进程已停止"
fi

echo "📦 替换当前版本为备份..."
# 保留当前 .env 和 data 目录
cp -r "\$CURRENT_DIR/backend/.env" "/tmp/aifriend_env_backup" 2>/dev/null || true
cp -r "\$CURRENT_DIR/backend/data" "/tmp/aifriend_data_backup" 2>/dev/null || true

rm -rf "\$CURRENT_DIR"
cp -r "\$BACKUP_DIR" "\$CURRENT_DIR"

# 恢复 .env 和 data
cp "/tmp/aifriend_env_backup" "\$CURRENT_DIR/backend/.env" 2>/dev/null || true
if [[ -d "/tmp/aifriend_data_backup" ]]; then
  cp -r "/tmp/aifriend_data_backup" "\$CURRENT_DIR/backend/data" 2>/dev/null || true
fi
rm -f "/tmp/aifriend_env_backup" 2>/dev/null || true
rm -rf "/tmp/aifriend_data_backup" 2>/dev/null || true

echo "🔄 重启服务..."
cd "\$CURRENT_DIR/backend"
find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

if systemctl is-enabled aifriend >/dev/null 2>&1; then
  sudo systemctl start aifriend
  sleep 5
  if systemctl is-active aifriend >/dev/null 2>&1; then
    echo "✅ systemd 服务已启动"
  else
    echo "❌ systemd 服务启动失败"
    journalctl -u aifriend --no-pager -n 20 || true
    exit 1
  fi
else
  # 降级：直接启动
  if [[ -f .env ]]; then
    set -a
    source .env
    set +a
  fi
  nohup /opt/aifriend/backend/venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 > /var/log/aifriend.log 2>&1 &
  sleep 3
fi

echo "🔍 健康检查..."
sleep 2
HTTP_CODE=\$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health 2>/dev/null || echo "000")
if [[ "\$HTTP_CODE" == "200" ]]; then
  echo "✅ 健康检查通过 (HTTP \$HTTP_CODE)"
else
  echo "❌ 健康检查失败 (HTTP \$HTTP_CODE)"
  echo "⚠️  服务可能需要更多时间启动，请手动检查: curl http://localhost:8000/api/health"
fi

echo
echo "✅ 回滚完成: \$backup_name"
ENDSSH
}

main() {
  print_header

  # 确定回滚目标
  if [[ -z "$TARGET_BACKUP" ]]; then
    echo "📌 未指定备份，将使用最新备份..."
    TARGET_BACKUP=$(find_latest_backup)
    if [[ -z "$TARGET_BACKUP" ]]; then
      echo "❌ 未找到可用备份"
      exit 1
    fi
    echo "   最新备份: $TARGET_BACKUP"
  fi

  # 验证备份存在
  validate_backup "$TARGET_BACKUP"

  # 确认回滚
  echo
  echo "⚠️  即将回滚到: $TARGET_BACKUP"
  echo "⚠️  当前版本将被替换，当前 .env 和 data 目录会保留"
  read -r -p "确认回滚？(y/N): " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "已取消"
    exit 0
  fi
  echo

  do_rollback "$TARGET_BACKUP"
}

main "$@"
