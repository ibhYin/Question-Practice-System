#!/usr/bin/env bash
# 数据库备份：mysqldump 全库 → gzip 存 data/backups/，保留最近 10 份
# 建议加入 crontab 每日自动执行：
#   crontab -e
#   0 2 * * * /Volumes/xiaoPai/Documents/MySQL+Redis/scripts/backup.sh >> /tmp/interview_backup.log 2>&1
set -e
cd "$(dirname "$0")/.."

BACKUP_DIR="data/backups"
STAMP=$(date +%Y%m%d_%H%M%S)
FILE="$BACKUP_DIR/interview_$STAMP.sql.gz"

mkdir -p "$BACKUP_DIR"

# 从 .env 读取连接信息
DB_USER=$(grep '^MYSQL_USER=' .env | cut -d= -f2)
DB_PASS=$(grep '^MYSQL_PASSWORD=' .env | cut -d= -f2)
DB_NAME=$(grep '^MYSQL_DATABASE=' .env | cut -d= -f2)

echo "==> 备份 $DB_NAME → $FILE"
docker exec interview-mysql mysqldump -u"$DB_USER" -p"$DB_PASS" \
    --single-transaction --routines --triggers "$DB_NAME" | gzip > "$FILE"

# 同步智能备份的时间戳，避免 24h 内被自动任务重复备份
docker exec interview-redis redis-cli SET backup:last_ts "$(date +%s)" >/dev/null 2>&1 || true

SIZE=$(du -h "$FILE" | cut -f1)
echo "    完成（$SIZE）"

# 只保留最近 10 份
ls -t "$BACKUP_DIR"/interview_*.sql.gz 2>/dev/null | tail -n +11 | while read -r old; do
    rm -f "$old"
    echo "    清理旧备份：$old"
done
echo "✅ 备份完成"
