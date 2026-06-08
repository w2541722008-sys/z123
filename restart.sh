#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

TARGET="${1:-backend}"

usage() {
  echo "用法: bash restart.sh [backend|frontend|all]"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "❌ 缺少命令: $1"
    exit 1
  }
}

stop_processes() {
  local pattern="$1"
  local name="$2"
  local pids
  pids="$(pgrep -f "$pattern" || true)"
  if [[ -z "$pids" ]]; then
    echo "✅ $name 未运行"
    return
  fi

  echo "⏹ 停止 $name"
  while read -r pid; do
    [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null || true
  done <<< "$pids"
  sleep 2

  pids="$(pgrep -f "$pattern" || true)"
  if [[ -n "$pids" ]]; then
    while read -r pid; do
      [[ -n "$pid" ]] && kill -KILL "$pid" 2>/dev/null || true
    done <<< "$pids"
  fi
}

restart_backend() {
  echo "▶ 重启后端"
  require_cmd python3

  if command -v systemctl >/dev/null 2>&1 && systemctl is-enabled aifriend >/dev/null 2>&1; then
    echo "🔄 使用 systemd 重启 aifriend"
    sudo systemctl restart aifriend
    sleep 5
    if systemctl is-active aifriend >/dev/null 2>&1; then
      echo "✅ systemd 后端启动成功"
      return
    fi
    echo "❌ systemd 后端启动失败"
    journalctl -u aifriend --no-pager -n 30 || true
    exit 1
  fi

  stop_processes "uvicorn main:app" "后端"

  if [[ ! -d "$BACKEND_DIR/venv" ]]; then
    python3 -m venv "$BACKEND_DIR/venv"
    "$BACKEND_DIR/venv/bin/pip" install -r "$BACKEND_DIR/requirements.txt" -q
  fi

  if [[ -f "$BACKEND_DIR/.env" ]]; then
    set -a
    # 逐行读取 .env，跳过注释和空行，处理含特殊字符的值
    while IFS='=' read -r key value; do
      key="${key#export }"
      # 跳过注释和空行
      [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
      # 去除值两端引号
      value="${value#\"}" ; value="${value%\"}"
      value="${value#\'}" ; value="${value%\'}"
      export "$key=$value"
    done < "$BACKEND_DIR/.env"
    set +a
  fi

  cd "$BACKEND_DIR"
  LOG_FILE="/var/log/aifriend.log"
  # 确保日志文件可写
  if [[ ! -f "$LOG_FILE" ]]; then
    touch "$LOG_FILE" 2>/dev/null || LOG_FILE="$BACKEND_DIR/aifriend.log"
  elif [[ ! -w "$LOG_FILE" ]]; then
    LOG_FILE="$BACKEND_DIR/aifriend.log"
  fi
  nohup "$BACKEND_DIR/venv/bin/python3" -m uvicorn main:app --host 127.0.0.1 --port 8000 >> "$LOG_FILE" 2>&1 &
  sleep 3

  if pgrep -f "uvicorn main:app" >/dev/null 2>&1; then
    echo "✅ 后端启动成功"
  else
    echo "❌ 后端启动失败"
    tail -n 30 /var/log/aifriend.log || true
    exit 1
  fi
}

restart_frontend() {
  echo "▶ 前端静态文件由 Nginx 托管，无需单独重启"
  echo "  如需本地预览：cd $FRONTEND_DIR && npx http-server -p 8080 -c-1"
}

show_status() {
  echo "--- 当前状态 ---"
  if pgrep -f "uvicorn main:app" >/dev/null 2>&1; then
    echo "后端: 运行中"
  else
    echo "后端: 未运行"
  fi
}

main() {
  case "$TARGET" in
    backend)
      restart_backend
      ;;
    frontend)
      restart_frontend
      ;;
    all)
      restart_backend
      restart_frontend
      ;;
    *)
      usage
      exit 1
      ;;
  esac

  show_status
}

main "$@"
