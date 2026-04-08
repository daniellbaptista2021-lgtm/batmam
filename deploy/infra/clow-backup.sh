#!/bin/bash
# Clow Daily Backup - DBs + configs
BACKUP_DIR="/root/backups/clow"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$BACKUP_DIR/$DATE"
RETENTION_DAYS=30

mkdir -p "$BACKUP_PATH"

# Backup databases
cp /root/batmam/data/clow.db "$BACKUP_PATH/clow.db" 2>/dev/null
cp /root/.clow/teams.db "$BACKUP_PATH/teams.db" 2>/dev/null
cp /root/.clow/autopilot.db "$BACKUP_PATH/autopilot.db" 2>/dev/null

# Backup configs
cp /root/.clow/app/.env "$BACKUP_PATH/app.env"
cp /root/batmam/deploy/.env "$BACKUP_PATH/deploy.env"
cp /etc/nginx/sites-available/vllm-proxy "$BACKUP_PATH/nginx-vllm.conf"
cp /etc/nginx/sites-available/clow-https "$BACKUP_PATH/nginx-clow.conf" 2>/dev/null
cp /etc/nginx/vllm_target "$BACKUP_PATH/vllm_target"

# Compress
tar -czf "$BACKUP_DIR/clow-backup-$DATE.tar.gz" -C "$BACKUP_DIR" "$DATE"
rm -rf "$BACKUP_PATH"

# Cleanup old backups
find "$BACKUP_DIR" -name "clow-backup-*.tar.gz" -mtime +$RETENTION_DAYS -delete

echo "$(date) Backup complete: clow-backup-$DATE.tar.gz ($(du -sh $BACKUP_DIR/clow-backup-$DATE.tar.gz | cut -f1))" >> /var/log/clow-backup.log
