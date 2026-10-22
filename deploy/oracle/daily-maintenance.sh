#!/usr/bin/env bash
# 每日维护：备份数据库/上传目录 + 清理过期数据 + 可选异地同步。
# 用法：bash deploy/oracle/daily-maintenance.sh
#
# 建议 cron（每天 03:10）：
#   10 3 * * * /opt/mouke/deploy/oracle/daily-maintenance.sh >> "$HOME/mouke-maintenance.log" 2>&1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose --env-file .env.production -f deploy/docker-compose.yml)

"${COMPOSE[@]}" exec -T backend python backup.py \
  --db /data/mouke.db \
  --uploads /data/uploads \
  --out /data/backups \
  --keep-days 14

"${COMPOSE[@]}" exec -T backend python scripts/retention.py

# 可选：rclone remote 名为 mouke-offsite: 时，把备份同步到另一台机器/对象存储。
# 见 deploy/ORACLE_FREE.md 第 7 节；备份含用户数据，建议用 rclone crypt 远端。
if command -v rclone >/dev/null 2>&1 && rclone listremotes 2>/dev/null | grep -qx 'mouke-offsite:'; then
  EXPORT_DIR="$ROOT/.backup-export"
  rm -rf "$EXPORT_DIR"
  "${COMPOSE[@]}" cp backend:/data/backups "$EXPORT_DIR"
  rclone sync "$EXPORT_DIR" mouke-offsite:mouke-backups --fast-list
  rm -rf "$EXPORT_DIR"
  echo "备份已同步到 mouke-offsite:mouke-backups"
fi
