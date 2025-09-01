#!/bin/bash

# ToolMux Quick Installer
# A simple script to install ToolMux for any user

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   print_error "This script should not be run as root for security reasons"
   exit 1
fi

print_status "Starting ToolMux installation..."

# Detect OS
OS="unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
    OS="windows"
fi

print_status "Detected OS: $OS"

# Find compatible Python version (3.10+)
PYTHON_CMD=""
PYTHON_VERSION=""
PIP_CMD=""

# List of Python commands to try (prioritize newer versions)
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
    "python3"
)

print_status "Searching for compatible Python version (3.10+)..."

for cmd in "${PYTHON_CANDIDATES[@]}"; do
    if command -v "$cmd" &> /dev/null; then
        # Check if this Python version is 3.10+
        if $cmd -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PYTHON_CMD="$cmd"
            PYTHON_VERSION=$($cmd --version 2>&1 | cut -d' ' -f2)
            print_success "Found compatible Python: $cmd (version $PYTHON_VERSION)"
            break
        else
            VERSION=$($cmd --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
            print_warning "Found $cmd (version $VERSION) but fastmcp requires Python 3.10+"
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    print_error "No compatible Python version found (3.10+ required for fastmcp)"
    print_status "Please install Python 3.10+ and try again"
    print_status "On macOS with Homebrew: brew install python@3.11"
    exit 1
fi

# Find corresponding pip
if [[ "$PYTHON_CMD" == *"python3.11"* ]]; then
    PIP_CANDIDATES=("${PYTHON_CMD/python3.11/pip3.11}" "${PYTHON_CMD/python/pip}" "pip3.11")
elif [[ "$PYTHON_CMD" == *"python3.10"* ]]; then
    PIP_CANDIDATES=("${PYTHON_CMD/python3.10/pip3.10}" "${PYTHON_CMD/python/pip}" "pip3.10")
elif [[ "$PYTHON_CMD" == *"python3.12"* ]]; then
    PIP_CANDIDATES=("${PYTHON_CMD/python3.12/pip3.12}" "${PYTHON_CMD/python/pip}" "pip3.12")
else
    PIP_CANDIDATES=("pip3" "$PYTHON_CMD -m pip")
fi

for pip_cmd in "${PIP_CANDIDATES[@]}"; do
    if command -v $pip_cmd &> /dev/null || [[ "$pip_cmd" == *"-m pip" ]]; then
        PIP_CMD="$pip_cmd"
        break
    fi
done

if [[ -z "$PIP_CMD" ]]; then
    print_warning "pip not found, using python -m pip"
    PIP_CMD="$PYTHON_CMD -m pip"
fi

# Install Python dependencies
print_status "Installing Python dependencies with $PIP_CMD..."

PYTHON_MAJOR_MINOR=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

if $PYTHON_CMD -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
    # Python 3.10+, can install all requirements including fastmcp
    print_status "Installing all requirements (Python $PYTHON_MAJOR_MINOR supports fastmcp)"
    if ! $PIP_CMD install --user -r requirements.txt; then
        print_error "Failed to install some dependencies"
        print_warning "You may need to install them manually"
    fi
else
    # Python < 3.10, install requirements except fastmcp
    print_warning "Python $PYTHON_MAJOR_MINOR detected - installing requirements except fastmcp"
    print_status "Some features may be limited without fastmcp"
    
    # Install dependencies one by one, skipping fastmcp
    while IFS= read -r line; do
        # Skip comments and empty lines
        if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "$line" ]]; then
            continue
        fi
        
        # Skip fastmcp for older Python versions
        if [[ "$line" =~ ^fastmcp ]]; then
            print_warning "Skipping fastmcp (requires Python 3.10+)"
            continue
        fi
        
        # Install the dependency
        if ! $PIP_CMD install --user "$line"; then
            print_warning "Failed to install: $line"
        fi
    done < requirements.txt
fi

# Create config directory
CONFIG_DIR="$HOME/.toolmux"
print_status "Creating configuration directory: $CONFIG_DIR"
mkdir -p "$CONFIG_DIR"

# Copy configuration files
if [[ -f "mcp.json" ]]; then
    cp mcp.json "$CONFIG_DIR/"
    print_success "Copied mcp.json to $CONFIG_DIR"
fi

if [[ -f "example_agent_config.json" ]]; then
    cp example_agent_config.json "$CONFIG_DIR/"
    print_success "Copied example_agent_config.json to $CONFIG_DIR"
fi

# Make toolmux.py executable
chmod +x toolmux.py

# Add to PATH (optional)
read -p "Would you like to add ToolMux to your PATH? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    TOOLMUX_DIR=$(pwd)
    
    # Determine shell config file
    SHELL_CONFIG=""
    if [[ -f "$HOME/.bashrc" ]]; then
        SHELL_CONFIG="$HOME/.bashrc"
    elif [[ -f "$HOME/.zshrc" ]]; then
        SHELL_CONFIG="$HOME/.zshrc"
    elif [[ -f "$HOME/.profile" ]]; then
        SHELL_CONFIG="$HOME/.profile"
    fi
    
    if [[ -n "$SHELL_CONFIG" ]]; then
        echo "" >> "$SHELL_CONFIG"
        echo "# ToolMux" >> "$SHELL_CONFIG"
        echo "export PATH=\"$TOOLMUX_DIR:\$PATH\"" >> "$SHELL_CONFIG"
        print_success "Added ToolMux to PATH in $SHELL_CONFIG"
        print_warning "Please restart your terminal or run: source $SHELL_CONFIG"
    else
        print_warning "Could not determine shell config file"
        print_status "You can manually add $TOOLMUX_DIR to your PATH"
    fi
fi

print_success "ToolMux installation completed!"
print_status "Configuration files are in: $CONFIG_DIR"
print_status "You can now run: ./toolmux.py --help"

# Update shebang in toolmux.py to use the correct Python
if [[ -f "toolmux.py" ]]; then
    # Create a backup
    cp toolmux.py toolmux.py.bak
    
    # Update shebang to use the compatible Python
    sed "1s|.*|#!$PYTHON_CMD|" toolmux.py.bak > toolmux.py
    chmod +x toolmux.py
    print_success "Updated toolmux.py to use $PYTHON_CMD"
fi

# Test installation
print_status "Testing installation..."
if $PYTHON_CMD toolmux.py --help > /dev/null 2>&1; then
    print_success "ToolMux is working correctly!"
else
    print_warning "There might be an issue with the installation"
    print_status "Try running: $PYTHON_CMD toolmux.py --help"
fi

echo
print_status "Next steps:"
echo "1. Review the configuration in $CONFIG_DIR"
echo "2. Run: $PYTHON_CMD toolmux.py --help to see available options"
echo "3. Or if PATH was updated: ./toolmux.py --help"
echo "4. Check the README.md for usage examples"
echo
print_success "Happy coding with ToolMux!"
print_status "Note: Using Python $PYTHON_VERSION at $PYTHON_CMD"