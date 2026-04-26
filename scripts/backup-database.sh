#!/bin/bash
set -e

# AscenAI Production Database Backup Script
# Usage: ./backup-database.sh [--verify] [--encrypt]

BACKUP_DIR="./backups"
RETENTION_DAYS=7
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/ascenai_backup_$TIMESTAMP.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "🔄 Starting database backup at $(date)"

# Create compressed backup
docker compose exec -T postgres pg_dump -U ascenai ascenai | gzip > "$BACKUP_FILE"

echo "✅ Backup created: $BACKUP_FILE"
echo "   Size: $(du -h $BACKUP_FILE | cut -f1)"

# Verify backup if requested
if [ "$1" = "--verify" ] || [ "$2" = "--verify" ]; then
    echo "🔍 Verifying backup integrity..."
    if gzip -t "$BACKUP_FILE"; then
        echo "✅ Backup verification passed"
    else
        echo "❌ Backup verification FAILED"
        rm -f "$BACKUP_FILE"
        exit 1
    fi
fi

# Encrypt backup if requested
if [ "$1" = "--encrypt" ] || [ "$2" = "--encrypt" ]; then
    if [ -z "$BACKUP_ENCRYPTION_KEY" ]; then
        echo "⚠️  BACKUP_ENCRYPTION_KEY not set - skipping encryption"
    else
        echo "🔐 Encrypting backup..."
        openssl enc -aes-256-cbc -salt -in "$BACKUP_FILE" -out "$BACKUP_FILE.enc" -k "$BACKUP_ENCRYPTION_KEY"
        rm -f "$BACKUP_FILE"
        BACKUP_FILE="$BACKUP_FILE.enc"
        echo "✅ Backup encrypted"
    fi
fi

# Clean up old backups
echo "🧹 Cleaning up backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -type f -name "ascenai_backup_*" -mtime +$RETENTION_DAYS -delete

echo "✅ Backup completed successfully at $(date)"
echo "📦 Final backup file: $BACKUP_FILE"
