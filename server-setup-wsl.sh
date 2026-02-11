#!/bin/bash
# =============================================================================
# PGVectorRAGIndexer — WSL2 Server Setup Script
# =============================================================================
#
# Sets up the PGVectorRAGIndexer backend server inside WSL2 on Windows.
# Requires: WSL2 with a Linux distribution + Docker Desktop for Windows.
#
# Usage (from inside WSL2):
#   bash server-setup-wsl.sh [OPTIONS]
#
# Options:
#   --port PORT         API port (default: 8000)
#   --generate-key      Auto-generate an API key and print it
#
# Prerequisites:
#   1. WSL2 enabled: wsl --install (from PowerShell as admin)
#   2. Docker Desktop for Windows with "Use WSL 2 based engine" enabled
#   3. Docker Desktop → Settings → Resources → WSL Integration → enable
#      for your distro
#
# NOTE: Do NOT attempt bare-metal PostgreSQL + pgvector on Windows.
#       The pgvector native build on Windows is fragile and unsupported.
#       Always use Docker (via WSL2 or Docker Desktop).
# =============================================================================

set -e

# ── Colors ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

API_PORT="${API_PORT:-8000}"
GENERATE_KEY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --port)         API_PORT="$2"; shift 2 ;;
        --generate-key) GENERATE_KEY=true; shift ;;
        -h|--help)      head -24 "$0" | tail -21; exit 0 ;;
        *)              echo -e "${RED}Unknown option: $1${NC}"; exit 1 ;;
    esac
done

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   PGVectorRAGIndexer — WSL2 Server Setup (Windows)        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Check WSL2 ───────────────────────────────────────────────────────────────
echo -e "${GREEN}[1/4] Checking WSL2 environment...${NC}"

if grep -qi microsoft /proc/version 2>/dev/null; then
    echo -e "  ✓ Running inside WSL2"
else
    echo -e "${YELLOW}  ⚠ This does not appear to be WSL2. Script may still work on native Linux.${NC}"
fi

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker not found in WSL2.${NC}"
    echo -e "${YELLOW}  Ensure Docker Desktop is installed and WSL integration is enabled:${NC}"
    echo -e "${YELLOW}    Docker Desktop → Settings → Resources → WSL Integration${NC}"
    exit 1
fi

if ! docker info &> /dev/null 2>&1; then
    echo -e "${RED}✗ Docker daemon not accessible.${NC}"
    echo -e "${YELLOW}  Make sure Docker Desktop is running and WSL integration is on.${NC}"
    exit 1
fi
echo -e "  ✓ Docker: $(docker --version | head -1)"
echo ""

# ── Clone / locate project ──────────────────────────────────────────────────
echo -e "${GREEN}[2/4] Setting up project...${NC}"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" 2>/dev/null && pwd )"

if [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
    PROJECT_DIR="$SCRIPT_DIR"
elif [ -f "./docker-compose.yml" ]; then
    PROJECT_DIR="$(pwd)"
else
    PROJECT_DIR="${HOME}/PGVectorRAGIndexer"
    if [ -d "$PROJECT_DIR/.git" ]; then
        echo -e "  Updating existing clone..."
        cd "$PROJECT_DIR"
        git pull origin main 2>/dev/null || true
    else
        echo -e "  Cloning repository..."
        git clone "https://github.com/valginer0/PGVectorRAGIndexer.git" "$PROJECT_DIR"
    fi
fi

cd "$PROJECT_DIR"
echo -e "  ✓ Project at: ${CYAN}$PROJECT_DIR${NC}"
echo ""

# ── Configure & start ───────────────────────────────────────────────────────
echo -e "${GREEN}[3/4] Starting server...${NC}"

# Delegate to the main server-setup.sh
SETUP_ARGS="--port $API_PORT"
if [ "$GENERATE_KEY" = true ]; then
    SETUP_ARGS="$SETUP_ARGS --generate-key"
fi

if [ -f "server-setup.sh" ]; then
    bash server-setup.sh $SETUP_ARGS
else
    echo -e "${RED}✗ server-setup.sh not found. Run from the project root.${NC}"
    exit 1
fi

# ── WSL-specific notes ──────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}[4/4] WSL2-specific notes...${NC}"
echo ""

# Get WSL IP
WSL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
WINDOWS_HOST="localhost"

echo -e "${CYAN}Accessing from Windows host:${NC}"
echo -e "  ${YELLOW}http://localhost:${API_PORT}${NC}"
echo -e "  (Docker Desktop forwards WSL2 ports to Windows automatically)"
echo ""
echo -e "${CYAN}Accessing from other machines on the network:${NC}"
echo -e "  Find your Windows IP: ${YELLOW}ipconfig${NC} (in PowerShell)"
echo -e "  URL: ${YELLOW}http://<windows-ip>:${API_PORT}${NC}"
echo ""
echo -e "${CYAN}Windows Firewall:${NC}"
echo -e "  If other machines can't connect, allow port ${API_PORT} in Windows Firewall:"
echo -e "  ${YELLOW}netsh advfirewall firewall add rule name=\"PGVectorRAG\" dir=in action=allow protocol=TCP localport=${API_PORT}${NC}"
echo ""
