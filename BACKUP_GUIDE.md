# Database Backup Guide

Complete guide for backing up your PGVectorRAGIndexer database to Google Drive.

## 🎯 Quick Start

### One-Time Setup

1. **Make scripts executable**:
```bash
chmod +x backup_database.sh restore_database.sh sync_to_gdrive.sh
```

2. **Install rclone** (for Google Drive sync):
```bash
sudo apt update
sudo apt install rclone
```

3. **Configure Google Drive**:
```bash
rclone config
```

Follow the prompts:
- Choose `n` for new remote
- Name it `gdrive`
- Choose `drive` for Google Drive
- Follow authentication steps
- Choose `1` for full access

### Daily Usage

**Backup and sync to Google Drive**:
```bash
./backup_database.sh && ./sync_to_gdrive.sh
```

That's it! Your database is backed up locally and synced to Google Drive.

---

## 📋 Detailed Instructions

### 1. Local Backup

**Create a backup**:
```bash
./backup_database.sh
```

This will:
- ✅ Create timestamped SQL backup in `./backups/`
- ✅ Update `latest_backup.sql` symlink
- ✅ Clean up backups older than 30 days
- ✅ Show backup size and statistics

**Backup location**:
```
./backups/
├── pgvector_backup_20250112_143022.sql
├── pgvector_backup_20250113_090015.sql
├── pgvector_backup_20250114_120530.sql
└── latest_backup.sql -> pgvector_backup_20250114_120530.sql
```

### 2. Sync to Google Drive

**First-time setup**:
```bash
# Install rclone
sudo apt install rclone

# Configure Google Drive
rclone config
```

**Sync backups**:
```bash
./sync_to_gdrive.sh
```

This will:
- ✅ Upload all backups to Google Drive
- ✅ Show progress and statistics
- ✅ Only upload changed files (efficient)
- ✅ Verify sync completed successfully

**Google Drive location**:
```
Google Drive/
└── PGVectorRAGIndexer/
    └── backups/
        ├── pgvector_backup_20250112_143022.sql
        ├── pgvector_backup_20250113_090015.sql
        └── pgvector_backup_20250114_120530.sql
```

### 3. Restore from Backup

**Restore latest backup**:
```bash
./restore_database.sh ./backups/latest_backup.sql
```

**Restore specific backup**:
```bash
./restore_database.sh ./backups/pgvector_backup_20250112_143022.sql
```

**Restore from Google Drive**:
```bash
# Download backups from Google Drive
rclone copy gdrive:PGVectorRAGIndexer/backups ./backups

# Restore
./restore_database.sh ./backups/latest_backup.sql
```

⚠️ **Warning**: Restore will replace ALL current data!

---

## 🤖 Automated Backups

### Option 1: Cron Job (Linux/WSL)

**Edit crontab**:
```bash
crontab -e
```

**Add daily backup at 2 AM**:
```bash
0 2 * * * cd /home/valginer0/projects/PGVectorRAGIndexer && ./backup_database.sh >> ./backups/backup.log 2>&1
```

**Add sync to Google Drive at 2:30 AM**:
```bash
30 2 * * * cd /home/valginer0/projects/PGVectorRAGIndexer && ./sync_to_gdrive.sh >> ./backups/sync.log 2>&1
```

**Common schedules**:
```bash
# Every day at 2 AM
0 2 * * * /path/to/backup_database.sh

# Every 6 hours
0 */6 * * * /path/to/backup_database.sh

# Every Sunday at 3 AM
0 3 * * 0 /path/to/backup_database.sh

# Every hour
0 * * * * /path/to/backup_database.sh
```

### Option 2: Windows Task Scheduler

1. Open **Task Scheduler**
2. Create **New Task**
3. **Trigger**: Daily at 2:00 AM
4. **Action**: Start a program
   - Program: `wsl`
   - Arguments: `bash -c "cd /home/valginer0/projects/PGVectorRAGIndexer && ./backup_database.sh && ./sync_to_gdrive.sh"`

### Option 3: Manual Script

