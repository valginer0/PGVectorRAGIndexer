#!/bin/bash
# PGVectorRAGIndexer Installer for macOS
# Download and double-click this file to install!
#
# This script downloads and runs the main installer.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}   PGVectorRAGIndexer - macOS Installer    ${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Check for curl
if ! command -v curl &>/dev/null; then
    echo -e "${RED}Error: curl is required but not installed.${NC}"
    echo "Please install curl and try again."
    read -p "Press Enter to close..."
    exit 1
fi

# Download and run installer
INSTALLER_URL="https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/installer.sh"

echo -e "${CYAN}Downloading installer...${NC}"
if curl -fsSL "$INSTALLER_URL" -o /tmp/pgvector_installer.sh; then
    chmod +x /tmp/pgvector_installer.sh
    echo -e "${GREEN}Download complete. Starting installation...${NC}"
    echo ""
    bash /tmp/pgvector_installer.sh
    rm -f /tmp/pgvector_installer.sh
else
    echo ""
    echo -e "${RED}Error: Failed to download the installer.${NC}"
    echo "Please check your internet connection and try again."
    echo ""
    echo "You can also try running this command in Terminal:"
    echo "  curl -fsSL $INSTALLER_URL | bash"
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi
