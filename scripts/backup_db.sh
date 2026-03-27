#!/bin/bash
# bookbug DB 백업 → iCloud Drive, 최근 30개 보관

DB="/Users/yong/.bookbug/bookbug.db"
BACKUP_DIR="/Users/yong/Library/Mobile Documents/com~apple~CloudDocs/bookbug-backup"
DATE=$(date +%Y%m%d-%H%M%S)
DEST="$BACKUP_DIR/bookbug-$DATE.db"

# iCloud 디렉토리 확인
mkdir -p "$BACKUP_DIR"

# SQLite 안전 복사 (WAL 포함)
sqlite3 "$DB" ".backup '$DEST'"

if [ $? -eq 0 ]; then
    echo "백업 완료: $DEST"
else
    echo "백업 실패" >&2
    exit 1
fi

# 30개 초과분 삭제 (오래된 것부터)
ls -t "$BACKUP_DIR"/bookbug-*.db | tail -n +31 | xargs rm -f

echo "보관 중: $(ls "$BACKUP_DIR"/bookbug-*.db | wc -l | tr -d ' ')개"
