# CLAUDE.md - ToolMux

## Project Overview

ToolMux is an MCP (Model Context Protocol) server aggregation tool that achieves ~98.65% token reduction by exposing 4 meta-tools instead of loading hundreds of individual tool schemas upfront. It supports both stdio and HTTP/SSE transports.

- **Version**: 2.2.1
- **License**: MIT
- **Python**: 3.10+
- **PyPI**: https://pypi.org/project/toolmux/

## Repository Structure

```
ToolMux/
├── toolmux/                    # Main Python package
│   ├── __init__.py             # Package init, exports main/ToolMux/HttpMcpClient
│   ├── main.py                 # Core implementation (~684 lines, single module)
│   ├── Prompt/                 # Agent instructions bundled with package
│   │   └── AGENT_INSTRUCTIONS.md
│   ├── examples/               # 11 JSON config templates (bundled with package)
│   └── scripts/                # Helper scripts (toolmux_hook.sh)
├── tests/                      # pytest test suite (8 modules)
│   ├── test_simple.py          # Basic functionality
│   ├── test_http_transport.py  # HTTP/SSE transport
│   ├── test_http_mcp.py        # HTTP MCP protocol
│   ├── test_http_server.py     # Mock HTTP server for testing
│   ├── test_mcp_protocol.py    # MCP protocol compliance
│   ├── test_e2e.py             # End-to-end integration
│   ├── test_e2e_simple.py      # Simplified E2E
│   └── test_e2e_pypi.py        # PyPI installation E2E
├── docs/                       # Extended documentation
│   ├── ARCHITECTURE.md         # Detailed architecture (~53KB)
│   ├── DEPLOYMENT_PLAN.md      # Deployment strategy
│   ├── FIX_SUMMARY.md          # Bug fix summaries
│   ├── GIT_COMMIT_CHECKLIST.md # Pre-commit checklist
│   └── PUBLICATION_REPORT.md   # PyPI publication details
├── pyproject.toml              # Project metadata (setuptools build)
├── requirements.txt            # Runtime dependencies
├── Makefile                    # Build/test/lint commands
├── mcp.json                    # Default server configuration
├── CHANGELOG.md                # Version history
├── AGENT_INSTRUCTIONS.md       # Agent integration guide
├── setup.sh / install.sh       # Shell-based setup scripts
└── README.md                   # Main documentation
```

## Architecture

The entire server implementation lives in a single module: `toolmux/main.py`.

### Key Classes

- **`HttpMcpClient`** (lines 19-145) - HTTP/SSE client for remote MCP servers. Handles JSON-RPC over HTTP with fallback endpoints (`/mcp` then `/rpc`), authentication headers, and timeout management.
- **`ToolMux`** (lines 147-478) - Core multiplexer server. Aggregates stdio and HTTP backend servers, manages server processes, caches tool lists, and handles MCP protocol requests.

### Key Functions

- `setup_first_run()` (line 480) - Creates `~/toolmux/` directory with config and examples on first run
- `create_basic_examples()` (line 557) - Generates fallback example configs
- `find_config_file()` (line 601) - Config discovery: explicit path > `./mcp.json` > `~/toolmux/mcp.json` > first-run setup
- `load_config()` (line 624) - Parses `mcp.json` and returns the `servers` dict
- `main()` (line 640) - CLI entry point with argparse (`--config`, `--version`, `--list-servers`)

### Meta-Tools Exposed via MCP

Instead of proxying all backend tool schemas, ToolMux exposes exactly 4 meta-tools:

1. **`catalog_tools`** - List all available tools from backend servers (name, server, summary)
2. **`get_tool_schema`** - Get input schema for a specific tool by name
3. **`invoke`** - Execute any backend tool by name with args
4. **`get_tool_count`** - Get tool count statistics grouped by server

### Transport Support

- **stdio**: Spawns backend MCP servers as subprocesses, communicates via stdin/stdout JSON-RPC
- **HTTP/SSE**: Connects to remote MCP servers over HTTP, uses JSON-RPC POST to `/mcp` (fallback `/rpc`)

### Configuration Format (`mcp.json`)

```json
{
  "servers": {
    "server-name": {
      "command": "npx",           // stdio: command to run
      "args": ["-y", "..."],      // stdio: command arguments
      "env": {},                  // stdio: environment variables
      "cwd": "/path",             // stdio: working directory
      "transport": "http",        // http: set to "http" for HTTP transport
      "base_url": "https://...",  // http: server URL
      "headers": {},              // http: request headers
      "timeout": 30,              // http: timeout in seconds
      "description": "..."        // both: human-readable description
    }
  }
}
```

