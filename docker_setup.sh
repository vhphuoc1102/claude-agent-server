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
ENV_FILE="$SCRIPT_DIR/.env"

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
    print_msg "$BLUE" "API Key Authentication"
    echo ""
    read -p "Enter your ANTHROPIC_API_KEY: " -s api_key
    echo ""

    if [ -z "$api_key" ]; then
        print_msg "$RED" "API key cannot be empty"
        exit 1
    fi

    # Save to .env file
    echo "ANTHROPIC_API_KEY=$api_key" > "$ENV_FILE"
    print_msg "$GREEN" "API key saved to .env file"
}

# Configuration
configure() {
    print_msg "$YELLOW" "[4/6] Configuration..."

    echo ""
    read -p "Do you want to configure custom settings? (y/N): " do_config

    if [[ ! "$do_config" =~ ^[Yy]$ ]]; then
        # Create empty .env if it doesn't exist
        touch "$ENV_FILE"
        return 0
    fi

    # Ensure .env exists
    touch "$ENV_FILE"

    # Proxy configuration
    echo ""
    read -p "Use a proxy for API requests? (y/N): " use_proxy
    if [[ "$use_proxy" =~ ^[Yy]$ ]]; then
        read -p "Enter ANTHROPIC_BASE_URL (e.g., http://127.0.0.1:8317): " base_url
        if [ -n "$base_url" ]; then
            # Remove existing ANTHROPIC_BASE_URL if present
            sed -i '/^ANTHROPIC_BASE_URL=/d' "$ENV_FILE" 2>/dev/null || true
            echo "ANTHROPIC_BASE_URL=$base_url" >> "$ENV_FILE"
            print_msg "$GREEN" "Proxy URL configured"
        fi
    fi

    # Model configuration
    echo ""
    read -p "Configure custom models? (y/N): " custom_models
    if [[ "$custom_models" =~ ^[Yy]$ ]]; then
        configure_models
    fi

    # Generate settings.json
    echo ""
    read -p "Generate Claude settings.json? (y/N): " gen_settings
    if [[ "$gen_settings" =~ ^[Yy]$ ]]; then
        generate_settings
    fi

    print_msg "$GREEN" "Configuration complete"
}

configure_models() {
    echo ""
    print_msg "$BLUE" "Model Configuration"
    print_msg "$YELLOW" "Press Enter to skip and use defaults"
    echo ""

    read -p "Default model (ANTHROPIC_MODEL): " model
    if [ -n "$model" ]; then
        sed -i '/^ANTHROPIC_MODEL=/d' "$ENV_FILE" 2>/dev/null || true
        echo "ANTHROPIC_MODEL=$model" >> "$ENV_FILE"
    fi

    read -p "Default Sonnet model (ANTHROPIC_DEFAULT_SONNET_MODEL): " sonnet_model
    if [ -n "$sonnet_model" ]; then
        sed -i '/^ANTHROPIC_DEFAULT_SONNET_MODEL=/d' "$ENV_FILE" 2>/dev/null || true
        echo "ANTHROPIC_DEFAULT_SONNET_MODEL=$sonnet_model" >> "$ENV_FILE"
    fi

    read -p "Default Haiku model (ANTHROPIC_DEFAULT_HAIKU_MODEL): " haiku_model
    if [ -n "$haiku_model" ]; then
        sed -i '/^ANTHROPIC_DEFAULT_HAIKU_MODEL=/d' "$ENV_FILE" 2>/dev/null || true
        echo "ANTHROPIC_DEFAULT_HAIKU_MODEL=$haiku_model" >> "$ENV_FILE"
    fi

    read -p "Default Opus model (ANTHROPIC_DEFAULT_OPUS_MODEL): " opus_model
    if [ -n "$opus_model" ]; then
        sed -i '/^ANTHROPIC_DEFAULT_OPUS_MODEL=/d' "$ENV_FILE" 2>/dev/null || true
        echo "ANTHROPIC_DEFAULT_OPUS_MODEL=$opus_model" >> "$ENV_FILE"
    fi
}

generate_settings() {
    mkdir -p "$CLAUDE_DIR"
    local settings_file="$CLAUDE_DIR/settings.json"

    # Read values from .env
    local api_key=$(grep '^ANTHROPIC_API_KEY=' "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
    local base_url=$(grep '^ANTHROPIC_BASE_URL=' "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
    local model=$(grep '^ANTHROPIC_MODEL=' "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
    local sonnet=$(grep '^ANTHROPIC_DEFAULT_SONNET_MODEL=' "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
    local haiku=$(grep '^ANTHROPIC_DEFAULT_HAIKU_MODEL=' "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
    local opus=$(grep '^ANTHROPIC_DEFAULT_OPUS_MODEL=' "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)

    # Build env object
    local env_entries=""
    [ -n "$api_key" ] && env_entries="$env_entries\"ANTHROPIC_AUTH_TOKEN\": \"$api_key\""
    [ -n "$base_url" ] && { [ -n "$env_entries" ] && env_entries="$env_entries, "; env_entries="$env_entries\"ANTHROPIC_BASE_URL\": \"$base_url\""; }
    [ -n "$model" ] && { [ -n "$env_entries" ] && env_entries="$env_entries, "; env_entries="$env_entries\"ANTHROPIC_MODEL\": \"$model\""; }
    [ -n "$sonnet" ] && { [ -n "$env_entries" ] && env_entries="$env_entries, "; env_entries="$env_entries\"ANTHROPIC_DEFAULT_SONNET_MODEL\": \"$sonnet\""; }
    [ -n "$haiku" ] && { [ -n "$env_entries" ] && env_entries="$env_entries, "; env_entries="$env_entries\"ANTHROPIC_DEFAULT_HAIKU_MODEL\": \"$haiku\""; }
    [ -n "$opus" ] && { [ -n "$env_entries" ] && env_entries="$env_entries, "; env_entries="$env_entries\"ANTHROPIC_DEFAULT_OPUS_MODEL\": \"$opus\""; }

    # Generate settings.json
    cat > "$settings_file" << EOF
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

    print_msg "$GREEN" "Settings saved to $settings_file"
}

# Prepare .claude directory for mounting
prepare_claude_dir() {
    print_msg "$YELLOW" "[5/6] Preparing .claude directory..."

    if [ ! -d "$CLAUDE_DIR" ]; then
        mkdir -p "$CLAUDE_DIR"
        print_msg "$BLUE" "Created $CLAUDE_DIR"
    fi

    # Ensure proper permissions
    chmod 755 "$CLAUDE_DIR"

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
    print_msg "$YELLOW" "Configuration files:"
    echo "  Environment:   $ENV_FILE"
    echo "  Claude config: $CLAUDE_DIR/settings.json"
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
