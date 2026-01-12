#!/bin/bash
# PGVectorRAGIndexer One-Click Installer (macOS/Linux)
# Fully automatic installation with progress UI
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/valginer0/PGVectorRAGIndexer/main/installer.sh | bash
#
# Or download and run:
#   chmod +x installer.sh && ./installer.sh

set -e

# ============================================================================
# CONFIGURATION
# ============================================================================

GITHUB_REPO="valginer0/PGVectorRAGIndexer"
BRANCH="main"
INSTALL_DIR="$HOME/PGVectorRAGIndexer"
CHANNEL="prod"
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --channel) CHANNEL="$2"; shift 2 ;;
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --branch) BRANCH="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help) echo "Usage: installer.sh [--dry-run] [--channel prod|dev] [--install-dir DIR]"; exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ============================================================================
# UI HELPER FUNCTIONS
# ============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m'

CURRENT_STEP=0
TOTAL_STEPS=6

show_banner() {
    clear
    echo ""
    echo -e "${CYAN}  =============================================================${NC}"
    echo -e "${CYAN}  |                                                           |${NC}"
    echo -e "${CYAN}  |         PGVectorRAGIndexer - One-Click Installer          |${NC}"
    echo -e "${CYAN}  |                                                           |${NC}"
    echo -e "${CYAN}  =============================================================${NC}"
    echo ""
}

show_step() {
    CURRENT_STEP=$1
    local message="$2"
    local time_est="$3"
    
    local percent=$((CURRENT_STEP * 100 / TOTAL_STEPS))
    local filled=$((CURRENT_STEP * 40 / TOTAL_STEPS))
    local empty=$((40 - filled))
    local bar=$(printf '%*s' "$filled" '' | tr ' ' '#')$(printf '%*s' "$empty" '' | tr ' ' '-')
    
    echo ""
    echo -e "${YELLOW}  Step $CURRENT_STEP of $TOTAL_STEPS: $message${NC}"
    if [ -n "$time_est" ]; then
        echo -e "${GRAY}  Estimated time: $time_est${NC}"
    fi
    echo -e "${CYAN}  [$bar] $percent%${NC}"
    echo ""
}

spinner() {
    local pid=$1
    local message="$2"
    local spin_chars='|/-\'
    local i=0
    
    while kill -0 $pid 2>/dev/null; do
        i=$(( (i+1) % 4 ))
        printf "\r  ${GRAY}${spin_chars:$i:1} $message...${NC}   "
        sleep 0.1
    done
    printf "\r                                                              \r"
}

run_with_spinner() {
    local message="$1"
    shift
    
    # Run command in background
    "$@" >/dev/null 2>&1 &
    local pid=$!
    
    # Show spinner while running
    spinner $pid "$message"
    
    # Wait for completion and get exit code
    wait $pid
    return $?
}

show_success() {
    echo -e "  ${GREEN}[OK]${NC} $1"
}

show_warning() {
    echo -e "  ${YELLOW}[!]${NC} $1"
}

show_error() {
    echo -e "  ${RED}[X]${NC} $1"
}

show_info() {
    echo -e "  ${CYAN}[i]${NC} $1"
}

# ============================================================================
# PREREQUISITE DETECTION AND INSTALLATION
# ============================================================================

detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        OS_TYPE="macos"
        MACOS_VERSION=$(sw_vers -productVersion 2>/dev/null || echo "unknown")
        show_info "Detected: macOS $MACOS_VERSION"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS_TYPE="linux"
        if [ -f /etc/os-release ]; then
            . /etc/os-release
            show_info "Detected: $NAME $VERSION_ID"
        else
            show_info "Detected: Linux"
        fi
    else
        OS_TYPE="unknown"
        show_warning "Unknown OS: $OSTYPE"
    fi
}

check_homebrew() {
    if command -v brew &>/dev/null; then
        return 0
    fi
    return 1
}

