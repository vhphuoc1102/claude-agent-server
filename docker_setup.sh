#!/bin/bash
#
# Claude Code Docker Setup Script
# This script installs Claude Code on the host, handles authentication,
# and sets up the Docker container with proper configuration.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"

# Configuration variables (will be written to settings.json)
CONFIG_API_KEY=""
CONFIG_BASE_URL=""
CONFIG_MODEL=""
CONFIG_SONNET=""
CONFIG_HAIKU=""
CONFIG_OPUS=""

# Print colored message
print_msg() {
    local color=$1
    local msg=$2
    echo -e "${color}${msg}${NC}"
}

print_header() {
    echo ""
    print_msg "$BLUE" "=================================================="
    print_msg "$BLUE" "  Claude Code Docker Setup"
    print_msg "$BLUE" "=================================================="
    echo ""
}

# Check if Docker is installed and running
check_docker() {
    print_msg "$YELLOW" "[1/6] Checking Docker..."

    if ! command -v docker &> /dev/null; then
        print_msg "$RED" "Error: Docker is not installed"
        print_msg "$RED" "Please install Docker first: https://docs.docker.com/get-docker/"
        exit 1
    fi

    if ! docker info &> /dev/null 2>&1; then
        print_msg "$RED" "Error: Docker is not running"
        print_msg "$RED" "Please start Docker and try again"
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null 2>&1; then
        print_msg "$RED" "Error: docker-compose is not available"
        exit 1
    fi

    print_msg "$GREEN" "Docker is ready"
}

# Install Claude Code on host
install_claude() {
    print_msg "$YELLOW" "[2/6] Checking Claude Code installation..."

    if command -v claude &> /dev/null; then
        local current_version=$(claude --version 2>/dev/null || echo "unknown")
        print_msg "$GREEN" "Claude Code is already installed (version: $current_version)"

        read -p "Do you want to reinstall/update? (y/N): " reinstall
        if [[ ! "$reinstall" =~ ^[Yy]$ ]]; then
            return 0
        fi
    fi

    print_msg "$BLUE" "Installing Claude Code..."
    curl -fsSL https://claude.ai/install.sh | bash

    # Reload shell environment (Claude Code installs to ~/.local/bin)
    export PATH="$HOME/.local/bin:$HOME/.claude/bin:$PATH"

    if command -v claude &> /dev/null; then
        print_msg "$GREEN" "Claude Code installed successfully"
    else
        print_msg "$RED" "Claude Code installation may have failed"
        print_msg "$YELLOW" "You may need to restart your terminal or run: source ~/.bashrc"
        exit 1
    fi
}

# Authentication
authenticate() {
    print_msg "$YELLOW" "[3/6] Authentication Setup..."

    echo ""
    echo "Choose authentication method:"
    echo "  [1] OAuth2 (browser login) - Recommended"
    echo "  [2] API Key"
    echo ""
    read -p "Selection (1/2): " auth_choice

    case $auth_choice in
        1)
            oauth2_auth
            ;;
        2)
            apikey_auth
            ;;
        *)
            print_msg "$RED" "Invalid selection"
            exit 1
            ;;
    esac
}

oauth2_auth() {
    print_msg "$BLUE" "Starting OAuth2 authentication..."
    echo ""
    print_msg "$YELLOW" "A link will be displayed below."
    print_msg "$YELLOW" "Copy and paste it into your browser to complete login."
    echo ""

    # Run claude login
    claude login

    if [ $? -eq 0 ]; then
        print_msg "$GREEN" "OAuth2 authentication successful"
    else
        print_msg "$RED" "OAuth2 authentication failed"
        exit 1
    fi
}

apikey_auth() {
    echo ""
    print_msg "$BLUE" "API Key Authentication (for claude login)"
    echo ""
    
    # Check if running in a TTY
    if [ -t 0 ]; then
        read -p "Enter your ANTHROPIC_API_KEY (for authentication): " api_key
    else
        print_msg "$YELLOW" "Non-interactive mode detected."
        print_msg "$YELLOW" "Please run claude login manually"
        return 1
    fi

    if [ -z "$api_key" ]; then
        print_msg "$RED" "API key cannot be empty"
        exit 1
    fi

    # Use key for claude login authentication
    export ANTHROPIC_API_KEY="$api_key"
    claude login
    
    if [ $? -eq 0 ]; then
        print_msg "$GREEN" "API key authentication successful"
    else
        print_msg "$RED" "API key authentication failed"
        exit 1
    fi
}

# Configuration
configure() {
    print_msg "$YELLOW" "[4/6] Configuration..."

    # Model configuration
    echo ""
    read -p "Configure custom models? (y/N): " custom_models
    if [[ "$custom_models" =~ ^[Yy]$ ]]; then
        configure_models
    fi

    print_msg "$GREEN" "Configuration complete"
}

