# ToolMux 🛠️

🚀 **98.65% Token Reduction** - Efficient MCP server aggregation with HTTP/SSE support and on-demand loading

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP Compatible](https://img.shields.io/badge/MCP-2024--11--05-green.svg)](https://modelcontextprotocol.io/)

## The Problem

Traditional MCP bridges load **all tool schemas upfront**, consuming 15-20% of your token budget before you even start:

- Large deployments can have hundreds of tools across multiple servers
- Each schema consumes tokens even if never used
- Mixed stdio/HTTP servers require separate client implementations
- **Result**: Token budgets exhausted before real work begins

## The Solution

ToolMux exposes only **4 meta-tools** with unified stdio/HTTP support and loads servers on-demand:

| Approach | Tools Loaded | Token Usage | Transport Support | Functionality |
|----------|--------------|-------------|-------------------|---------------|
| **Traditional Bridge** | All schemas | 15-20% tokens | Single protocol | ✅ Full access |
| **ToolMux** | 4 meta-tools | 1.35% tokens | Mixed stdio/HTTP | ✅ Full access |

## Real Performance

In a deployment with 200+ tools across 11 MCP servers (stdio + HTTP):
- **Before**: ~20% token usage for schema loading
- **After**: 1.35% token usage with ToolMux  
- **Savings**: 98.65% reduction in overhead
- **Bonus**: Unified interface for mixed transport protocols

## Requirements

- **Python 3.10+** (required for fastmcp dependency)
- pip3 (Python package manager)
- Virtual environment support (recommended)

**Dependencies**:
- `fastmcp>=0.2.0` - FastMCP runtime for MCP protocol support
- `httpx>=0.24.0` - HTTP client for HTTP/SSE MCP servers
- `websockets>=11.0.0` - WebSocket support for real-time communication
- `pydantic>=2.6.0` - Data validation and settings management
- `click>=8.0.0` - CLI interface and command handling

**Note**: Python 3.10+ is required for full functionality including HTTP/SSE transport support.

## Installation

### Quick Install (Recommended)
```bash
uvx toolmux
```

That's it! ToolMux will auto-configure on first run.

**🎉 Now available on PyPI: https://pypi.org/project/toolmux/**

### Latest Updates (v1.2.1)
- ✅ **Fixed**: First-time setup now properly copies all bundled resources (`Prompt/`, `scripts/`, `examples/`)
- ✅ **Enhanced**: Complete local access to agent instructions and scripts after installation
- ✅ **Improved**: Better user experience with all resources available in `~/toolmux/`

### Alternative Methods

#### Install as Persistent Tool
```bash
uv tool install toolmux
```

#### Install from Git (Development)
```bash
uvx --from git+https://github.com/subnetangel/ToolMux toolmux
```

#### Install Specific Version
```bash
uvx toolmux@1.2.1
```

#### Manual Install (Development)
```bash
# Clone the repository
git clone https://github.com/subnetangel/ToolMux.git
cd ToolMux

# Install dependencies
pip install -r requirements.txt

# Run directly
python toolmux.py
```

## Quick Start

### 1. Install and First Run
```bash
# Install ToolMux
uvx toolmux

# First run creates configuration
toolmux --list-servers
```

On first run, ToolMux creates:
- `~/toolmux/mcp.json` - Your main configuration file
- `~/toolmux/examples/` - Reference configurations for copy-paste

### 2. Configure Your Servers
Edit `~/toolmux/mcp.json` to add your MCP servers:

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
      "description": "Local filesystem access"
    },
    "brave-search": {
      "command": "uvx", 
      "args": ["mcp-server-brave-search"],
      "env": {"BRAVE_API_KEY": "your-key"},
      "description": "Web search using Brave Search API"
    },
    "remote-api": {
      "transport": "http",
      "base_url": "https://api.example.com/mcp",
      "headers": {"Authorization": "Bearer your-token"},
      "timeout": 30,
      "description": "Remote HTTP MCP server"
    }
  }
}
```

### 3. Run ToolMux
```bash
# Basic usage
toolmux

# With custom config
toolmux --config /path/to/custom.json

# List configured servers
toolmux --list-servers

