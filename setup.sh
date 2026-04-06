#!/bin/bash

# ToolMux Setup Script
# Installs all requirements and sets up the environment for ToolMux usage.

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored output
print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}❌${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check Python version
check_python() {
    print_info "Checking Python installation..."
    
    if command_exists python3; then
        PYTHON_CMD="python3"
    elif command_exists python; then
        PYTHON_CMD="python"
    else
        print_error "Python is not installed. Please install Python 3.8 or higher."
        exit 1
    fi
    
    # Check Python version - need 3.10+ for fastmcp
    PYTHON_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PYTHON_MAJOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.major)")
    PYTHON_MINOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.minor)")
    
    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
        print_warning "Found Python $PYTHON_VERSION, but fastmcp requires Python 3.10+"
        
        # Try to find a compatible Python version
        PYTHON_CANDIDATES=(
            "/opt/homebrew/bin/python3.12"
            "/opt/homebrew/bin/python3.11" 
            "/opt/homebrew/bin/python3.10"
            "/usr/local/bin/python3.12"
            "/usr/local/bin/python3.11"
            "/usr/local/bin/python3.10"
            "python3.12"
            "python3.11" 
            "python3.10"
        )
        
        FOUND_COMPATIBLE=false
        for cmd in "${PYTHON_CANDIDATES[@]}"; do
            if command_exists "$cmd"; then
                if $cmd -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
                    PYTHON_CMD="$cmd"
                    PYTHON_VERSION=$($cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
                    print_status "Found compatible Python: $cmd (version $PYTHON_VERSION)"
                    FOUND_COMPATIBLE=true
                    break
                fi
            fi
        done
        
        if [ "$FOUND_COMPATIBLE" = false ]; then
            print_error "No compatible Python version found (3.10+ required for fastmcp)"
            print_info "Please install Python 3.10+ and try again"
            if [ "$OS" = "macos" ]; then
                print_info "On macOS with Homebrew: brew install python@3.11"
            elif [ "$OS" = "linux" ]; then
                print_info "On Ubuntu/Debian: sudo apt install python3.11"
                print_info "On RHEL/CentOS: sudo yum install python311"
            fi
            exit 1
        fi
    else
        print_status "Python $PYTHON_VERSION detected (compatible)"
    fi
}

# Install Python requirements
install_python_requirements() {
    print_info "Installing Python requirements..."
    
    if [ ! -f "requirements.txt" ]; then
        print_warning "requirements.txt not found"
        return 1
    fi
    
    PYTHON_VERSION_CHECK=$($PYTHON_CMD -c "import sys; print(sys.version_info >= (3,10))")
    
    if [ "$PYTHON_VERSION_CHECK" = "True" ]; then
        # Python 3.10+, install all requirements
        print_status "Installing all requirements (fastmcp supported)"
        if $PYTHON_CMD -m pip install -r requirements.txt; then
            print_status "Python requirements installed successfully"
        else
            print_error "Failed to install some requirements"
            return 1
        fi
    else
        # Python < 3.10, install requirements except fastmcp
        print_warning "Installing requirements except fastmcp (Python version limitation)"
        
        while IFS= read -r line; do
            # Skip comments and empty lines
            if echo "$line" | grep -q "^[[:space:]]*#" || [ -z "$line" ]; then
                continue
            fi
            
            # Skip fastmcp for older Python versions
            if echo "$line" | grep -q "^fastmcp"; then
                print_warning "Skipping fastmcp (requires Python 3.10+)"
                continue
            fi
            
            # Install the dependency
            if ! $PYTHON_CMD -m pip install "$line"; then
                print_warning "Failed to install: $line"
            fi
        done < requirements.txt
        
        print_status "Base requirements installed (limited functionality without fastmcp)"
    fi
}

# Check and install uv
install_uv() {
    print_info "Checking uv installation..."
    
    if command_exists uv; then
        UV_VERSION=$(uv --version)
        print_status "uv is already installed: $UV_VERSION"
        return 0
    fi
    
    print_info "uv not found. Installing uv..."
    
    # Detect OS
    OS=$(uname -s)
    case $OS in
        Darwin)
            # macOS
            if command_exists brew; then
                print_info "Installing uv via Homebrew..."
                brew install uv
                print_status "uv installed via Homebrew"
                return 0
            fi
            ;;
        Linux)
            # Linux - try package managers
            if command_exists apt-get; then
                print_info "Detected apt package manager"
            elif command_exists yum; then
                print_info "Detected yum package manager"
            elif command_exists pacman; then
                print_info "Detected pacman package manager"
            fi
            ;;
    esac
    
    # Fallback to curl installation
    print_info "Installing uv via curl..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    
    # Add to PATH for current session
    export PATH="$HOME/.cargo/bin:$PATH"
    
    if command_exists uv; then
        print_status "uv installed successfully"
        return 0
    else
        print_error "Failed to install uv. Please install manually: https://docs.astral.sh/uv/getting-started/installation/"
        return 1
    fi
}

# Setup MCP configuration
setup_mcp_config() {
    print_info "Setting up MCP configuration..."
    
    # Create .toolmux directory for configuration
    CONFIG_DIR="$HOME/.toolmux"
    mkdir -p "$CONFIG_DIR"
    
    USER_MCP_CONFIG="$CONFIG_DIR/mcp.json"
    
    if [ -f "$USER_MCP_CONFIG" ]; then
        print_status "User MCP config already exists at $USER_MCP_CONFIG"
        
        # Ask if user wants to merge with example config
        if [ -f "example_mcp.json" ]; then
            echo -n "Do you want to merge with the example MCP configuration? (y/n): "
            read -r response
            if [ "$response" = "y" ] || [ "$response" = "Y" ]; then
                # Simple merge - just inform user to do it manually for now
                print_info "Please manually merge configurations from example_mcp.json"
                print_info "Or backup your current config and replace it with the example"
            fi
        fi
    else
        # Copy example config if it exists
        if [ -f "example_mcp.json" ]; then
            cp "example_mcp.json" "$USER_MCP_CONFIG"
            print_status "MCP configuration copied to $USER_MCP_CONFIG"
        else
            print_warning "example_mcp.json not found"
        fi
    fi
}