install_homebrew() {
    show_info "Installing Homebrew (package manager)..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/null >/dev/null 2>&1 &
    local pid=$!
    spinner $pid "Installing Homebrew"
    wait $pid
    
    # Add Homebrew to PATH for this session
    if [[ "$OS_TYPE" == "macos" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"
    else
        eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv 2>/dev/null)"
    fi
    
    if check_homebrew; then
        show_success "Homebrew installed"
        return 0
    else
        show_error "Homebrew installation failed"
        return 1
    fi
}

check_python() {
    if command -v python3 &>/dev/null; then
        PYTHON_CMD="python3"
        return 0
    elif command -v python &>/dev/null; then
        PYTHON_CMD="python"
        return 0
    fi
    return 1
}

install_python() {
    if check_python; then
        local version=$($PYTHON_CMD --version 2>&1)
        show_success "Python already installed: $version"
        return 0
    fi
    
    if [[ "$OS_TYPE" == "macos" ]]; then
        if check_homebrew; then
            run_with_spinner "Installing Python" brew install python3
            if check_python; then
                show_success "Python installed via Homebrew"
                return 0
            fi
        fi
    elif [[ "$OS_TYPE" == "linux" ]]; then
        if command -v apt-get &>/dev/null; then
            run_with_spinner "Installing Python" sudo apt-get install -y python3 python3-venv python3-pip
        elif command -v dnf &>/dev/null; then
            run_with_spinner "Installing Python" sudo dnf install -y python3 python3-pip
        elif check_homebrew; then
            run_with_spinner "Installing Python" brew install python3
        fi
        
        if check_python; then
            show_success "Python installed"
            return 0
        fi
    fi
    
    show_error "Python installation failed"
    show_info "Please install Python 3.9+ manually"
    return 1
}

check_git() {
    command -v git &>/dev/null
}

install_git() {
    if check_git; then
        local version=$(git --version 2>&1)
        show_success "Git already installed: $version"
        return 0
    fi
    
    if [[ "$OS_TYPE" == "macos" ]]; then
        # Try xcode-select first
        run_with_spinner "Installing Git (Xcode tools)" xcode-select --install 2>/dev/null || true
        sleep 2
        if check_git; then
            show_success "Git installed via Xcode tools"
            return 0
        fi
        
        if check_homebrew; then
            run_with_spinner "Installing Git" brew install git
        fi
    elif [[ "$OS_TYPE" == "linux" ]]; then
        if command -v apt-get &>/dev/null; then
            run_with_spinner "Installing Git" sudo apt-get install -y git
        elif command -v dnf &>/dev/null; then
            run_with_spinner "Installing Git" sudo dnf install -y git
        elif check_homebrew; then
            run_with_spinner "Installing Git" brew install git
        fi
    fi
    
    if check_git; then
        show_success "Git installed"
        return 0
    fi
    
    show_error "Git installation failed"
    return 1
}

check_docker() {
    command -v docker &>/dev/null && docker ps >/dev/null 2>&1
}

install_docker() {
    if check_docker; then
        local version=$(docker --version 2>&1)
        show_success "Docker already running: $version"
        return 0
    fi
    
    if command -v docker &>/dev/null; then
        show_warning "Docker installed but not running"
        show_info "Please start Docker Desktop and run the installer again"
        return 1
    fi
    
    if [[ "$OS_TYPE" == "macos" ]]; then
        if check_homebrew; then
            show_info "Installing Docker Desktop via Homebrew..."
            run_with_spinner "Installing Docker Desktop" brew install --cask docker
            show_warning "Docker Desktop installed - please start it from Applications"
            show_info "After Docker starts, run this installer again"
            return 1
        fi
    elif [[ "$OS_TYPE" == "linux" ]]; then
        show_info "For Linux, please install Docker manually:"
        show_info "  https://docs.docker.com/engine/install/"
        return 1
    fi
    
    show_error "Docker installation requires manual setup"
    show_info "Install from: https://docs.docker.com/get-docker/"
    return 1
}

# ============================================================================
# APPLICATION SETUP
# ============================================================================

setup_application() {
    # Clone or update repository
    if [ -d "$INSTALL_DIR/.git" ]; then
        (cd "$INSTALL_DIR" && git reset --hard HEAD && git pull origin "$BRANCH") >/dev/null 2>&1 &
        local pid=$!
        spinner $pid "Updating repository"
        wait $pid
    else
        [ -d "$INSTALL_DIR" ] && rm -rf "$INSTALL_DIR"
        git clone "https://github.com/$GITHUB_REPO.git" "$INSTALL_DIR" >/dev/null 2>&1 &
        local pid=$!
        spinner $pid "Cloning repository"
        wait $pid
    fi
    
    if [ ! -d "$INSTALL_DIR" ]; then
        show_error "Failed to clone repository"
        return 1
    fi
    show_success "Repository ready"
    
    cd "$INSTALL_DIR"
    
    # Create virtual environment (with virtualenv fallback for systems without venv)
    if [ ! -d "venv" ] || [ ! -f "venv/bin/activate" ]; then
        rm -rf venv 2>/dev/null || true
        
        # Try python -m venv first
        if $PYTHON_CMD -m venv venv >/dev/null 2>&1; then
            show_success "Virtual environment created"
        else
            # Fallback: bootstrap pip if needed, then install virtualenv
            show_info "Setting up Python environment..."
            
            # Install pip if not available
            if ! $PYTHON_CMD -m pip --version >/dev/null 2>&1; then
                curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py >/dev/null 2>&1
                $PYTHON_CMD /tmp/get-pip.py --user >/dev/null 2>&1 || true
                rm -f /tmp/get-pip.py
            fi
            
            # Install virtualenv and create venv
            $PYTHON_CMD -m pip install --user virtualenv >/dev/null 2>&1 || true
            if $PYTHON_CMD -m virtualenv venv >/dev/null 2>&1; then
                show_success "Virtual environment created (via virtualenv)"
            else
                show_error "Failed to create virtual environment"
                show_info "Please run: sudo apt install python3-venv python3-pip"
                return 1
            fi
        fi
    fi
    
    if [ ! -f "venv/bin/activate" ]; then
        show_error "Virtual environment not found"
        return 1
    fi
    source venv/bin/activate
    show_success "Virtual environment ready"
    
    # Install dependencies
    pip install -q --upgrade pip >/dev/null 2>&1 &
    local pid=$!
    spinner $pid "Upgrading pip"
    wait $pid
    
    pip install -q -r requirements-desktop.txt >/dev/null 2>&1 &
    pid=$!
    spinner $pid "Installing Python dependencies"
    wait $pid
    show_success "Dependencies installed"
    
    # Pull Docker images if Docker is available
    if check_docker && [ -f "./manage.sh" ]; then
        chmod +x ./manage.sh
        ./manage.sh update "$CHANNEL" >/dev/null 2>&1 &
        local pid=$!
        spinner $pid "Pulling Docker images"
        wait $pid
        show_success "Docker containers ready"
    fi
    
    return 0
}

# ============================================================================
# MAIN INSTALLATION FLOW
# ============================================================================

main() {
    show_banner
    
    # Handle dry-run mode
    if [[ "$DRY_RUN" == "true" ]]; then
        echo -e "  ${YELLOW}=== DRY RUN MODE ===${NC}"
        echo -e "  ${GRAY}Showing what would happen without actually installing.${NC}"
        echo ""
        detect_os
        echo ""
        echo -e "  ${CYAN}Would check/install:${NC}"
        echo -e "    - Python 3.9+"
        echo -e "    - Git"
        echo -e "    - Docker"
        echo ""
        echo -e "  ${CYAN}Would install to:${NC} $INSTALL_DIR"
        echo ""
        echo -e "  ${CYAN}Prerequisites status:${NC}"
        echo -e "    Python: $(command -v python3 >/dev/null && python3 --version 2>&1 || echo 'NOT FOUND - will install')"
        echo -e "    Git:    $(command -v git >/dev/null && git --version 2>&1 | head -1 || echo 'NOT FOUND - will install')"
        echo -e "    Docker: $(docker ps >/dev/null 2>&1 && docker --version 2>&1 | head -1 || echo 'NOT RUNNING - will prompt')"
        echo ""
        echo -e "  ${GREEN}Run without --dry-run to proceed with installation.${NC}"
        exit 0
    fi
    
    # Step 1: Detect OS
    show_step 1 "Detecting system" "~10 seconds"
    detect_os
    
    # Step 2: Check/Install Homebrew (macOS only)
    show_step 2 "Checking package manager" "~1 minute"
    if [[ "$OS_TYPE" == "macos" ]]; then
        if ! check_homebrew; then
            show_info "Homebrew not found - will install"
            if ! install_homebrew; then
                show_error "Cannot proceed without Homebrew on macOS"
                exit 1
            fi
        else
            show_success "Homebrew available"
        fi
    else
        show_success "Using system package manager"
    fi
    
    # Step 3: Install Python
    show_step 3 "Installing Python" "~2 minutes"
    if ! install_python; then
        exit 1
    fi
    
    # Step 4: Install Git
    show_step 4 "Installing Git" "~1 minute"
    if ! install_git; then
        exit 1
    fi
    
    # Step 5: Check Docker
    show_step 5 "Checking Docker" "~1 minute"
    if ! install_docker; then
        show_warning "Continuing without Docker - some features may not work"
    fi
    
    # Step 6: Setup application
    show_step 6 "Setting up application" "~3 minutes"
    if ! setup_application; then
        show_error "Application setup failed"
        exit 1
    fi
    
    # Complete!
    echo ""
    echo -e "${GREEN}  =============================================================${NC}"
    echo -e "${GREEN}  |                  INSTALLATION COMPLETE!                   |${NC}"
    echo -e "${GREEN}  =============================================================${NC}"
    echo ""
    echo -e "  ${CYAN}Starting PGVectorRAGIndexer...${NC}"
    echo ""
    echo -e "  ${GRAY}To run again later:${NC}"
    echo -e "    cd $INSTALL_DIR && ./run_desktop_app.sh"
    echo ""
    echo -e "  ${GRAY}To uninstall:${NC}"
    echo -e "    rm -rf $INSTALL_DIR"
    echo ""
    
    # Launch the app
    cd "$INSTALL_DIR"
    source venv/bin/activate
    $PYTHON_CMD -m desktop_app.main
}

# Handle Ctrl+C
trap 'echo ""; echo -e "  ${YELLOW}[!] Installation interrupted${NC}"; exit 1' INT

# Run main
main
