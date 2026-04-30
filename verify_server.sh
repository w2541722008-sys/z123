#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/aifriend}"
HEALTH_URL_LOCAL="http://localhost:8000/api/health"
HEALTH_URL_PUBLIC="https://lunawhisp.com/api/health"

section() {
  echo
  echo "=== $1 ==="
}

check_cmd() {
  command -v "$1" >/dev/null 2>&1
}

section "环境信息"
python3 --version || true

section "项目路径"
if [[ -d "$PROJECT_DIR" ]]; then
  echo "✅ 存在: $PROJECT_DIR"
else
  echo "❌ 不存在: $PROJECT_DIR"
  exit 1
fi

section "依赖关键项"
if [[ -f "$PROJECT_DIR/backend/requirements.txt" ]]; then
  echo "✅ requirements.txt 存在"
else
  echo "❌ 缺少 requirements.txt"
fi

section "服务进程"
if pgrep -f "uvicorn main:app" >/dev/null 2>&1; then
  echo "✅ 检测到 uvicorn 进程"
  pgrep -fa "uvicorn main:app" | head -3
else
  echo "⚠️ 未检测到 uvicorn 进程"
fi

section "端口监听"
if check_cmd ss; then
  ss -tlnp | grep -E ":8000|:80|:443" || echo "⚠️ 未看到 8000/80/443 监听"
elif check_cmd netstat; then
  netstat -tlnp | grep -E ":8000|:80|:443" || echo "⚠️ 未看到 8000/80/443 监听"
else
  echo "⚠️ 未安装 ss/netstat"
fi

section "健康检查"
if check_cmd curl; then
  echo "本地: $HEALTH_URL_LOCAL"
  curl -fsS "$HEALTH_URL_LOCAL" || echo "❌ 本地健康检查失败"
  echo
  echo "公网: $HEALTH_URL_PUBLIC"
  curl -fsS "$HEALTH_URL_PUBLIC" || echo "❌ 公网健康检查失败"
else
  echo "❌ 缺少 curl"
fi

section "配置文件"
if [[ -f "$PROJECT_DIR/backend/.env" ]]; then
  echo "✅ backend/.env 存在"
  grep -q '^DATABASE_URL=' "$PROJECT_DIR/backend/.env" && echo "✅ DATABASE_URL 已配置" || echo "❌ DATABASE_URL 缺失"
  grep -q '^ALLOWED_ORIGINS=' "$PROJECT_DIR/backend/.env" && echo "✅ ALLOWED_ORIGINS 已配置" || echo "❌ ALLOWED_ORIGINS 缺失"
else
  echo "❌ backend/.env 不存在"
fi

section "日志尾部"
if [[ -f /var/log/aifriend.log ]]; then
  tail -n 20 /var/log/aifriend.log
else
  echo "⚠️ /var/log/aifriend.log 不存在"
fi

echo
echo "✅ 验证完成"

