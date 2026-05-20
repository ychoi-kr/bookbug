#!/bin/bash
# bookbug DB 백업, 최근 30개 보관

set -euo pipefail

DB="$HOME/.bookbug/bookbug.db"
BACKUP_DIR="$HOME/.bookbug/backups"
DATE=$(date +%Y%m%d-%H%M%S)
DEST="$BACKUP_DIR/bookbug-$DATE.db"

mkdir -p "$BACKUP_DIR"

# SQLite 안전 복사 (WAL 포함)
sqlite3 "$DB" ".backup '$DEST'"

echo "백업 완료: $DEST"

# 30개 초과분 삭제 (오래된 것부터)
ls -t "$BACKUP_DIR"/bookbug-*.db 2>/dev/null | tail -n +31 | xargs -r rm -f

echo "보관 중: $(ls "$BACKUP_DIR"/bookbug-*.db 2>/dev/null | wc -l | tr -d ' ')개"
