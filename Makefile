# ToolMux Makefile
# Provides convenient commands for setup, installation, and development

.PHONY: help setup install clean test lint format dev-setup

# Default target
help:
	@echo "ToolMux - MCP Tool Multiplexer"
	@echo "=============================="
	@echo ""
	@echo "Available commands:"
	@echo "  make setup      - Run full setup (Python + shell script)"
	@echo "  make install    - Install ToolMux and dependencies"
	@echo "  make clean      - Clean up temporary files"
	@echo "  make test       - Run tests (if available)"
	@echo "  make lint       - Run code linting"
	@echo "  make format     - Format code"
	@echo "  make dev-setup  - Setup development environment"
	@echo "  make help       - Show this help message"

# Full setup using Python script
setup:
	@echo "🚀 Running ToolMux setup..."
	python3 setup.py

# Alternative setup using shell script
setup-sh:
	@echo "🚀 Running ToolMux setup (shell)..."
	./setup.sh

# Install dependencies only
install:
	@echo "📦 Installing dependencies..."
	python3 -m pip install -r requirements.txt
	@echo "✓ Dependencies installed"

# Clean up temporary files
clean:
	@echo "🧹 Cleaning up..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	@echo "✓ Cleanup complete"

# Run tests
test:
	@echo "🧪 Running tests..."
	python3 -m pytest tests/ -v

# Run HTTP transport tests specifically
test-http:
	@echo "🌐 Running HTTP transport tests..."
	python3 tests/test_http_transport.py

# Start test HTTP server for development
test-server:
	@echo "🚀 Starting test HTTP MCP server..."
	python3 tests/test_http_server.py

# Lint code
lint:
	@echo "🔍 Running code linting..."
	@if command -v flake8 >/dev/null 2>&1; then \
		flake8 toolmux.py --max-line-length=100; \
	else \
		echo "flake8 not installed. Install with: pip install flake8"; \
	fi

# Format code
format:
	@echo "✨ Formatting code..."
	@if command -v black >/dev/null 2>&1; then \
		black toolmux.py --line-length=100; \
	else \
		echo "black not installed. Install with: pip install black"; \
	fi

# Development setup
dev-setup: install
	@echo "🛠️ Setting up development environment..."
	python3 -m pip install flake8 black pytest
	@echo "✓ Development tools installed"

# Quick start
quickstart: setup
	@echo ""
	@echo "🎉 ToolMux is ready!"
	@echo "Try: python3 toolmux.py --help"