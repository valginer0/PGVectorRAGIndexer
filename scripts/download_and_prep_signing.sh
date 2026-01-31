#!/bin/bash

# Script to automatically find the latest successful Windows Installer build,
# download the artifact, and prepare it for signing in the ToSign folder.

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

TEMP_DIR="$HOME/temp_artifact_download"
WORKFLOW_NAME="Build Windows Installer"

echo -e "${GREEN}Looking for latest successful build of '$WORKFLOW_NAME'...${NC}"

# Find latest successful run
# formatting: databaseId \t status \t conclusion
LATEST_RUN_JSON=$(gh run list --workflow="$WORKFLOW_NAME" --limit 1 --status success --json databaseId,headBranch,headSha,createdAt)

if [ -z "$LATEST_RUN_JSON" ]; then
    echo -e "${RED}No successful runs found.${NC}"
    exit 1
fi

RUN_ID=$(echo "$LATEST_RUN_JSON" | grep -o '"databaseId":[0-9]*' | cut -d: -f2)
BRANCH=$(echo "$LATEST_RUN_JSON" | grep -o '"headBranch":"[^"]*"' | cut -d: -f2 | tr -d '"')
SHA=$(echo "$LATEST_RUN_JSON" | grep -o '"headSha":"[^"]*"' | cut -d: -f2 | tr -d '"')

echo -e "Found Run ID: ${GREEN}$RUN_ID${NC}"
echo -e "Branch/Tag: ${YELLOW}$BRANCH${NC}"
echo -e "Commit: ${YELLOW}${SHA:0:7}${NC}"

# Clean temp dir
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"

echo -e "${GREEN}Downloading artifact...${NC}"

# We will download everything to temp dir and inspect contents

# We assume the artifact name is "PGVectorRAGIndexer-Setup" (standard) or "PGVectorRAGIndexer.msi" (future)
# We download everything to temp dir
gh run download "$RUN_ID" --dir "$TEMP_DIR"

echo -e "${GREEN}Download complete.${NC}"
echo -e "Contents:"
ls -la "$TEMP_DIR"

# Determine what to pass to the update script
# If we have a folder named "PGVectorRAGIndexer-Setup", use that (legacy/current exe)
# If we have a file named "PGVectorRAGIndexer.msi", use that (future msi)

ARTIFACT_PATH=""

if [ -f "$TEMP_DIR/PGVectorRAGIndexer.msi" ]; then
    ARTIFACT_PATH="$TEMP_DIR/PGVectorRAGIndexer.msi"
elif [ -d "$TEMP_DIR/PGVectorRAGIndexer-Setup" ]; then
    ARTIFACT_PATH="$TEMP_DIR/PGVectorRAGIndexer-Setup"
# It might be in a subfolder if gh run download creates one per artifact
elif [ -d "$TEMP_DIR" ]; then 
     # Check for MSI in root of temp (if download flattened it or single artifact)
     FOUND_MSI=$(find "$TEMP_DIR" -maxdepth 2 -name "PGVectorRAGIndexer.msi" | head -n 1)
     if [ -n "$FOUND_MSI" ]; then
        ARTIFACT_PATH="$FOUND_MSI"
     else
        # Fallback to checking for the Setup folder
        FOUND_FOLDER=$(find "$TEMP_DIR" -maxdepth 2 -name "PGVectorRAGIndexer-Setup" -type d | head -n 1)
        if [ -n "$FOUND_FOLDER" ]; then
            ARTIFACT_PATH="$FOUND_FOLDER"
        fi
     fi
fi

if [ -z "$ARTIFACT_PATH" ]; then
    echo -e "${RED}Could not identify a valid artifact (PGVectorRAGIndexer.msi or PGVectorRAGIndexer-Setup folder) in download.${NC}"
    exit 1
fi

echo -e "${GREEN}Identified artifact: $ARTIFACT_PATH${NC}"
echo -e "Calling update_tosign_artifact.sh..."

./scripts/update_tosign_artifact.sh "$ARTIFACT_PATH"

echo -e "${GREEN}SUCCESS! Artifact is ready in ToSign folder.${NC}"
