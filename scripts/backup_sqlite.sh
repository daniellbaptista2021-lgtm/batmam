#!/bin/bash
# Backup automatizado do SQLite — Clow Platform
# Instalar no cron: crontab -e
#   0 */6 * * * /root/batmam/scripts/backup_sqlite.sh >> /var/log/clow-backup.log 2>&1
#
# Faz backup a cada execucao, mantém os ultimos 30 dias.

set -euo pipefail

# Config
DB_DIR="/root/.clow"
BACKUP_DIR="/root/.clow/backups"
RETENTION_DAYS=30
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Iniciando backup SQLite..."

# Backup de todos os .db encontrados
backup_count=0
for db_file in $(find "$DB_DIR" -maxdepth 2 -name "*.db" -type f 2>/dev/null); do
    db_name=$(basename "$db_file" .db)
    backup_file="$BACKUP_DIR/${db_name}_${DATE}.db"

    # Usa sqlite3 .backup para consistência (hot backup seguro)
    if command -v sqlite3 &>/dev/null; then
        sqlite3 "$db_file" ".backup '$backup_file'"
    else
        cp "$db_file" "$backup_file"
    fi

    # Comprime
    if command -v gzip &>/dev/null; then
        gzip "$backup_file"
        backup_file="${backup_file}.gz"
    fi

    size=$(du -sh "$backup_file" 2>/dev/null | cut -f1)
    echo "  OK: $db_name -> $(basename $backup_file) ($size)"
    backup_count=$((backup_count + 1))
done

# Backup do diretório de dados (data/)
DATA_DIR="/root/batmam/data"
if [ -d "$DATA_DIR" ]; then
    data_backup="$BACKUP_DIR/data_${DATE}.tar.gz"
    tar -czf "$data_backup" -C "$(dirname $DATA_DIR)" "$(basename $DATA_DIR)" 2>/dev/null || true
    size=$(du -sh "$data_backup" 2>/dev/null | cut -f1)
    echo "  OK: data/ -> $(basename $data_backup) ($size)"
    backup_count=$((backup_count + 1))
fi

# Limpa backups antigos
deleted=$(find "$BACKUP_DIR" -type f -mtime +${RETENTION_DAYS} -delete -print 2>/dev/null | wc -l)

echo "[$(date)] Backup concluido: $backup_count arquivo(s), $deleted antigo(s) removido(s)"
echo "  Diretorio: $BACKUP_DIR"
echo "  Retencao: ${RETENTION_DAYS} dias"
