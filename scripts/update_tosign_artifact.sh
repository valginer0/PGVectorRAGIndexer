#!/bin/bash

# Script to safely update the Windows installer artifact in the ToSign folder
# Usage: ./update_tosign_artifact.sh <path_to_new_artifact_folder>

set -e

SOURCE_PATH="$1"
TOSIGN_ROOT="/mnt/c/Users/v_ale/Desktop/ToSign"


# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

if [ -z "$SOURCE_PATH" ]; then
    echo -e "${RED}Error: Source path required${NC}"
    echo "Usage: ./scripts/update_tosign_artifact.sh <path_to_new_artifact_file_or_folder>"
    exit 1
fi

if [ ! -e "$SOURCE_PATH" ]; then
    echo -e "${RED}Error: Source path not found: $SOURCE_PATH${NC}"
    exit 1
fi

# Determine type of artifact
IS_MSI=false
if [ -f "$SOURCE_PATH" ]; then
    if [[ "$SOURCE_PATH" == *.msi ]]; then
        IS_MSI=true
        TARGET_NAME="PGVectorRAGIndexer.msi"
    else
        echo -e "${RED}Error: Single file must be an .msi${NC}"
        exit 1
    fi
else
    IS_MSI=false
    TARGET_NAME="PGVectorRAGIndexer-unsigned"
fi

TARGET_PATH="$TOSIGN_ROOT/$TARGET_NAME"
BACKUP_PATH="$TOSIGN_ROOT/${TARGET_NAME}_bak"

echo -e "${GREEN}Updating ToSign artifact...${NC}"
echo -e "  Source: $SOURCE_PATH"
echo -e "  Target: $TARGET_PATH"

# 1. Remove old backup
if [ -e "$BACKUP_PATH" ]; then
    echo -e "${YELLOW}Removing old backup...${NC}"
    rm -rf "$BACKUP_PATH"
fi

# 2. Rotate current version to backup
if [ -e "$TARGET_PATH" ]; then
    echo -e "${YELLOW}Backing up current version...${NC}"
    if mv "$TARGET_PATH" "$BACKUP_PATH" 2>/dev/null; then
        echo -e "${GREEN}✓ Backup created${NC}"
    else
        echo -e "${RED}⚠ Could not move/backup existing artifact (locked?).${NC}"
        echo -e "${YELLOW}Attempting to overwrite existing files...${NC}"
    fi
fi

# 3. Copy new version
echo -e "${GREEN}Copying new version...${NC}"

if [ -e "$TARGET_PATH" ]; then
    # Target still exists (move failed), so we overwrite contents
    echo -e "${YELLOW}Target exists. Overwriting...${NC}"
    if [ "$IS_MSI" = true ]; then
        cp -f "$SOURCE_PATH" "$TARGET_PATH"
    else
        # Use -T to treat destination as a normal file (prevent copy into directory if source is dir? no, cp -r semantics)
        # Best way: cp -rf "$SOURCE_PATH/." "$TARGET_PATH/"
        cp -rf "$SOURCE_PATH/." "$TARGET_PATH/"
    fi
else
    # Target was moved (or didn't exist), so we copy to the new name
    if [ "$IS_MSI" = true ]; then
        cp "$SOURCE_PATH" "$TARGET_PATH"
    else
        cp -r "$SOURCE_PATH" "$TARGET_PATH"
    fi
fi

echo -e "${GREEN}✓ Done!${NC}"
echo -e "Contents of ToSign folder:"
ls -la "$TOSIGN_ROOT"