## Development Commands

```bash
# Run tests
make test                        # Full pytest suite
python3 -m pytest tests/ -v     # Direct pytest invocation
make test-http                   # HTTP transport tests only
make test-server                 # Start mock HTTP server

# Code quality
make lint                        # flake8 (if installed)
make format                      # black formatter (if installed)

# Setup
make install                     # Install runtime dependencies
make dev-setup                   # Install dev tools (flake8, black, pytest)
make setup                       # Full setup via setup.py

# Cleanup
make clean                       # Remove __pycache__, .pyc, .egg-info
```

## Dependencies

### Runtime
- `fastmcp>=3.1.1,<4` - MCP server/client framework (proxy, mount, tool transforms, schema compression)
- `mcp>=1.20.0` - MCP protocol SDK (types, transports, session management)
- `click>=8.0.0` - CLI interface
- `pydantic>=2.6.0` - Data validation
- `httpx>=0.24.0` - HTTP client
- `websockets>=11.0.0` - WebSocket support
- `python-dotenv>=1.0.1` - Environment variables

### Dev (optional)
- `pytest>=7.0.0`, `black>=23.0.0`, `ruff>=0.1.0`, `mypy>=1.0.0`

### Server (optional)
- `fastapi>=0.104.0`, `uvicorn>=0.24.0`

## Code Conventions

- **Single-module design**: All core logic is in `toolmux/main.py`. Do not split into sub-modules without strong justification.
- **Version strings**: Must be kept in sync across `pyproject.toml`, `toolmux/__init__.py`, and `toolmux/main.py` (appears in `initialize()` calls, `handle_request()`, `setup_first_run()`, and argparse `--version`).
- **Protocol compliance**: All MCP protocol handling follows the MCP 2024-11-05 specification. JSON-RPC 2.0 format is used throughout.
- **Error output**: Diagnostic/error messages go to `stderr`. Protocol messages (JSON-RPC) go to `stdout`.
- **Transport abstraction**: `HttpMcpClient` instances and `subprocess.Popen` instances are both stored in `self.server_processes` and differentiated via `isinstance()` checks.
- **Tool metadata**: Internal `_server` and `_transport` keys are injected into tool dicts for routing purposes and stripped before external use where needed.
- **Config discovery order**: Explicit `--config` flag > `./mcp.json` (project-local) > `~/toolmux/mcp.json` (user global) > first-run auto-setup.
- **Line length**: Target 100 characters (configured in Makefile lint/format targets).
- **Type hints**: Python 3.10+ type hints are used (`Dict`, `Any`, `List`, `Optional`, `Union` from `typing`).

## Testing

Tests use pytest. The suite covers unit tests, HTTP transport, MCP protocol compliance, and end-to-end integration. Run `make test` or `python3 -m pytest tests/ -v` from the project root.

Key test patterns:
- `test_simple.py` validates basic tool discovery and MCP protocol handling
- `test_http_*.py` files test HTTP transport with mock servers
- `test_e2e*.py` files test full workflows including PyPI installation verification
- `test_http_server.py` provides a mock HTTP MCP server used by other test modules

## Entry Point

The CLI entry point is `toolmux.main:main` (defined in `pyproject.toml` `[project.scripts]`). Users run via `uvx toolmux`, `toolmux` (if installed), or `python3 -m toolmux.main`.

## Common Tasks

### Adding a new meta-tool
1. Add the tool definition in `handle_request()` under the `tools/list` method response (around line 318)
2. Add the handler in `handle_request()` under the `tools/call` method (around line 354)
3. Update tests in `tests/test_simple.py` and `tests/test_mcp_protocol.py`

### Updating the version
Update all three locations:
1. `pyproject.toml` - `version = "X.Y.Z"`
2. `toolmux/__init__.py` - `__version__ = "X.Y.Z"`
3. `toolmux/main.py` - Search for the old version string and replace all occurrences (appears in `initialize()`, `handle_request()`, `setup_first_run()`, and `argparse`)

### Adding a new transport type
1. Create a new client class similar to `HttpMcpClient`
2. Add detection logic in `ToolMux.start_server()` based on config `transport` field
3. Add `isinstance()` handling in `ToolMux.get_all_tools()` and `ToolMux.call_tool()`
