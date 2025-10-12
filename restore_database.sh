#!/bin/bash

# PGVectorRAGIndexer Database Restore Script
# Restores PostgreSQL database from backup file

set -e  # Exit on error

# Configuration
CONTAINER_NAME="vector_rag_db"
DB_USER="rag_user"
DB_NAME="rag_vector_db"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== PGVectorRAGIndexer Database Restore ===${NC}"
echo "Timestamp: $(date)"
echo ""

# Check if backup file is provided
if [ -z "$1" ]; then
    echo -e "${RED}Error: No backup file specified!${NC}"
    echo ""
    echo "Usage: $0 <backup_file.sql>"
    echo ""
    echo "Available backups:"
    ls -lh ./backups/pgvector_backup_*.sql 2>/dev/null || echo "  No backups found"
    echo ""
    echo "To restore latest backup:"
    echo "  $0 ./backups/latest_backup.sql"
    exit 1
fi

BACKUP_FILE="$1"

# Check if backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo -e "${RED}Error: Backup file not found: ${BACKUP_FILE}${NC}"
    exit 1
fi

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${RED}Error: Container '${CONTAINER_NAME}' is not running!${NC}"
    echo "Start it with: docker-compose up -d"
    exit 1
fi

# Show backup file info
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup file: $BACKUP_FILE"
echo "Size: $BACKUP_SIZE"
echo ""

# Confirmation prompt
echo -e "${YELLOW}WARNING: This will replace all current data in the database!${NC}"
read -p "Are you sure you want to restore? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Restore cancelled."
    exit 0
fi

echo ""
echo -e "${GREEN}Restoring database...${NC}"

# Drop existing database and recreate (clean restore)
echo "Dropping existing database..."
docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;"
docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "CREATE DATABASE $DB_NAME;"

# Enable pgvector extension
echo "Enabling pgvector extension..."
docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Restore from backup
echo "Restoring data from backup..."
cat "$BACKUP_FILE" | docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME"

# Check if restore was successful
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Restore successful!${NC}"
    echo ""
    
    # Show database stats
    echo "Database statistics:"
    docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -c "
        SELECT 
            schemaname,
            tablename,
            pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
            n_tup_ins AS rows_inserted
        FROM pg_stat_user_tables 
        ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
    "
else
    echo -e "${RED}✗ Restore failed!${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}=== Restore Complete ===${NC}"