# See all options
toolmux --help
```

## How It Works

ToolMux exposes 4 efficient meta-tools:

### 🔍 Discovery
```bash
catalog_tools  # List all available tools from all servers
```

### 📋 Schema
```bash
get_tool_schema({"name": "read_file"})  # Get parameters for specific tool
```

### ⚡ Execute  
```bash
invoke({"name": "read_file", "args": {"path": "/tmp/test.txt"}})  # Run any tool
```

### 📊 Stats
```bash
get_tool_count  # Show tool count by server
```

## HTTP/SSE MCP Support 🌐

ToolMux supports **mixed configurations** with both stdio and HTTP/SSE MCP servers:

### Architecture
```
Q CLI (stdio) ↔ ToolMux (stdio) ↔ Mixed MCP Servers
                                  ├── stdio servers
                                  └── HTTP/SSE servers
```

### Benefits
- **Unified Interface**: Q CLI sees all tools as single stdio server
- **Mixed Deployments**: Combine local stdio + remote HTTP servers  
- **Transparent Routing**: ToolMux handles protocol translation
- **Backward Compatible**: Existing stdio configs unchanged
- **Scalable**: Add HTTP servers without Q CLI changes

### HTTP Server Configuration
```json
{
  "servers": {
    "local-stdio": {
      "command": "python", 
      "args": ["server.py"]
    },
    "remote-http": {
      "transport": "http",
      "base_url": "https://api.example.com/mcp",
      "headers": {"Authorization": "Bearer token"},
      "timeout": 30,
      "sse_endpoint": "/events"
    }
  }
}
```

### Authentication Options
- **Bearer Tokens**: `"Authorization": "Bearer your-token"`
- **API Keys**: `"X-API-Key": "your-api-key"`
- **OAuth**: `"Authorization": "Bearer oauth-token"`
- **Custom Headers**: Any additional headers needed

### Testing HTTP Support
```bash
# Start test HTTP server
python test_http_server.py

# Test mixed configuration
python test_http_transport.py

