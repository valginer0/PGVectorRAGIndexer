#!/bin/bash
# Bootstrap script for PGVectorRAGIndexer Desktop App (macOS/Linux)
# Downloads and sets up the desktop app from GitHub
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/bootstrap_desktop_app.sh | bash
#
# Or with options:
#   curl -fsSL ... | bash -s -- --channel dev --install-dir ~/MyApps/PGVectorRAGIndexer

set -e

# Default values
GITHUB_REPO="valginer0/PGVectorRAGIndexer"
BRANCH="main"
INSTALL_DIR="$HOME/PGVectorRAGIndexer"
CHANNEL="prod"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --channel)
            CHANNEL="$2"
            shift 2
            ;;
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}PGVectorRAGIndexer Desktop App Installer${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""

# Detect OS
OS_TYPE="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS_TYPE="macos"
    # Detect macOS version for Catalina compatibility
    MACOS_VERSION=$(sw_vers -productVersion 2>/dev/null || echo "unknown")
    MACOS_MAJOR=$(echo "$MACOS_VERSION" | cut -d. -f1)
    echo -e "Detected: ${GREEN}macOS $MACOS_VERSION${NC}"
    
    # Check if Catalina (10.15) or earlier
    if [[ "$MACOS_MAJOR" == "10" ]]; then
        MACOS_MINOR=$(echo "$MACOS_VERSION" | cut -d. -f2)
        if [[ "$MACOS_MINOR" -le "15" ]]; then
            echo -e "${YELLOW}Note: Catalina detected - will use compatible PySide6 version${NC}"
            USE_CATALINA_REQUIREMENTS=true
        fi
    fi
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS_TYPE="linux"
    echo -e "Detected: ${GREEN}Linux${NC}"
else
    echo -e "${YELLOW}Warning: Unknown OS type: $OSTYPE${NC}"
fi

echo ""

# Check Python
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1)
    echo -e "✓ Found: ${GREEN}$PYTHON_VERSION${NC}"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1)
    echo -e "✓ Found: ${GREEN}$PYTHON_VERSION${NC}"
else
    echo -e "${RED}✗ ERROR: Python is not installed${NC}"
    echo -e "${YELLOW}  Please install Python 3.9+ from https://www.python.org/downloads/${NC}"
    exit 1
fi

# Check Git
if command -v git &> /dev/null; then
    GIT_VERSION=$(git --version 2>&1)
    echo -e "✓ Found: ${GREEN}$GIT_VERSION${NC}"
else
    echo -e "${RED}✗ ERROR: Git is not installed${NC}"
    echo -e "${YELLOW}  Please install Git:${NC}"
    echo -e "${YELLOW}    macOS: xcode-select --install${NC}"
    echo -e "${YELLOW}    Linux: sudo apt install git${NC}"
    exit 1
fi

# Check Docker (optional but recommended)
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version 2>&1)
    echo -e "✓ Found: ${GREEN}$DOCKER_VERSION${NC}"
else
    echo -e "${YELLOW}⚠ Docker not found (optional - needed for database backend)${NC}"
    echo -e "${YELLOW}  Install from: https://docs.docker.com/get-docker/${NC}"
fi

echo ""

# Clone or update repository
if [ -d "$INSTALL_DIR" ]; then
    if [ -d "$INSTALL_DIR/.git" ]; then
        echo -e "${YELLOW}Updating existing installation at: $INSTALL_DIR${NC}"
        cd "$INSTALL_DIR"
        
        # Reset any local changes and pull
        git reset --hard HEAD 2>/dev/null || true
        if ! git pull origin "$BRANCH"; then
            echo -e "${YELLOW}Pull failed, removing and re-cloning...${NC}"
            cd ..
            rm -rf "$INSTALL_DIR"
            git clone "https://github.com/$GITHUB_REPO.git" "$INSTALL_DIR"
            cd "$INSTALL_DIR"
        fi
    else
        echo -e "${YELLOW}Removing incomplete installation at: $INSTALL_DIR${NC}"
        rm -rf "$INSTALL_DIR"
        echo -e "${YELLOW}Installing to: $INSTALL_DIR${NC}"
        git clone "https://github.com/$GITHUB_REPO.git" "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    fi
else
    echo -e "${YELLOW}Installing to: $INSTALL_DIR${NC}"
    git clone "https://github.com/$GITHUB_REPO.git" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo ""

# Create virtual environment if needed
VENV_DIR="venv"
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    
    # Check if venv module is available, if not try to install it (Debian/Ubuntu)
    if ! $PYTHON_CMD -c "import venv" 2>/dev/null; then
        if [ "$OS_TYPE" = "linux" ]; then
            echo -e "${YELLOW}Installing python3-venv (required for virtual environments)...${NC}"
            PY_VER=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
            sudo apt update -qq && sudo apt install -y python${PY_VER}-venv
            if [ $? -ne 0 ]; then
                echo -e "${RED}✗ ERROR: Failed to install python3-venv${NC}"
                echo -e "${YELLOW}  Please run manually: sudo apt install python${PY_VER}-venv${NC}"
                exit 1
            fi
        else
            echo -e "${RED}✗ ERROR: Python venv module not available${NC}"
            exit 1
        fi
    fi
    
    $PYTHON_CMD -m venv "$VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Determine which requirements file to use
if [ "$USE_CATALINA_REQUIREMENTS" = true ] && [ -f "requirements-desktop-catalina.txt" ]; then
    REQUIREMENTS_FILE="requirements-desktop-catalina.txt"
    echo -e "${YELLOW}Installing Catalina-compatible dependencies...${NC}"
else
    REQUIREMENTS_FILE="requirements-desktop.txt"
    echo -e "${YELLOW}Installing dependencies...${NC}"
fi

pip install -q --upgrade pip
pip install -q -r "$REQUIREMENTS_FILE"

echo ""

# Update Docker containers if manage.sh exists and docker is available
if [ -f "./manage.sh" ] && command -v docker &> /dev/null; then
    echo -e "${YELLOW}Updating Docker containers (channel: $CHANNEL)...${NC}"
    chmod +x ./manage.sh
    ./manage.sh update "$CHANNEL" || echo -e "${YELLOW}Docker update skipped (containers may need manual setup)${NC}"
    echo ""
fi

echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}==========================================${NC}"
echo ""
echo -e "${CYAN}To run the desktop app:${NC}"
echo -e "  cd $INSTALL_DIR"
echo -e "  source venv/bin/activate"
echo -e "  python -m desktop_app.main"
echo ""
echo -e "${CYAN}Or use the shortcut:${NC}"
echo -e "  cd $INSTALL_DIR"
echo -e "  ./run_desktop_app.sh"
echo ""

# Auto-start the desktop app
echo -e "${GREEN}Starting desktop app...${NC}"
$PYTHON_CMD -m desktop_app.main
