#!/bin/bash

# Sync backups to Google Drive using rclone
# First-time setup required: rclone config

set -e

# Configuration
BACKUP_DIR="./backups"
GDRIVE_REMOTE="gdrive"  # Name you gave to Google Drive in rclone config
GDRIVE_PATH="PGVectorRAGIndexer/backups"  # Path in Google Drive

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Sync Backups to Google Drive ===${NC}"
echo "Timestamp: $(date)"
echo ""

# Check if rclone is installed
if ! command -v rclone &> /dev/null; then
    echo -e "${RED}Error: rclone is not installed!${NC}"
    echo ""
    echo "Install rclone:"
    echo "  sudo apt update"
    echo "  sudo apt install rclone"
    echo ""
    echo "Then configure Google Drive:"
    echo "  rclone config"
    echo ""
    exit 1
fi

# Check if Google Drive remote is configured
if ! rclone listremotes | grep -q "^${GDRIVE_REMOTE}:$"; then
    echo -e "${RED}Error: Google Drive remote '${GDRIVE_REMOTE}' not configured!${NC}"
    echo ""
    echo "Configure Google Drive with rclone:"
    echo "  rclone config"
    echo ""
    echo "Follow the prompts to add Google Drive as '${GDRIVE_REMOTE}'"
    exit 1
fi

# Check if backup directory exists
if [ ! -d "$BACKUP_DIR" ]; then
    echo -e "${RED}Error: Backup directory not found: ${BACKUP_DIR}${NC}"
    echo "Run ./backup_database.sh first to create backups"
    exit 1
fi

# Count backups
BACKUP_COUNT=$(ls -1 "${BACKUP_DIR}"/pgvector_backup_*.sql 2>/dev/null | wc -l)
if [ $BACKUP_COUNT -eq 0 ]; then
    echo -e "${YELLOW}Warning: No backup files found in ${BACKUP_DIR}${NC}"
    echo "Run ./backup_database.sh first"
    exit 1
fi

echo "Found $BACKUP_COUNT backup file(s)"
echo "Syncing to: ${GDRIVE_REMOTE}:${GDRIVE_PATH}"
echo ""

# Sync to Google Drive
echo -e "${GREEN}Syncing...${NC}"
rclone sync "$BACKUP_DIR" "${GDRIVE_REMOTE}:${GDRIVE_PATH}" \
    --progress \
    --transfers 4 \
    --checkers 8 \
    --stats 1s \
    --stats-one-line

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Sync complete!${NC}"
    echo ""
    
    # Show remote files
    echo "Files in Google Drive:"
    rclone ls "${GDRIVE_REMOTE}:${GDRIVE_PATH}" | head -10
    
    TOTAL_FILES=$(rclone ls "${GDRIVE_REMOTE}:${GDRIVE_PATH}" | wc -l)
    echo ""
    echo "Total files in Google Drive: $TOTAL_FILES"
else
    echo -e "${RED}✗ Sync failed!${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}=== Sync Complete ===${NC}"
echo ""
echo "View files in Google Drive:"
echo "  rclone ls ${GDRIVE_REMOTE}:${GDRIVE_PATH}"
echo ""
echo "Download from Google Drive:"
echo "  rclone copy ${GDRIVE_REMOTE}:${GDRIVE_PATH} ./backups"