# Run ToolMux with mixed servers
./toolmux.py --config mixed_servers.json
```

## Adding Servers

ToolMux uses a single `mcp.json` configuration file. Copy examples from `~/toolmux/examples/` into your main config.

### Popular MCP Servers

#### Filesystem Access
```json
"filesystem": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
  "description": "Local filesystem access"
}
```

#### Web Search (Brave)
```json
"brave-search": {
  "command": "uvx",
  "args": ["mcp-server-brave-search"],
  "env": {"BRAVE_API_KEY": "your-api-key"},
  "description": "Web search using Brave Search API"
}
```

#### Database Access (SQLite)
```json
"sqlite": {
  "command": "uvx",
  "args": ["mcp-server-sqlite", "--db-path", "/path/to/database.sqlite"],
  "description": "SQLite database queries"
}
```

#### GitHub Integration
```json
"github": {
  "command": "uvx",
  "args": ["mcp-server-github"],
  "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "your-token"},
  "description": "GitHub repository and issue management"
}
```

#### HTTP MCP Server
```json
"remote-api": {
  "transport": "http",
  "base_url": "https://api.example.com/mcp",
  "headers": {"Authorization": "Bearer your-token"},
  "timeout": 30,
  "description": "Remote HTTP MCP server"
}
```

### Configuration Reference

All server configurations support:
- `command` + `args`: Command to run (stdio servers)
- `transport`: "http" for HTTP servers (default: stdio)
- `base_url`: HTTP server endpoint
- `headers`: HTTP headers for authentication
- `timeout`: Request timeout in seconds
- `env`: Environment variables
- `cwd`: Working directory
- `description`: Human-readable description

## Agent Integration

### Q CLI Integration

#### Quick Start (Recommended)
```json
{
  "name": "simple-toolmux-agent",
  "mcpServers": {
    "toolmux": {
      "command": "uvx",
      "args": ["toolmux"],
      "timeout": 30000
    }
  },
  "tools": ["*"],
  "systemPrompt": "Use catalog_tools to see available tools, get_tool_schema for parameters, and invoke to execute tools."
}
```

#### Complete Configuration
See `toolmux/examples/q-cli-agent.json` for a comprehensive Q CLI configuration with:
- Detailed system prompt explaining ToolMux workflow
- All 4 meta-tools explicitly listed
- Hooks and examples
- Alternative installation methods

#### Available Examples
After installation, examples are available in the package:
```bash
# Find example configurations
python -c "import toolmux; import os; print(os.path.join(os.path.dirname(toolmux.__file__), 'examples'))"
```

- `q-cli-simple.json` - Minimal configuration to get started
- `q-cli-agent.json` - Complete configuration with all features
- `example_agent_config.json` - Legacy example (updated for v1.2.1)

### Other AI Clients
Include the agent instructions from the installed package to ensure proper meta-tool usage:

```bash
# After installing with uvx/uv, find the instructions at:
python -c "import toolmux; import os; print(os.path.join(os.path.dirname(toolmux.__file__), 'Prompt', 'AGENT_INSTRUCTIONS.md'))"
```

## Files Included

### Core Package
- `toolmux/main.py` - Main multiplexer server
- `toolmux/examples/` - Configuration examples and templates
- `toolmux/Prompt/AGENT_INSTRUCTIONS.md` - Agent behavior guide
- `toolmux/scripts/toolmux_hook.sh` - Q CLI agent hook

### Configuration Files
- `mcp.json` - Default server configuration (created on first run)
- Example configurations in `toolmux/examples/`:
  - `q-cli-simple.json` - Minimal Q CLI setup
  - `q-cli-agent.json` - Complete Q CLI configuration
  - `example_agent_config.json` - Legacy example (updated for v1.2.1)

## Benefits

✅ **98.65% token reduction** - Only 4 tools vs hundreds of schemas  
✅ **On-demand loading** - Servers start when needed  
✅ **Standard config** - Uses familiar `mcp.json` format  
✅ **Zero breaking changes** - Works with any MCP server  
✅ **Full functionality** - Access all tools through meta-tools  

## Use Cases

Perfect for:
- **AI Assistants** with multiple MCP servers
- **Token-constrained environments** 
- **Large MCP deployments** (10+ servers)
- **Development workflows** with many tools

## Architecture

### System Overview

```mermaid
graph TB
    subgraph "AI Client Layer"
        QCli["Q CLI Agent"]
        Claude["Claude Desktop"]
        Custom["Custom AI Client"]
    end
    
    subgraph "ToolMux Core"
        TM["ToolMux Server<br/>(4 Meta-Tools)"]
        Cache["Tool Cache"]
        Router["Protocol Router"]
    end
    
    subgraph "MCP Server Layer"
        subgraph "Stdio Servers"
            FS["Filesystem<br/>Server"]
            SQLite["SQLite<br/>Server"]
            Git["Git<br/>Server"]
        end
        
        subgraph "HTTP/SSE Servers"
            API1["Remote API<br/>Server"]
            Search["Search<br/>Service"]
            Cloud["Cloud<br/>Service"]
        end
    end
    
    QCli -.->|stdio| TM
    Claude -.->|stdio| TM
    Custom -.->|stdio| TM
    
    TM --> Cache
    TM --> Router
    
    Router -->|stdio| FS
    Router -->|stdio| SQLite
    Router -->|stdio| Git
    Router -->|HTTP/SSE| API1
    Router -->|HTTP/SSE| Search
    Router -->|HTTP/SSE| Cloud
    
    style TM fill:#e1f5fe
    style Router fill:#f3e5f5
    style Cache fill:#e8f5e8
```

### Token Usage Comparison

```mermaid
pie title Token Usage: Traditional vs ToolMux
    "Traditional: Schema Loading" : 18.65
    "Traditional: Actual Work" : 81.35
    "ToolMux: Meta-Tools" : 1.35
    "ToolMux: Actual Work" : 98.65
```

### Mixed Transport Architecture

```mermaid
graph LR
    subgraph "Client"
        Agent["AI Agent<br/>(Q CLI)"]
    end
    
    subgraph "ToolMux"
        Core["ToolMux Core<br/>stdio interface"]
        HTTP["HTTP Client"]
        Stdio["Stdio Manager"]
    end
    
    subgraph "MCP Servers"
        S1["Local Server 1<br/>(stdio)"]
        S2["Local Server 2<br/>(stdio)"]
        S3["Remote Server 1<br/>(HTTP)"]
        S4["Remote Server 2<br/>(SSE)"]
    end
    
    Agent -->|stdio| Core
    Core --> HTTP
    Core --> Stdio
    
    Stdio -->|subprocess| S1
    Stdio -->|subprocess| S2
    HTTP -->|HTTPS| S3
    HTTP -->|WebSocket/SSE| S4
    
    style Core fill:#e1f5fe
    style HTTP fill:#fff3e0
    style Stdio fill:#e8f5e8