Create `auto_backup.sh`:
```bash
#!/bin/bash
cd /home/valginer0/projects/PGVectorRAGIndexer
./backup_database.sh && ./sync_to_gdrive.sh
```

Run whenever needed:
```bash
./auto_backup.sh
```

---

## 🔧 Advanced Configuration

### Change Backup Retention

Edit `backup_database.sh`:
```bash
# Keep backups for 60 days instead of 30
RETENTION_DAYS=60
```

### Change Google Drive Path

Edit `sync_to_gdrive.sh`:
```bash
# Use different folder in Google Drive
GDRIVE_PATH="MyBackups/Database"
```

### Compress Backups

Add compression to save space:
```bash
# In backup_database.sh, change:
docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE.gz"
```

### Encrypt Backups

Add encryption for security:
```bash
# Backup with encryption
docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" | \
    gpg --symmetric --cipher-algo AES256 > "$BACKUP_FILE.gpg"

# Restore encrypted backup
gpg --decrypt "$BACKUP_FILE.gpg" | \
    docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME"
```

---

## 📊 Monitoring Backups

### Check Backup Status

**List all backups**:
```bash
ls -lh ./backups/
```

**Check backup size**:
```bash
du -sh ./backups/
```

**Verify latest backup**:
```bash
ls -lh ./backups/latest_backup.sql
```

### Check Google Drive Sync

**List files in Google Drive**:
```bash
rclone ls gdrive:PGVectorRAGIndexer/backups
```

**Check sync status**:
```bash
rclone check ./backups gdrive:PGVectorRAGIndexer/backups
```

**Show Google Drive usage**:
```bash
rclone about gdrive:
```

---

## 🆘 Troubleshooting

### Container Not Running

**Error**: "Container 'vector_rag_db' is not running!"

**Solution**:
```bash
docker-compose up -d
```

### rclone Not Found

**Error**: "rclone is not installed!"

**Solution**:
```bash
sudo apt update
sudo apt install rclone
```

### Google Drive Not Configured

**Error**: "Google Drive remote 'gdrive' not configured!"

**Solution**:
```bash
rclone config
# Follow prompts to add Google Drive
```

### Permission Denied

**Error**: "Permission denied: ./backup_database.sh"

**Solution**:
```bash
chmod +x backup_database.sh restore_database.sh sync_to_gdrive.sh
```

### Backup Failed

**Check container logs**:
```bash
docker logs vector_rag_db
```

**Check disk space**:
```bash
df -h
```

### Restore Failed

**Check backup file**:
```bash
head -n 20 ./backups/latest_backup.sql
```

**Verify database connection**:
```bash
docker exec vector_rag_db psql -U rag_user -d rag_vector_db -c "SELECT version();"
```

---

## 📁 Backup File Structure

### Backup Contains

- ✅ All document chunks and embeddings
- ✅ Document metadata
- ✅ Database schema and indexes
- ✅ pgvector extension configuration
- ✅ All custom views and triggers

### Backup Does NOT Contain

- ❌ Docker container configuration
- ❌ Application code
- ❌ Python dependencies
- ❌ Environment variables (.env file)

**Important**: Also backup your `.env` file separately!

---

## 🔐 Security Best Practices

1. **Encrypt sensitive backups**:
   ```bash
   gpg --symmetric backup.sql
   ```

2. **Secure Google Drive access**:
   - Use service account for automation
   - Enable 2FA on Google account
   - Limit rclone permissions

3. **Protect backup files**:
   ```bash
   chmod 600 ./backups/*.sql
   ```

4. **Regular testing**:
   - Test restore monthly
   - Verify backup integrity
   - Document restore procedures

5. **Multiple backup locations**:
   - Local backups
   - Google Drive
   - External hard drive
   - Cloud storage (S3, Azure, etc.)

---

## 📞 Support

For backup issues:
- Check logs in `./backups/backup.log`
- Review Docker container logs
- Verify disk space and permissions
- Contact: valginer0@gmail.com

---

**Last Updated**: 2025  
**Status**: Production Ready ✅
