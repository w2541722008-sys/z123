#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="/opt/aifriend"
ENV_FILE="$PROJECT_DIR/backend/.env"
BACKUP_DIR="$PROJECT_DIR/backups"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "❌ 缺少命令: $1"
    exit 1
  }
}

main() {
  require_cmd pg_dump
  require_cmd gzip

  if [[ ! -f "$ENV_FILE" ]]; then
    echo "❌ 找不到环境变量文件: $ENV_FILE"
    exit 1
  fi

  set -a
  source "$ENV_FILE"
  set +a

  if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "❌ DATABASE_URL 未配置"
    exit 1
  fi

  mkdir -p "$BACKUP_DIR"

  local ts backup_sql backup_gz
  ts="$(date +%Y%m%d_%H%M%S)"
  backup_sql="$BACKUP_DIR/backup_${ts}.sql"
  backup_gz="$backup_sql.gz"

  echo "开始备份数据库..."
  pg_dump "$DATABASE_URL" > "$backup_sql"
  gzip "$backup_sql"

  find "$BACKUP_DIR" -name "backup_*.sql.gz" -mtime +"$RETENTION_DAYS" -delete

  echo "✅ 备份完成: $backup_gz"
  echo "✅ 已清理 ${RETENTION_DAYS} 天前备份"
}

main "$@"