```

## Interaction Flow

### Tool Discovery and Execution Flow

```mermaid
sequenceDiagram
    participant Agent as AI Agent
    participant TM as ToolMux
    participant Cache as Tool Cache
    participant Server as MCP Server
    
    Note over Agent,Server: 1. Discovery Phase
    Agent->>TM: catalog_tools()
    TM->>Cache: Check cached tools
    alt Cache Miss
        TM->>Server: Start server (on-demand)
        Server-->>TM: Server ready
        TM->>Server: List tools
        Server-->>TM: Tool list
        TM->>Cache: Cache tools
    else Cache Hit
        Cache-->>TM: Return cached tools
    end
    TM-->>Agent: All available tools
    
    Note over Agent,Server: 2. Schema Retrieval
    Agent->>TM: get_tool_schema({"name": "read_file"})
    TM->>Cache: Check schema cache
    alt Schema Cached
        Cache-->>TM: Return schema
    else Schema Not Cached
        TM->>Server: Get tool schema
        Server-->>TM: Tool schema
        TM->>Cache: Cache schema
    end
    TM-->>Agent: Tool schema
    
    Note over Agent,Server: 3. Tool Execution
    Agent->>TM: invoke({"name": "read_file", "args": {...}})
    TM->>Server: Execute tool
    Server-->>TM: Tool result
    TM-->>Agent: Execution result
```

### HTTP vs Stdio Server Handling

```mermaid
flowchart TD
    Start([Tool Request]) --> Check{Server Type?}
    
    Check -->|stdio| StdioFlow[Stdio Flow]
    Check -->|HTTP| HTTPFlow[HTTP Flow]
    
    subgraph "Stdio Processing"
        StdioFlow --> StartProc[Start subprocess]
        StartProc --> SendJSON[Send JSON-RPC]
        SendJSON --> ReadResp[Read response]
        ReadResp --> StdioResult[Return result]
    end
    
    subgraph "HTTP Processing"
        HTTPFlow --> HTTPReq[HTTP Request]
        HTTPReq --> Auth[Add authentication]
        Auth --> SendHTTP[Send to endpoint]
        SendHTTP --> ParseHTTP[Parse response]
        ParseHTTP --> HTTPResult[Return result]
    end
    
    StdioResult --> End([Result to Agent])
    HTTPResult --> End
    
    style StdioFlow fill:#e8f5e8
    style HTTPFlow fill:#fff3e0
```

### On-Demand Server Loading

```mermaid
stateDiagram-v2
    [*] --> Idle: ToolMux starts
    
    Idle --> CheckCache: Tool request received
    CheckCache --> ServerRunning: Server already running
    CheckCache --> StartServer: Server not running
    
    StartServer --> Initializing: Launch server process
    Initializing --> Ready: Server responds
    Initializing --> Failed: Server fails to start
    
    Ready --> ServerRunning: Server available
    ServerRunning --> ExecuteTool: Forward request
    ExecuteTool --> ServerRunning: Tool executed
    
    ServerRunning --> Idle: Request complete
    Failed --> [*]: Error returned
    
    note right of StartServer
        Only starts when
        tool is requested
    end note
    
    note right of ServerRunning
        Server stays running
        for subsequent requests
    end note
```

### Error Handling Flow

```mermaid
flowchart TD
    Request[Tool Request] --> Validate{Valid Request?}
    
    Validate -->|No| ValidationError[Return validation error]
    Validate -->|Yes| FindServer{Server exists?}
    
    FindServer -->|No| ServerError[Return server not found]
    FindServer -->|Yes| CheckRunning{Server running?}
    
    CheckRunning -->|No| StartServer[Start server]
    CheckRunning -->|Yes| ExecuteTool[Execute tool]
    
    StartServer --> StartSuccess{Start successful?}
    StartSuccess -->|No| StartError[Return startup error]
    StartSuccess -->|Yes| ExecuteTool
    
    ExecuteTool --> ToolSuccess{Tool executed?}
    ToolSuccess -->|No| ToolError[Return execution error]
    ToolSuccess -->|Yes| Success[Return result]
    
    ValidationError --> ErrorResponse[Format error response]
    ServerError --> ErrorResponse
    StartError --> ErrorResponse
    ToolError --> ErrorResponse
    
    ErrorResponse --> End[Return to agent]
    Success --> End
    
    style ValidationError fill:#ffebee
    style ServerError fill:#ffebee
    style StartError fill:#ffebee
    style ToolError fill:#ffebee
    style Success fill:#e8f5e8
```

## License

MIT License - see LICENSE file for details

---

*Built for the MCP community to make AI assistants more efficient* 🤖
