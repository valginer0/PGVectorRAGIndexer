#!/bin/bash

# PGVectorRAGIndexer Database Backup Script
# Backs up PostgreSQL database to timestamped SQL file

set -e  # Exit on error

# Configuration
CONTAINER_NAME="vector_rag_db"
DB_USER="rag_user"
DB_NAME="rag_vector_db"
BACKUP_DIR="./backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/pgvector_backup_${TIMESTAMP}.sql"
LATEST_LINK="${BACKUP_DIR}/latest_backup.sql"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== PGVectorRAGIndexer Database Backup ===${NC}"
echo "Timestamp: $(date)"
echo ""

# Create backup directory if it doesn't exist
if [ ! -d "$BACKUP_DIR" ]; then
    echo -e "${YELLOW}Creating backup directory: ${BACKUP_DIR}${NC}"
    mkdir -p "$BACKUP_DIR"
fi

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${RED}Error: Container '${CONTAINER_NAME}' is not running!${NC}"
    echo "Start it with: docker-compose up -d"
    exit 1
fi

# Perform backup
echo -e "${GREEN}Backing up database...${NC}"
docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP_FILE"

# Check if backup was successful
if [ $? -eq 0 ]; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo -e "${GREEN}✓ Backup successful!${NC}"
    echo "  File: $BACKUP_FILE"
    echo "  Size: $BACKUP_SIZE"
    
    # Create/update symlink to latest backup
    ln -sf "$(basename "$BACKUP_FILE")" "$LATEST_LINK"
    echo -e "${GREEN}✓ Latest backup link updated${NC}"
    
    # Count total backups
    BACKUP_COUNT=$(ls -1 "${BACKUP_DIR}"/pgvector_backup_*.sql 2>/dev/null | wc -l)
    echo ""
    echo "Total backups: $BACKUP_COUNT"
    
    # Show disk usage
    TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
    echo "Backup directory size: $TOTAL_SIZE"
    
else
    echo -e "${RED}✗ Backup failed!${NC}"
    exit 1
fi

# Optional: Clean up old backups (keep last 30 days)
RETENTION_DAYS=30
echo ""
echo -e "${YELLOW}Cleaning up backups older than ${RETENTION_DAYS} days...${NC}"
find "$BACKUP_DIR" -name "pgvector_backup_*.sql" -type f -mtime +${RETENTION_DAYS} -delete
DELETED_COUNT=$(find "$BACKUP_DIR" -name "pgvector_backup_*.sql" -type f -mtime +${RETENTION_DAYS} | wc -l)
if [ $DELETED_COUNT -gt 0 ]; then
    echo "Deleted $DELETED_COUNT old backup(s)"
else
    echo "No old backups to delete"
fi

echo ""
echo -e "${GREEN}=== Backup Complete ===${NC}"
echo ""
echo "To restore this backup, run:"
echo "  ./restore_database.sh $BACKUP_FILE"
echo ""
echo "To sync to Google Drive:"
echo "  1. Install Google Drive for Desktop"
echo "  2. Copy backups folder to Google Drive"
echo "  3. Or use rclone for automated sync"