# Setup workspace configuration
setup_workspace_config() {
    print_info "Setting up workspace configuration..."
    
    # Create .toolmux directory in current workspace for project-specific config
    WORKSPACE_CONFIG=".toolmux"
    mkdir -p "$WORKSPACE_CONFIG"
    
    # Copy mcp.json to workspace if it exists
    if [ -f "mcp.json" ]; then
        WORKSPACE_MCP="$WORKSPACE_CONFIG/mcp.json"
        if [ ! -f "$WORKSPACE_MCP" ]; then
            cp "mcp.json" "$WORKSPACE_MCP"
            print_status "Workspace MCP config copied to $WORKSPACE_MCP"
        else
            print_status "Workspace MCP config already exists at $WORKSPACE_MCP"
        fi
    fi
    
    # Create a simple config guide
    README_CONFIG="$WORKSPACE_CONFIG/README.md"
    if [ ! -f "$README_CONFIG" ]; then
        cat > "$README_CONFIG" << 'EOF'
# ToolMux Configuration

This directory contains project-specific ToolMux configuration.

## Files:
- `mcp.json`: MCP server configuration for this project
- `agent_config.json`: Agent-specific configuration (optional)

## Usage:
ToolMux will look for configuration in this order:
1. Current directory `.toolmux/mcp.json`
2. User home directory `~/.toolmux/mcp.json`
3. Built-in example configuration

## Customization:
Copy and modify `example_mcp.json` and `example_agent_config.json` from the main directory.
EOF
        print_status "Created configuration guide at $README_CONFIG"
    fi
}

# Make scripts executable
make_executable() {
    print_info "Making scripts executable..."
    
    for script in "toolmux.py" "toolmux_hook.sh"; do
        if [ -f "$script" ]; then
            chmod +x "$script"
            print_status "Made $script executable"
        fi
    done
}

# Create symlinks
create_symlinks() {
    print_info "Creating symlinks..."
    
    # Create symlink in user's local bin if it exists
    LOCAL_BIN="$HOME/.local/bin"
    if [ -d "$LOCAL_BIN" ]; then
        TOOLMUX_LINK="$LOCAL_BIN/toolmux"
        TOOLMUX_SCRIPT="$(pwd)/toolmux.py"
        
        if [ ! -L "$TOOLMUX_LINK" ]; then
            ln -s "$TOOLMUX_SCRIPT" "$TOOLMUX_LINK" 2>/dev/null || {
                print_warning "Could not create symlink: $TOOLMUX_LINK"
            }
            if [ -L "$TOOLMUX_LINK" ]; then
                print_status "Created symlink: $TOOLMUX_LINK -> $TOOLMUX_SCRIPT"
            fi
        else
            print_status "Symlink already exists: $TOOLMUX_LINK"
        fi
    else
        print_info "Creating $LOCAL_BIN directory..."
        mkdir -p "$LOCAL_BIN"
        # Add to PATH in shell profile if not already there
        SHELL_PROFILE=""
        if [ -f "$HOME/.bashrc" ]; then
            SHELL_PROFILE="$HOME/.bashrc"
        elif [ -f "$HOME/.zshrc" ]; then
            SHELL_PROFILE="$HOME/.zshrc"
        elif [ -f "$HOME/.profile" ]; then
            SHELL_PROFILE="$HOME/.profile"
        fi
        
        if [ -n "$SHELL_PROFILE" ]; then
            if ! grep -q "$LOCAL_BIN" "$SHELL_PROFILE"; then
                echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$SHELL_PROFILE"
                print_status "Added $LOCAL_BIN to PATH in $SHELL_PROFILE"
            fi
        fi
    fi
}

# Print usage instructions
print_usage_instructions() {
    echo
    echo "============================================================"
    echo -e "${GREEN}🎉 ToolMux Setup Complete!${NC}"
    echo "============================================================"
    echo
    echo "Usage Instructions:"
    echo "1. Run ToolMux directly:"
    echo "   python toolmux.py --help"
    echo
    echo "2. If symlink was created:"
    echo "   toolmux --help"
    echo
    echo "3. Configuration files:"
    echo "   - User config: $HOME/.kiro/settings/mcp.json"
    echo "   - Workspace config: .kiro/settings/mcp.json"
    echo
    echo "4. Example agent config:"
    echo "   See example_agent_config.json for agent integration"
    echo
    echo "5. Hook script:"
    echo "   Use toolmux_hook.sh for automated execution"
    echo
    echo "For more information, see README.md"
    echo "============================================================"
}

# Main setup function
main() {
    echo -e "${BLUE}🚀 ToolMux Setup Script${NC}"
    echo "========================================"
    
    # Check Python version
    check_python
    
    # Install Python requirements
    install_python_requirements
    
    # Check and install uv
    if ! install_uv; then
        print_warning "uv installation failed. Some MCP servers may not work."
    fi
    
    # Setup configurations
    setup_mcp_config
    setup_workspace_config
    
    # Make scripts executable
    make_executable
    
    # Create symlinks
    create_symlinks
    
    # Print usage instructions
    print_usage_instructions
}

# Run main function
main "$@"