configure_models() {
    echo ""
    print_msg "$BLUE" "Container Configuration"
    print_msg "$YELLOW" "Press Enter to skip and use defaults"
    echo ""

    # API key for settings.json (different from login authentication key)
    read -p "Enter ANTHROPIC_AUTH_TOKEN (API key for container): " auth_token
    if [ -n "$auth_token" ]; then
        CONFIG_API_KEY="$auth_token"
        print_msg "$GREEN" "Auth token configured for settings.json"
    fi

    read -p "Enter ANTHROPIC_BASE_URL (e.g., http://127.0.0.1:8317): " base_url
    if [ -n "$base_url" ]; then
        CONFIG_BASE_URL="$base_url"
        print_msg "$GREEN" "Proxy URL configured"
    fi

    read -p "Default model (ANTHROPIC_MODEL): " model
    if [ -n "$model" ]; then
        CONFIG_MODEL="$model"
    fi

    read -p "Default Sonnet model (ANTHROPIC_DEFAULT_SONNET_MODEL): " sonnet_model
    if [ -n "$sonnet_model" ]; then
        CONFIG_SONNET="$sonnet_model"
    fi

    read -p "Default Haiku model (ANTHROPIC_DEFAULT_HAIKU_MODEL): " haiku_model
    if [ -n "$haiku_model" ]; then
        CONFIG_HAIKU="$haiku_model"
    fi

    read -p "Default Opus model (ANTHROPIC_DEFAULT_OPUS_MODEL): " opus_model
    if [ -n "$opus_model" ]; then
        CONFIG_OPUS="$opus_model"
    fi
}

generate_settings() {
    mkdir -p "$CLAUDE_DIR"

    # Build env object from config variables
    local env_entries=""
    [ -n "$CONFIG_API_KEY" ] && env_entries="$env_entries\"ANTHROPIC_AUTH_TOKEN\": \"$CONFIG_API_KEY\""
    [ -n "$CONFIG_BASE_URL" ] && { [ -n "$env_entries" ] && env_entries="$env_entries, "; env_entries="$env_entries\"ANTHROPIC_BASE_URL\": \"$CONFIG_BASE_URL\""; }
    [ -n "$CONFIG_MODEL" ] && { [ -n "$env_entries" ] && env_entries="$env_entries, "; env_entries="$env_entries\"ANTHROPIC_MODEL\": \"$CONFIG_MODEL\""; }
    [ -n "$CONFIG_SONNET" ] && { [ -n "$env_entries" ] && env_entries="$env_entries, "; env_entries="$env_entries\"ANTHROPIC_DEFAULT_SONNET_MODEL\": \"$CONFIG_SONNET\""; }
    [ -n "$CONFIG_HAIKU" ] && { [ -n "$env_entries" ] && env_entries="$env_entries, "; env_entries="$env_entries\"ANTHROPIC_DEFAULT_HAIKU_MODEL\": \"$CONFIG_HAIKU\""; }
    [ -n "$CONFIG_OPUS" ] && { [ -n "$env_entries" ] && env_entries="$env_entries, "; env_entries="$env_entries\"ANTHROPIC_DEFAULT_OPUS_MODEL\": \"$CONFIG_OPUS\""; }

    # Generate settings.json
    cat > "$SETTINGS_FILE" << EOF
{
    "autoUpdatesChannel": "latest",
    "env": {
        $env_entries
    },
    "permissions": {
        "allow": []
    }
}
EOF

    print_msg "$GREEN" "Settings saved to $SETTINGS_FILE"
}

# Prepare .claude directory and generate settings.json
prepare_claude_dir() {
    print_msg "$YELLOW" "[5/6] Preparing .claude directory and settings..."

    if [ ! -d "$CLAUDE_DIR" ]; then
        mkdir -p "$CLAUDE_DIR"
        print_msg "$BLUE" "Created $CLAUDE_DIR"
    fi

    # Generate settings.json with collected configuration
    generate_settings

    # Ensure proper permissions
    chmod 755 "$CLAUDE_DIR"
    chmod 600 "$SETTINGS_FILE" 2>/dev/null || true

    print_msg "$GREEN" ".claude directory ready for mounting"
}

# Docker operations
run_docker() {
    print_msg "$YELLOW" "[6/6] Starting Docker container..."

    cd "$SCRIPT_DIR"

    # Determine docker-compose command
    local compose_cmd="docker-compose"
    if ! command -v docker-compose &> /dev/null; then
        compose_cmd="docker compose"
    fi

    # Build the image
    print_msg "$BLUE" "Building Docker image..."
    $compose_cmd build

    # Start the container
    print_msg "$BLUE" "Starting container..."
    $compose_cmd up -d

    # Wait for health check
    print_msg "$BLUE" "Waiting for server to be ready..."
    local max_attempts=30
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            break
        fi
        sleep 1
        attempt=$((attempt + 1))
    done

    if [ $attempt -eq $max_attempts ]; then
        print_msg "$YELLOW" "Warning: Health check timed out, but container may still be starting"
        print_msg "$YELLOW" "Check logs with: docker-compose logs -f"
    else
        print_msg "$GREEN" "Server is healthy!"
    fi

    echo ""
    print_msg "$GREEN" "=================================================="
    print_msg "$GREEN" "  Setup Complete!"
    print_msg "$GREEN" "=================================================="
    echo ""
    print_msg "$BLUE" "Server running at: http://localhost:8000"
    print_msg "$BLUE" "Health check: http://localhost:8000/health"
    echo ""
    print_msg "$YELLOW" "Useful commands:"
    echo "  View logs:     docker-compose logs -f"
    echo "  Stop server:   docker-compose down"
    echo "  Restart:       docker-compose restart"
    echo ""
    print_msg "$YELLOW" "Configuration file:"
    echo "  Claude config: $SETTINGS_FILE"
    echo ""
}

# Main
main() {
    print_header
    check_docker
    install_claude
    authenticate
    configure
    prepare_claude_dir
    run_docker
}

main "$@"
