# ToolMux v2.0 - FastMCP Rewrite Specification

## Document Purpose
This is a complete, self-contained implementation spec for rewriting ToolMux to use FastMCP 2.14.x
as its foundation. Every code block is copy-paste ready. Every API reference is verified against
the installed package at `/usr/local/lib/python3.11/dist-packages/fastmcp/`. A dev agent should be
able to implement the entire rewrite from this document alone.

---

## 1. PROJECT CONTEXT

### What ToolMux Is
ToolMux is an MCP (Model Context Protocol) server that acts as a **proxy/gateway** for multiple
backend MCP servers. Instead of an agent connecting to 10 MCP servers individually (loading hundreds
of tool schemas), it connects to one ToolMux instance that aggregates everything.

- **Repository**: `/home/user/ToolMux/`
- **Current Version**: 1.2.1
- **Target Version**: 2.0.0
- **License**: MIT
- **Python**: 3.10+
- **PyPI**: `toolmux`
- **Entry point**: `toolmux.main:main` (defined in `pyproject.toml [project.scripts]`)

### Repository Structure
```
ToolMux/
├── toolmux/
│   ├── __init__.py          # Exports main/ToolMux/HttpMcpClient, __version__
│   ├── main.py              # ALL core logic (~684 lines, single module)
│   ├── Prompt/
│   │   └── AGENT_INSTRUCTIONS.md
│   ├── examples/            # 11 JSON config templates
│   └── scripts/             # Helper scripts
├── tests/
│   ├── test_simple.py       # Basic functionality (subprocess-based, uses toolmux.py)
│   ├── test_mcp_protocol.py # MCP protocol compliance (subprocess-based, uses toolmux.py)
│   ├── test_http_mcp.py     # HTTP MCP protocol (unit tests, imports ToolMux directly)
│   ├── test_http_transport.py # HTTP transport (unit tests)
│   ├── test_http_server.py  # Mock HTTP server for testing
│   ├── test_e2e.py          # End-to-end integration
│   ├── test_e2e_simple.py   # Simplified E2E
│   ├── test_e2e_pypi.py     # PyPI installation E2E
│   ├── test_token_analysis.py     # Token comparison (v1)
│   └── test_token_analysis_v2.py  # Token comparison (v2, progressive disclosure)
├── docs/
│   ├── SMART_PROXY_PLAN.md  # Previous design exploration
│   └── TOOLMUX_V2_SPEC.md  # THIS FILE
├── pyproject.toml
├── requirements.txt
├── mcp.json                 # Default server config
├── CLAUDE.md                # Project conventions
└── .gitignore
```

### Key Convention
**Single-module design**: All core logic lives in `toolmux/main.py`. Do NOT split into sub-modules.
The rewrite should maintain this pattern — one main file.

---

## 2. CURRENT STATE (What Exists Today)

### Architecture
The current implementation is **hand-rolled JSON-RPC over stdio**. It does NOT use FastMCP despite
listing it as a dependency. The entire server is a manual stdin/stdout JSON-RPC loop.

### Current Classes in `toolmux/main.py`

**`HttpMcpClient`** (lines 19-145): HTTP/SSE client for remote MCP servers.
- Makes JSON-RPC POST requests to `/mcp` (fallback `/rpc`)
- Handles initialize handshake, tools/list, tools/call
- Manages auth headers, timeouts
- Synchronous (uses `httpx.Client`, not `httpx.AsyncClient`)

**`ToolMux`** (lines 147-478): Core multiplexer.
- `__init__(servers_config)` - takes parsed mcp.json servers dict
- `start_server(name)` - spawns stdio subprocess OR creates HttpMcpClient
- `get_all_tools()` - iterates all servers, initializes each, fetches tools/list, caches result.
  Injects `_server` and `_transport` metadata keys into each tool dict.
- `call_tool(name, arguments)` - looks up tool in cache, routes to correct backend
- `handle_request(request)` - processes JSON-RPC: initialize, tools/list, tools/call
- `run()` - stdin readline loop, parses JSON, dispatches to handle_request

### Current tools/list Response (The Problem)
Returns exactly 4 hardcoded meta-tools:
```json
{
  "tools": [
    {"name": "catalog_tools", "description": "List all available tools from backend MCP servers",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_tool_schema", "description": "Get schema for a specific tool",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "invoke", "description": "Execute a backend tool",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "args": {"type": "object"}}, "required": ["name"]}},
    {"name": "get_tool_count", "description": "Get count of available tools by server",
     "inputSchema": {"type": "object", "properties": {}}}
  ]
}
```

### Current initialize Response (Missing `instructions`)
```json
{
  "protocolVersion": "2024-11-05",
  "capabilities": {"tools": {}},
  "serverInfo": {"name": "ToolMux", "version": "1.2.1"}
}
```
**No `instructions` field.** This is why agents don't know how to use the meta-tools without an
external AGENT_INSTRUCTIONS.md file injected into context.

### What's Wrong (Problems to Solve)

1. **FastMCP is a dependency but never imported or used.** The entire server is manually coded
   JSON-RPC. This means no protocol compliance guarantees, no transport abstraction, no built-in features.

2. **Agents can't use the meta-tools without external instructions.** When an agent sees `invoke`,
   `catalog_tools`, etc., it has no idea what backend tools exist or what workflow to follow.

3. **No `instructions` field in initialize response.** The MCP protocol (2024-11-05+) supports an
   `instructions` field that clients automatically inject into agent context. ToolMux doesn't send it.

4. **Dumb description truncation.** `catalog_tools` truncates descriptions at 80 chars (`desc[:80]`),
   which can cut mid-word and lose meaning.

5. **Full docstrings lost after discovery.** The full tool descriptions are cached internally but
   never provided to the agent at invocation time.

6. **No schema optimization.** When `get_tool_schema` returns a schema, it's the raw full schema.
   When tools are condensed for display, no intelligent schema reduction happens.

7. **Lazy loading blocks on first tool call.** Backend servers aren't started until `catalog_tools`
   or another meta-tool triggers `get_all_tools()`. All servers initialize sequentially.

---

## 3. TARGET STATE (What To Build)

### Core Principle
Rewrite `toolmux/main.py` to use **FastMCP 2.14.x** as the server framework. This gives us proper
MCP protocol handling, the `instructions` field, dynamic tool registration,
`notifications/tools/list_changed`, and clean transport management — all for free.

### Three Operating Modes

The server supports three modes, selectable via `--mode` CLI flag or `"mode"` field in mcp.json:

#### Mode 1: `meta` (current behavior, improved)
- **tools/list**: Returns the 4 meta-tools (catalog_tools, get_tool_schema, invoke, get_tool_count)
- **NEW**: The `instructions` field in the initialize response contains the full agent workflow guide
- **NEW**: `catalog_tools` uses smart description condensation (not dumb truncation)
- **NEW**: First invocation of each tool via `invoke` includes the full docstring in the result
- **Token savings**: 93-99%
- **Agent UX**: Self-documenting via `instructions` field — no external file needed

#### Mode 2: `proxy` (NEW — default mode)
- **tools/list**: Returns ALL backend tools with condensed schemas + `get_tool_schema` as a helper
- Agent calls tools **directly by their real names** (e.g., `read_file`, not `invoke`)
- ToolMux transparently routes to the correct backend
- Full docstring included in result on first invocation of each unique tool
- Full schema included in result on invocation errors
- **Token savings**: 55-75% (varies by tool complexity and count)
- **Agent UX**: Fully transparent — identical to connecting to the backend directly

#### Mode 3: `gateway` (NEW)
- **tools/list**: Tools grouped by server (one MCP tool per backend server)
- Each server-tool lists sub-tools in its description
- Calling pattern: `filesystem(tool="read_file", arguments={"path": "/tmp/x"})`
- **Token savings**: 87-92%
- **Agent UX**: Near-transparent, one level of indirection

### Configuration Format

**mcp.json** (extended — backwards compatible):
```json
{
  "mode": "proxy",
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "description": "Local filesystem access"
    },
    "remote-api": {
      "transport": "http",
      "base_url": "https://api.example.com/mcp",
      "headers": {"Authorization": "Bearer token"},
      "timeout": 30
    }
  }
}
```

**CLI**:
```bash
toolmux                          # Default: proxy mode
toolmux --mode meta              # Meta-tools with embedded instructions
toolmux --mode proxy             # Condensed real tools (default)
toolmux --mode gateway           # Server-grouped tools
toolmux --config ./custom.json   # Custom config path
toolmux --list-servers           # List configured servers and exit
toolmux --version                # Show version
```

---

## 4. VERIFIED FASTMCP 2.14.x API REFERENCE

All line numbers verified against `/usr/local/lib/python3.11/dist-packages/fastmcp/`.

### 4.1 Server Construction

**File**: `fastmcp/server/server.py:155-254`
```python
from fastmcp import FastMCP

mcp = FastMCP(
    name="ToolMux",              # str | None — server name
    instructions="...",           # str | None — injected into InitializeResult
    version="2.0.0",             # str | None — server version
)
```

The `instructions` parameter flows to `InitializeResult.instructions` in the MCP protocol.
MCP-compliant clients (Claude Desktop, Cursor, Cline, Claude Code) read this field and inject it
into the agent's system context automatically.

**Properties** (server.py:350-364):
```python
mcp.name          # -> str (read-only)
mcp.instructions  # -> str | None (read/write)
mcp.version       # -> str | None (read-only)
```

### 4.2 Tool Registration — Decorator

**File**: `fastmcp/server/server.py:1917-1968`
```python
@mcp.tool()
def my_tool(param1: str, param2: int = 0) -> str:
    """Tool description becomes the MCP description."""
    return "result"

# With overrides:
@mcp.tool(name="custom_name", description="Custom description")
def my_other_tool(x: str) -> str:
    return x
```

The decorator creates a `FunctionTool` from the function. Parameters are extracted from the function
signature and converted to JSON Schema automatically. The docstring becomes the description.

### 4.3 Tool Registration — Dynamic (add_tool)

**File**: `fastmcp/server/server.py:1862-1885`
```python
from fastmcp.tools.tool import FunctionTool

tool = FunctionTool.from_function(
    fn=my_function,              # Callable — the handler function
    name="tool_name",            # str | None — overrides fn.__name__
    description="Short desc",    # str | None — overrides fn.__doc__
)
mcp.add_tool(tool)  # -> Tool (returns the registered tool)
```

**For custom schemas** (not derived from a function signature), subclass `Tool` directly:
```python
from fastmcp.tools.tool import Tool, ToolResult
from mcp.types import TextContent

class CustomTool(Tool):
    async def run(self, arguments: dict) -> ToolResult:
        # arguments is the raw dict from the MCP tools/call request
        return ToolResult(content=[TextContent(type="text", text="result")])

custom = CustomTool(
    name="my_tool",
    description="My tool description",
    parameters={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
)
mcp.add_tool(custom)
```

**Key fields on Tool base class** (tool.py:123-149):
- `name: str` — tool name
- `description: str | None` — shown to agents
- `parameters: dict` — JSON Schema for inputSchema
- `output_schema: dict | None` — JSON Schema for output
- `async def run(self, arguments: dict) -> ToolResult` — abstract, must implement

### 4.4 Server Run (stdio)

**File**: `fastmcp/server/server.py:624-643`
```python
mcp.run(transport="stdio")      # Synchronous, blocks until stdin closes
mcp.run()                       # Default: stdio
```

Handles the entire JSON-RPC stdio loop — reading from stdin, dispatching MCP methods, writing
responses to stdout. **This completely replaces the manual `while True: readline()` loop.**

### 4.5 Schema Compression (built-in)

**File**: `fastmcp/utilities/json_schema.py:364-394`
```python
from fastmcp.utilities.json_schema import compress_schema

compressed = compress_schema(
    schema=full_schema,
    prune_params=["verbose_param"],    # Remove specific params
    prune_defs=True,                   # Remove unused $defs
    prune_additional_properties=True,  # Remove additionalProperties: false
    prune_titles=False,                # Remove title fields
)
```

---

## 5. COMPLETE IMPLEMENTATION — `toolmux/main.py`

This is the complete rewrite. Copy-paste ready. All placeholders are filled in.

```python
#!/usr/bin/env python3
"""
ToolMux v2.0 - Efficient MCP server aggregation with FastMCP
Supports proxy, meta, and gateway modes with smart token optimization.
"""
import json
import sys
import subprocess
import os
import argparse
import re
import threading
import concurrent.futures
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional

import httpx
from fastmcp import FastMCP
from fastmcp.tools.tool import Tool, ToolResult
from mcp.types import TextContent


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "2.0.0"

INSTRUCTIONS_META = """\
You are connected to ToolMux, an MCP tool proxy.

Available tools:
- catalog_tools: Discover all backend tools (names, servers, descriptions, parameters). Call first.
- get_tool_schema(name): Get full parameter schema for any tool before calling it.
- invoke(name, args): Execute any backend tool. Example: invoke(name="read_file", args={"path": "/tmp/x"})
- get_tool_count: Get tool count statistics by server.

Workflow: catalog_tools -> get_tool_schema -> invoke"""

INSTRUCTIONS_PROXY = """\
You are connected to ToolMux, an MCP tool proxy.

All tools listed are from backend servers. Call them directly by name.
If you need full parameter details for a tool, call get_tool_schema(name="tool_name").
On first use of each tool, additional context about the tool will be provided with the result."""

INSTRUCTIONS_GATEWAY = """\
You are connected to ToolMux, an MCP tool proxy.

Each tool represents a backend server with multiple sub-tools listed in its description.
Call format: server_name(tool="sub_tool_name", arguments={...})
Use get_tool_schema(name="sub_tool_name") for full parameter details."""


# ---------------------------------------------------------------------------
# HttpMcpClient — preserved from v1.2.1 with version bump
# ---------------------------------------------------------------------------

class HttpMcpClient:
    """HTTP/SSE MCP client for remote MCP servers."""

    def __init__(self, base_url: str, headers: Optional[Dict[str, str]] = None,
                 timeout: int = 30, sse_endpoint: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.headers = headers or {}
        self.timeout = timeout
        self.sse_endpoint = sse_endpoint or "/sse"
        self.client = httpx.Client(
            headers=self.headers,
            timeout=httpx.Timeout(timeout, connect=timeout / 2)
        )
        self._initialized = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        if hasattr(self, 'client'):
            self.client.close()

    def call_rpc(self, method: str, params: Optional[Dict[str, Any]] = None,
                 request_id: int = 1) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": request_id}
        if params:
            payload["params"] = params

        try:
            response = self.client.post(f"{self.base_url}/mcp", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                try:
                    response = self.client.post(f"{self.base_url}/rpc", json=payload)
                    response.raise_for_status()
                    return response.json()
                except Exception:
                    pass
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32603,
                              "message": f"HTTP {e.response.status_code}: {e}",
                              "data": {"transport": "http", "url": self.base_url}}}
        except httpx.TimeoutException:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32603,
                              "message": f"Request timeout after {self.timeout}s",
                              "data": {"transport": "http", "url": self.base_url}}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32603,
                              "message": f"Connection error: {e}",
                              "data": {"transport": "http", "url": self.base_url}}}

    def initialize(self) -> bool:
        if self._initialized:
            return True
        init_response = self.call_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ToolMux", "version": VERSION}
        })
        if "error" in init_response:
            return False
        self.call_rpc("notifications/initialized")
        self._initialized = True
        return True

    def get_tools(self) -> List[Dict[str, Any]]:
        if not self.initialize():
            return []
        response = self.call_rpc("tools/list")
        if "error" in response:
            return []
        return response.get("result", {}).get("tools", [])

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self.initialize():
            return {"error": "Failed to initialize HTTP MCP connection"}
        response = self.call_rpc("tools/call", {"name": tool_name, "arguments": arguments})
        if "error" in response:
            return {"error": response["error"]["message"]}
        return response.get("result", {"error": "No result returned"})


# ---------------------------------------------------------------------------
# BackendManager — manages all backend MCP server connections
# ---------------------------------------------------------------------------

class BackendManager:
    """Manages connections to backend MCP servers (stdio + HTTP) with parallel init."""

    def __init__(self, servers_config: Dict[str, Dict[str, Any]]):
        self.servers = servers_config
        self.server_processes: Dict[str, Any] = {}
        self.tool_cache: Optional[List[Dict[str, Any]]] = None
        self._described_tools: set = set()  # Track first-invocation enrichment
        self._init_complete = threading.Event()
        self._lock = threading.Lock()

    # --- Parallel initialization ---

    def initialize_all_async(self):
        """Start all backend servers in parallel threads. Non-blocking."""
        thread = threading.Thread(target=self._init_all, daemon=True)
        thread.start()

    def _init_all(self):
        """Initialize all servers in parallel using thread pool."""
        max_workers = min(len(self.servers), 10)
        if max_workers == 0:
            self._init_complete.set()
            return

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._init_server, name): name
                for name in self.servers
            }
            for future in concurrent.futures.as_completed(futures, timeout=30):
                name = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"Failed to init {name}: {e}", file=sys.stderr)

        self._init_complete.set()

    def _init_server(self, server_name: str):
        """Initialize a single server and fetch its tools."""
        server = self.start_server(server_name)
        if not server:
            return

        try:
            if isinstance(server, HttpMcpClient):
                tools = server.get_tools()
                for tool in tools:
                    tool["_server"] = server_name
                    tool["_transport"] = "http"
                with self._lock:
                    if self.tool_cache is None:
                        self.tool_cache = []
                    self.tool_cache.extend(tools)
            else:
                # stdio subprocess — initialize and fetch tools
                init_request = {
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "ToolMux", "version": VERSION}
                    }
                }
                server.stdin.write(json.dumps(init_request) + "\n")
                server.stdin.flush()
                server.stdout.readline()  # read init response

                init_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                server.stdin.write(json.dumps(init_notif) + "\n")
                server.stdin.flush()

                tools_request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
                server.stdin.write(json.dumps(tools_request) + "\n")
                server.stdin.flush()

                response_line = server.stdout.readline()
                if response_line:
                    response = json.loads(response_line)
                    if "result" in response and "tools" in response["result"]:
                        tools = response["result"]["tools"]
                        for tool in tools:
                            tool["_server"] = server_name
                            tool["_transport"] = "stdio"
                        with self._lock:
                            if self.tool_cache is None:
                                self.tool_cache = []
                            self.tool_cache.extend(tools)
        except Exception as e:
            print(f"Error getting tools from {server_name}: {e}", file=sys.stderr)

    # --- Server lifecycle ---

    def start_server(self, server_name: str):
        """Start a backend server (stdio subprocess or HTTP client)."""
        if server_name in self.server_processes:
            return self.server_processes[server_name]

        server_config = self.servers[server_name]

        if server_config.get("transport") == "http":
            try:
                client = HttpMcpClient(
                    base_url=server_config["base_url"],
                    headers=server_config.get("headers"),
                    timeout=server_config.get("timeout", 30),
                    sse_endpoint=server_config.get("sse_endpoint")
                )
                self.server_processes[server_name] = client
                return client
            except Exception as e:
                print(f"Failed to create HTTP client for {server_name}: {e}", file=sys.stderr)
                return None

        # stdio transport
        env = os.environ.copy()
        env.update(server_config.get("env", {}))

        try:
            process = subprocess.Popen(
                [server_config["command"]] + server_config.get("args", []),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
                env=env, cwd=server_config.get("cwd")
            )
            self.server_processes[server_name] = process
            return process
        except Exception as e:
            print(f"Failed to start stdio server {server_name}: {e}", file=sys.stderr)
            return None

    # --- Tool access ---

    def wait_for_tools(self, timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Block until backends are ready, return all tools."""
        self._init_complete.wait(timeout=timeout)
        return self.get_all_tools()

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """Return cached tools list."""
        if self.tool_cache is None:
            self.tool_cache = []
        return self.tool_cache

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Route a tool call to the correct backend server."""
        tools = self.get_all_tools()
        target_server = None

        for tool in tools:
            if tool["name"] == tool_name:
                target_server = tool["_server"]
                break

        if not target_server:
            return {"content": [{"type": "text", "text": f"Tool '{tool_name}' not found"}],
                    "isError": True}

        try:
            server = self.server_processes.get(target_server)
            if not server:
                return {"content": [{"type": "text",
                                     "text": f"Server '{target_server}' not available"}],
                        "isError": True}

            if isinstance(server, HttpMcpClient):
                return server.call_tool(tool_name, arguments)

            # stdio subprocess
            request = {
                "jsonrpc": "2.0", "id": 3,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments}
            }
            server.stdin.write(json.dumps(request) + "\n")
            server.stdin.flush()

            response_line = server.stdout.readline()
            if response_line:
                response = json.loads(response_line)
                return response.get("result", {"error": "No result"})

        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

        return {"content": [{"type": "text", "text": "Tool execution failed"}], "isError": True}

    # --- Cleanup ---

    def shutdown(self):
        """Terminate all backend server processes."""
        for server in self.server_processes.values():
            try:
                if isinstance(server, HttpMcpClient):
                    server.close()
                else:
                    server.terminate()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Smart description condensation
# ---------------------------------------------------------------------------

def condense_description(description: str, max_len: int = 80) -> str:
    """Intelligently condense a tool description.

    Strategy:
    1. Extract first sentence (the action statement)
    2. Remove filler phrases that don't help tool selection
    3. Never cut mid-word
    """
    if not description:
        return ""

    # Extract first sentence (split on '. ' to avoid decimals/abbreviations)
    match = re.match(r'^(.+?\.)\s', description + ' ')
    first_sentence = match.group(1) if match else description

    # Remove filler phrases
    fillers = [
        r'\s*Only works within allowed directories\.?',
        r'\s*Use this tool when you need to\s+',
        r'\s*Use this for\s+',
        r'\s*Use with caution as\s+',
    ]
    cleaned = first_sentence
    for filler in fillers:
        cleaned = re.sub(filler, '', cleaned, flags=re.IGNORECASE)

    # Trim to max_len without cutting mid-word
    if len(cleaned) <= max_len:
        return cleaned.strip().rstrip('.')

    truncated = cleaned[:max_len]
    last_space = truncated.rfind(' ')
    if last_space > max_len // 2:
        truncated = truncated[:last_space]

    return truncated.strip().rstrip('.')


# ---------------------------------------------------------------------------
# Schema condensation
# ---------------------------------------------------------------------------

def condense_schema(schema: dict) -> dict:
    """Condense inputSchema: keep property names + types, drop verbose extras.

    Keep: property names, property types, required array, array item types
    Drop: descriptions, defaults, enums, examples, additionalProperties,
          min/max constraints, nested object property descriptions
    """
    if not schema or not schema.get("properties"):
        return {"type": "object"}

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    condensed_props = {}
    for prop_name, prop_def in properties.items():
        prop_type = prop_def.get("type", "string")
        if prop_type == "array":
            items = prop_def.get("items", {})
            items_type = items.get("type", "string")
            condensed_props[prop_name] = {"type": "array", "items": {"type": items_type}}
        elif prop_type == "object":
            condensed_props[prop_name] = {"type": "object"}
        else:
            condensed_props[prop_name] = {"type": prop_type}

    result: dict = {"type": "object", "properties": condensed_props}
    if required:
        result["required"] = required
    return result


# ---------------------------------------------------------------------------
# Tool name collision handling
# ---------------------------------------------------------------------------

def resolve_collisions(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Handle duplicate tool names across servers by prefixing with server name."""
    seen: Dict[str, str] = {}  # name -> first server that claimed it

    for tool in tools:
        name = tool["name"]
        server = tool["_server"]

        if name in seen and seen[name] != server:
            for t in tools:
                if t["name"] == name and t["_server"] == seen[name]:
                    t["name"] = f"{seen[name]}_{name}"
                    break
            tool["name"] = f"{server}_{name}"
            print(f"Warning: tool name collision '{name}' — "
                  f"renamed to {seen[name]}_{name} and {server}_{name}",
                  file=sys.stderr)
        else:
            seen[name] = server

    return tools


# ---------------------------------------------------------------------------
# Invocation enrichment (progressive disclosure)
# ---------------------------------------------------------------------------

def enrich_result(tool_name: str, backend_result: dict,
                  described_tools: set, tool_cache: List[Dict[str, Any]]) -> dict:
    """Add full docstring to result on first invocation of each unique tool."""
    content = backend_result.get("content", [])

    if tool_name not in described_tools:
        described_tools.add(tool_name)
        for tool_def in tool_cache:
            if tool_def["name"] == tool_name:
                full_desc = tool_def.get("description", "")
                full_schema = tool_def.get("inputSchema", {})
                if full_desc:
                    enrichment = (
                        f"[Tool: {tool_name}]\n"
                        f"[Description: {full_desc}]\n"
                        f"[Parameters: {json.dumps(full_schema)}]"
                    )
                    content.append({"type": "text", "text": enrichment})
                break

    return {"content": content}


def enrich_error_result(tool_name: str, error_result: dict,
                        tool_cache: List[Dict[str, Any]]) -> dict:
    """On errors, always include full schema to help agent self-correct."""
    content = error_result.get("content", [])
    for tool_def in tool_cache:
        if tool_def["name"] == tool_name:
            full_schema = tool_def.get("inputSchema", {})
            content.append({
                "type": "text",
                "text": f"[Schema for {tool_name}: {json.dumps(full_schema)}]"
            })
            break
    return {"content": content}


# ---------------------------------------------------------------------------
# Mode-specific tool registration
# ---------------------------------------------------------------------------

def register_meta_tools(mcp: FastMCP, backend: BackendManager):
    """Register the 4 meta-tools for meta mode."""

    @mcp.tool()
    def catalog_tools() -> str:
        """Discover all available backend tools with descriptions and parameter summaries."""
        tools = backend.get_all_tools()
        catalog = []
        for tool in tools:
            schema = tool.get("inputSchema", {})
            required = schema.get("required", [])
            properties = schema.get("properties", {})

            param_hints = []
            for prop_name, prop_def in properties.items():
                prop_type = prop_def.get("type", "?")
                req_marker = ", required" if prop_name in required else ""
                param_hints.append(f"{prop_name}({prop_type}{req_marker})")

            catalog.append({
                "name": tool["name"],
                "server": tool["_server"],
                "description": condense_description(tool.get("description", "")),
                "parameters": ", ".join(param_hints) if param_hints else "none",
            })
        return json.dumps(catalog, indent=2)

    @mcp.tool()
    def get_tool_schema(name: str) -> str:
        """Get full parameter schema and description for any backend tool."""
        tools = backend.get_all_tools()
        for tool in tools:
            if tool["name"] == name:
                return json.dumps({
                    "name": name,
                    "server": tool["_server"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("inputSchema", {}),
                }, indent=2)
        return f"Tool '{name}' not found. Use catalog_tools to see available tools."

    @mcp.tool()
    def invoke(name: str, args: Optional[dict] = None) -> str:
        """Execute any backend tool by name with arguments."""
        result = backend.call_tool(name, args or {})
        is_error = result.get("isError", False)
        if is_error:
            enriched = enrich_error_result(name, result, backend.get_all_tools())
        else:
            enriched = enrich_result(
                name, result, backend._described_tools, backend.get_all_tools()
            )
        return json.dumps(enriched, indent=2)

    @mcp.tool()
    def get_tool_count() -> str:
        """Get count of available tools grouped by server."""
        tools = backend.get_all_tools()
        servers: Dict[str, int] = {}
        for tool in tools:
            s = tool["_server"]
            servers[s] = servers.get(s, 0) + 1
        return json.dumps({"total_tools": len(tools), "by_server": servers}, indent=2)


def register_proxy_tools(mcp: FastMCP, backend: BackendManager):
    """Register all backend tools as condensed real tools for proxy mode."""
    tools = backend.wait_for_tools()
    tools = resolve_collisions(tools)

    for tool_def in tools:
        tool_name = tool_def["name"]
        condensed_desc = condense_description(tool_def.get("description", ""))
        condensed_input = condense_schema(tool_def.get("inputSchema", {}))

        # Use a factory to capture tool_name in the closure correctly
        def make_proxy_tool(tn, desc, params):
            class _ProxyTool(Tool):
                async def run(self, arguments: dict) -> ToolResult:
                    result = backend.call_tool(tn, arguments)
                    is_error = result.get("isError", False)
                    if is_error:
                        enriched = enrich_error_result(tn, result, backend.get_all_tools())
                    else:
                        enriched = enrich_result(
                            tn, result, backend._described_tools, backend.get_all_tools()
                        )
                    text = json.dumps(enriched, indent=2)
                    return ToolResult(content=[TextContent(type="text", text=text)])

            return _ProxyTool(name=tn, description=desc, parameters=params)

        mcp.add_tool(make_proxy_tool(tool_name, condensed_desc, condensed_input))

    # Also register get_tool_schema as a helper
    @mcp.tool()
    def get_tool_schema(name: str) -> str:
        """Get full parameter details and description for any tool."""
        all_tools = backend.get_all_tools()
        for tool in all_tools:
            if tool["name"] == name:
                return json.dumps({
                    "name": name,
                    "server": tool["_server"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("inputSchema", {}),
                }, indent=2)
        return f"Tool '{name}' not found."


def register_gateway_tools(mcp: FastMCP, backend: BackendManager):
    """Register one tool per backend server with sub-tool listing for gateway mode."""
    tools = backend.wait_for_tools()

    # Group by server
    servers: Dict[str, List[Dict[str, Any]]] = {}
    for tool in tools:
        server = tool["_server"]
        servers.setdefault(server, []).append(tool)

    for server_name, server_tools in servers.items():
        tool_names = [t["name"] for t in server_tools]
        desc = f"Tools: {', '.join(tool_names)}"

        def make_gateway_tool(sn, names, description):
            class _GatewayTool(Tool):
                async def run(self, arguments: dict) -> ToolResult:
                    sub_tool = arguments.get("tool", "")
                    sub_args = arguments.get("arguments", {})
                    if not sub_tool:
                        return ToolResult(content=[TextContent(
                            type="text",
                            text=f"Missing 'tool' argument. Available: {', '.join(names)}"
                        )])
                    result = backend.call_tool(sub_tool, sub_args)
                    is_error = result.get("isError", False)
                    if is_error:
                        enriched = enrich_error_result(
                            sub_tool, result, backend.get_all_tools()
                        )
                    else:
                        enriched = enrich_result(
                            sub_tool, result, backend._described_tools, backend.get_all_tools()
                        )
                    text = json.dumps(enriched, indent=2)
                    return ToolResult(content=[TextContent(type="text", text=text)])

            return _GatewayTool(
                name=sn,
                description=description,
                parameters={
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string",
                                 "description": f"One of: {', '.join(names)}"},
                        "arguments": {"type": "object",
                                      "description": "Arguments for the sub-tool"},
                    },
                    "required": ["tool"],
                },
            )

        mcp.add_tool(make_gateway_tool(server_name, tool_names, desc))

    # Also register get_tool_schema helper
    @mcp.tool()
    def get_tool_schema(name: str) -> str:
        """Get full parameter details and description for any tool."""
        all_tools = backend.get_all_tools()
        for tool in all_tools:
            if tool["name"] == name:
                return json.dumps({
                    "name": name,
                    "server": tool["_server"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("inputSchema", {}),
                }, indent=2)
        return f"Tool '{name}' not found."


# ---------------------------------------------------------------------------
# Configuration loading (preserved from v1, extended for mode field)
# ---------------------------------------------------------------------------

def setup_first_run():
    """Set up configuration directory and example config on first run."""
    config_dir = Path.home() / "toolmux"
    config_file = config_dir / "mcp.json"
    examples_dir = config_dir / "examples"

    if config_file.exists():
        return config_file

    print(f"ToolMux v{VERSION} - First run detected")
    config_dir.mkdir(exist_ok=True)
    print(f"Created configuration directory: {config_dir}")

    examples_dir.mkdir(exist_ok=True)

    try:
        package_dir = Path(__file__).parent
        package_examples = package_dir / "examples"
        if package_examples.exists():
            for example_file in package_examples.glob("*.json"):
                shutil.copy2(example_file, examples_dir / example_file.name)
            print(f"Installed example configurations: {examples_dir}")
        else:
            create_basic_examples(examples_dir)
            print(f"Created basic example configurations: {examples_dir}")

        package_prompt = package_dir / "Prompt"
        user_prompt = config_dir / "Prompt"
        if package_prompt.exists():
            shutil.copytree(package_prompt, user_prompt, dirs_exist_ok=True)
            print(f"Installed agent instructions: {user_prompt}")

        package_scripts = package_dir / "scripts"
        user_scripts = config_dir / "scripts"
        if package_scripts.exists():
            shutil.copytree(package_scripts, user_scripts, dirs_exist_ok=True)
            print(f"Installed scripts: {user_scripts}")
    except Exception as e:
        create_basic_examples(examples_dir)
        print(f"Could not copy package resources: {e}", file=sys.stderr)
        print(f"Created basic example configurations: {examples_dir}")

    default_config = {
        "servers": {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", str(Path.home())],
                "description": "Local filesystem access - read, write, and manage files"
            }
        }
    }

    with open(config_file, 'w') as f:
        json.dump(default_config, f, indent=2)

    print(f"Installed default configuration: {config_file}")
    print(f"\nEdit ~/toolmux/mcp.json to add your MCP servers")
    print(f"See ~/toolmux/examples/ for configuration templates")
    print(f"Run 'toolmux' again to start with your configured servers\n")

    return config_file


def create_basic_examples(examples_dir: Path):
    """Create basic example configurations."""
    examples = {
        "filesystem.json": {
            "servers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
                    "description": "Local filesystem access"
                }
            }
        },
        "brave-search.json": {
            "servers": {
                "brave-search": {
                    "command": "uvx",
                    "args": ["mcp-server-brave-search"],
                    "env": {"BRAVE_API_KEY": "your-brave-api-key-here"},
                    "description": "Web search using Brave Search API"
                }
            }
        },
        "mixed-servers.json": {
            "servers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
                    "description": "Local filesystem access via stdio"
                },
                "remote-api": {
                    "transport": "http",
                    "base_url": "https://api.example.com/mcp",
                    "headers": {"Authorization": "Bearer your-token-here"},
                    "timeout": 30,
                    "description": "Remote HTTP MCP server"
                }
            }
        }
    }
    for filename, config in examples.items():
        with open(examples_dir / filename, 'w') as f:
            json.dump(config, f, indent=2)


def find_config_file(config_path: Optional[str] = None) -> Path:
    """Find configuration file using discovery order."""
    if config_path:
        config_file = Path(config_path)
        if not config_file.exists():
            print(f"Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        return config_file

    search_paths = [
        Path.cwd() / "mcp.json",
        Path.home() / "toolmux" / "mcp.json",
    ]
    for path in search_paths:
        if path.exists():
            return path

    return setup_first_run()


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load full configuration from mcp.json (returns the entire config dict)."""
    config_file = find_config_file(config_path)
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in config file: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading config file: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ToolMux - MCP proxy/gateway with smart token optimization",
        epilog="For more information, visit: https://github.com/subnetangel/ToolMux"
    )
    parser.add_argument("--config", help="Path to MCP configuration file (default: auto-discover)")
    parser.add_argument("--version", action="version", version=f"ToolMux {VERSION}")
    parser.add_argument(
        "--mode", choices=["proxy", "meta", "gateway"], default=None,
        help="Operating mode (default: proxy, or from config)"
    )
    parser.add_argument("--list-servers", action="store_true",
                        help="List configured servers and exit")

    args = parser.parse_args()

    # Load config
    config = load_config(args.config)
    servers = config.get("servers", {})

    # Determine mode: CLI flag > config file > default
    mode = args.mode or config.get("mode", "proxy")

    # Handle list-servers command
    if args.list_servers:
        print(f"Configured MCP servers (mode: {mode}):")
        for name, srv_config in servers.items():
            transport = srv_config.get("transport", "stdio")
            if transport == "http":
                endpoint = srv_config.get("base_url", "unknown")
            else:
                cmd = srv_config.get("command", "unknown")
                srv_args = " ".join(srv_config.get("args", []))
                endpoint = f"{cmd} {srv_args}"
            print(f"  {name}: {transport} - {endpoint}")
        return

    if not servers:
        print("No servers configured. Edit your mcp.json file to add MCP servers.",
              file=sys.stderr)
        sys.exit(1)

    # Create backend manager
    backend = BackendManager(servers)

    # Create FastMCP server with mode-appropriate instructions
    instructions = {
        "meta": INSTRUCTIONS_META,
        "proxy": INSTRUCTIONS_PROXY,
        "gateway": INSTRUCTIONS_GATEWAY,
    }
    mcp = FastMCP(
        name="ToolMux",
        instructions=instructions[mode],
        version=VERSION,
    )

    # Start backend initialization in background
    backend.initialize_all_async()

    # Register tools based on mode
    if mode == "meta":
        register_meta_tools(mcp, backend)
    elif mode == "proxy":
        register_proxy_tools(mcp, backend)
    elif mode == "gateway":
        register_gateway_tools(mcp, backend)

    # Run the server (FastMCP handles the stdio JSON-RPC loop)
    try:
        mcp.run(transport="stdio")
    finally:
        backend.shutdown()


if __name__ == "__main__":
    main()
```

---

## 6. FILE CHANGES — `toolmux/__init__.py`

```python
"""
ToolMux - Efficient MCP server aggregation with smart token optimization
Supports proxy, meta, and gateway modes via FastMCP
"""

from .main import main, BackendManager, HttpMcpClient

__version__ = "2.0.0"
__all__ = ["main", "BackendManager", "HttpMcpClient"]
```

---

## 7. VERSION SYNC

When updating the version, ALL of these locations must match:

| File | Location | Current | Target |
|------|----------|---------|--------|
| `pyproject.toml` | line 7: `version = "..."` | `1.2.1` | `2.0.0` |
| `toolmux/__init__.py` | `__version__ = "..."` | `1.2.1` | `2.0.0` |
| `toolmux/main.py` | `VERSION = "..."` constant | `1.2.1` (scattered) | `2.0.0` (single const) |

---

## 8. CONFIGURATION FORMAT

### New mcp.json format (backwards compatible)
```json
{
  "mode": "proxy",
  "servers": {
    "server-name": {
      "command": "npx",
      "args": ["-y", "..."],
      "env": {},
      "cwd": "/path",
      "description": "Human description"
    },
    "http-server": {
      "transport": "http",
      "base_url": "https://...",
      "headers": {},
      "timeout": 30,
      "description": "Remote server"
    }
  }
}
```

The `"mode"` field is new and optional. Old configs without it default to `"proxy"`.
The `"servers"` field format is unchanged — full backwards compatibility.

---

## 9. DEPENDENCIES

### pyproject.toml dependencies (ALREADY UPDATED):
```toml
dependencies = [
    "fastmcp>=2.14.0,<3",
    "mcp>=1.20.0",
    "click>=8.0.0",
    "pydantic>=2.6.0",
    "httpx>=0.24.0",
    "websockets>=11.0.0",
    "python-dotenv>=1.0.1",
]
```

### requirements.txt (ALREADY UPDATED):
```
fastmcp>=2.14.0,<3
mcp>=1.20.0
click>=8.0.0
pydantic>=2.6.0
httpx>=0.24.0
websockets>=11.0.0
python-dotenv>=1.0.1
```

### Why Pin `<3`

FastMCP 3.0 (currently RC2, Feb 2026) introduces breaking changes including the provider/transform
architecture redesign. Key incompatibilities:
- `FastMCPProxy` is replaced by `ProxyProvider`
- Constructor kwargs like `ui=` changed to `app=` with `AppConfig`
- 16 `FastMCP()` constructor kwargs removed

We should adopt 3.0 features in a separate major version (ToolMux 3.0) after FastMCP 3.0 reaches
stable release. See section 15.

---

## 10. TESTING — COMPLETE TEST IMPLEMENTATIONS

### 10.1 New test: `tests/test_v2_unit.py`

```python
#!/usr/bin/env python3
"""Unit tests for ToolMux v2 — pure function tests, no subprocess needed."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from toolmux.main import (
    BackendManager, condense_description, condense_schema,
    resolve_collisions, enrich_result, enrich_error_result, VERSION
)


class TestVersion:
    def test_version_is_2(self):
        assert VERSION == "2.0.0"


class TestCondenseDescription:
    def test_first_sentence(self):
        desc = "Read the complete contents of a file from the file system. Handles various encodings."
        result = condense_description(desc)
        assert result == "Read the complete contents of a file from the file system"

    def test_filler_removal(self):
        desc = "Use this tool when you need to search for files. Only works within allowed directories."
        result = condense_description(desc)
        assert "Use this tool when you need to" not in result
        assert "Only works within allowed directories" not in result

    def test_no_mid_word_cut(self):
        desc = "This is a really long description that goes on and on and on and on and should be truncated nicely"
        result = condense_description(desc, max_len=40)
        assert len(result) <= 40
        assert not result.endswith(' ')

    def test_empty(self):
        assert condense_description("") == ""

    def test_short_passthrough(self):
        assert condense_description("Short desc") == "Short desc"


class TestCondenseSchema:
    def test_basic(self):
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path"},
                "encoding": {"type": "string", "description": "Text encoding", "default": "utf-8"},
            },
            "required": ["path"],
            "additionalProperties": False,
        }
        result = condense_schema(schema)
        assert result["properties"]["path"] == {"type": "string"}
        assert result["properties"]["encoding"] == {"type": "string"}
        assert result["required"] == ["path"]
        assert "additionalProperties" not in result
        assert "description" not in json.dumps(result)

    def test_empty(self):
        assert condense_schema({}) == {"type": "object"}
        assert condense_schema({"type": "object"}) == {"type": "object"}

    def test_arrays(self):
        schema = {
            "type": "object",
            "properties": {
                "edits": {"type": "array", "items": {"type": "object",
                          "properties": {"old": {"type": "string"}, "new": {"type": "string"}}}},
            },
            "required": ["edits"],
        }
        result = condense_schema(schema)
        assert result["properties"]["edits"] == {"type": "array", "items": {"type": "object"}}

    def test_preserves_required(self):
        schema = {
            "type": "object",
            "properties": {"x": {"type": "string"}, "y": {"type": "integer"}},
            "required": ["x", "y"],
        }
        result = condense_schema(schema)
        assert result["required"] == ["x", "y"]


class TestResolveCollisions:
    def test_no_collision(self):
        tools = [
            {"name": "read_file", "_server": "fs"},
            {"name": "search", "_server": "brave"},
        ]
        result = resolve_collisions(tools)
        assert result[0]["name"] == "read_file"
        assert result[1]["name"] == "search"

    def test_with_collision(self):
        tools = [
            {"name": "search", "_server": "fs"},
            {"name": "search", "_server": "brave"},
        ]
        result = resolve_collisions(tools)
        names = {t["name"] for t in result}
        assert "fs_search" in names
        assert "brave_search" in names
        assert "search" not in names


class TestEnrichment:
    def test_first_invocation_includes_docstring(self):
        described = set()
        tool_cache = [
            {"name": "read_file", "description": "Read file contents",
             "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}}
        ]
        result = {"content": [{"type": "text", "text": "file contents here"}]}

        enriched = enrich_result("read_file", result, described, tool_cache)
        texts = [c["text"] for c in enriched["content"]]
        combined = "\n".join(texts)
        assert "[Tool: read_file]" in combined
        assert "[Description: Read file contents]" in combined
        assert "read_file" in described

    def test_second_invocation_no_docstring(self):
        described = {"read_file"}
        tool_cache = [
            {"name": "read_file", "description": "Read file contents",
             "inputSchema": {"type": "object"}}
        ]
        result = {"content": [{"type": "text", "text": "file contents here"}]}

        enriched = enrich_result("read_file", result, described, tool_cache)
        assert len(enriched["content"]) == 1

    def test_error_includes_schema(self):
        tool_cache = [
            {"name": "read_file", "description": "Read file contents",
             "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
                             "required": ["path"]}}
        ]
        error_result = {"content": [{"type": "text", "text": "Missing required param: path"}],
                        "isError": True}

        enriched = enrich_error_result("read_file", error_result, tool_cache)
        texts = [c["text"] for c in enriched["content"]]
        combined = "\n".join(texts)
        assert "[Schema for read_file:" in combined
        assert '"path"' in combined


class TestBackendManager:
    def test_init_empty(self):
        bm = BackendManager({})
        assert bm.get_all_tools() == []

    def test_described_tools_tracking(self):
        bm = BackendManager({})
        assert len(bm._described_tools) == 0
```

### 10.2 Update `tests/test_mcp_protocol.py` — verify instructions field

```python
#!/usr/bin/env python3
"""Test ToolMux MCP protocol compliance with FastMCP — subprocess-based."""
import json
import subprocess
import sys
import threading
from queue import Queue, Empty


def test_mcp_protocol():
    """Test ToolMux MCP protocol compliance in meta mode via subprocess."""
    process = subprocess.Popen(
        [sys.executable, "-m", "toolmux.main", "--mode", "meta"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=0
    )

    output_queue: Queue = Queue()

    def read_output(pipe, queue):
        try:
            for line in iter(pipe.readline, ''):
                if line.strip():
                    queue.put(line.strip())
        except Exception:
            pass

    output_thread = threading.Thread(target=read_output, args=(process.stdout, output_queue))
    output_thread.daemon = True
    output_thread.start()

    def send_request(request):
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        try:
            response_str = output_queue.get(timeout=10)
            return json.loads(response_str)
        except (Empty, json.JSONDecodeError):
            return None

    try:
        # 1. Initialize — must have instructions field
        init_resp = send_request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestClient", "version": "1.0.0"}
            }
        })
        assert init_resp is not None, "No response to initialize"
        assert init_resp["result"]["protocolVersion"] == "2024-11-05"
        assert init_resp["result"]["serverInfo"]["name"] == "ToolMux"
        assert "instructions" in init_resp["result"], "Missing instructions field"
        assert len(init_resp["result"]["instructions"]) > 0, "Empty instructions"
        assert "catalog_tools" in init_resp["result"]["instructions"]

        # 2. Initialized notification
        send_request({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 3. List tools — must have 4 meta-tools
        list_resp = send_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert list_resp is not None, "No response to tools/list"
        tools = list_resp["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        assert "catalog_tools" in tool_names
        assert "get_tool_schema" in tool_names
        assert "invoke" in tool_names
        assert "get_tool_count" in tool_names

    finally:
        process.terminate()
        process.wait()
```

---

## 11. FILES TO MODIFY — COMPLETE CHECKLIST

| # | File | Action | What to Do |
|---|------|--------|------------|
| 1 | `toolmux/main.py` | **REWRITE** | Replace entire file with Section 5 code |
| 2 | `toolmux/__init__.py` | **UPDATE** | Replace with Section 6 code |
| 3 | `pyproject.toml` | **UPDATE** | Change `version = "1.2.1"` to `version = "2.0.0"` |
| 4 | `tests/test_v2_unit.py` | **CREATE** | New file with Section 10.1 code |
| 5 | `tests/test_mcp_protocol.py` | **REWRITE** | Replace with Section 10.2 code |
| 6 | `tests/test_simple.py` | **KEEP** | Preserved as legacy reference (may need path updates) |
| 7 | `tests/test_http_mcp.py` | **UPDATE** | Change `from toolmux.main import ToolMux, HttpMcpClient` to `from toolmux.main import BackendManager, HttpMcpClient`. Replace `ToolMux` class references with `BackendManager`. |
| 8 | `toolmux/Prompt/AGENT_INSTRUCTIONS.md` | **KEEP** | Preserved for documentation. Now superseded by MCP `instructions` field. |
| 9 | `mcp.json` | **KEEP** | Backwards compatible — no changes needed |
| 10 | `requirements.txt` | **DONE** | Already updated to `fastmcp>=2.14.0,<3` |
| 11 | `CLAUDE.md` | **DONE** | Already updated dependencies section |

---

## 12. IMPLEMENTATION ORDER — STEP BY STEP

Each step has explicit acceptance criteria. Complete one phase before moving to the next.

### Phase 1: FastMCP Foundation + Meta Mode
**Goal**: Replace hand-rolled JSON-RPC with FastMCP. Meta mode works with `instructions` field.

**Steps**:
1. Replace `toolmux/main.py` with the complete code from Section 5
2. Replace `toolmux/__init__.py` with Section 6 code
3. Update `pyproject.toml` version to `2.0.0`

**Acceptance criteria**:
- [ ] `python -m toolmux.main --version` prints `ToolMux 2.0.0`
- [ ] `python -m toolmux.main --list-servers` shows configured servers
- [ ] Server starts in meta mode via stdin/stdout without errors
- [ ] Initialize response contains `instructions` field with meta-mode text
- [ ] `tools/list` returns exactly 4 tools: catalog_tools, get_tool_schema, invoke, get_tool_count
- [ ] Each tool has proper `inputSchema` with type/properties/required

### Phase 2: Unit Tests Pass
**Goal**: All unit tests pass.

**Steps**:
1. Create `tests/test_v2_unit.py` from Section 10.1 code
2. Replace `tests/test_mcp_protocol.py` with Section 10.2 code
3. Update `tests/test_http_mcp.py` imports (ToolMux -> BackendManager)
4. Run: `python -m pytest tests/test_v2_unit.py -v`

**Acceptance criteria**:
- [ ] All `TestCondenseDescription` tests pass (5 tests)
- [ ] All `TestCondenseSchema` tests pass (4 tests)
- [ ] All `TestResolveCollisions` tests pass (2 tests)
- [ ] All `TestEnrichment` tests pass (3 tests)
- [ ] All `TestBackendManager` tests pass (2 tests)
- [ ] `TestVersion` passes
- [ ] Total: 17 unit tests pass

### Phase 3: MCP Protocol Tests Pass
**Goal**: Protocol compliance verified via subprocess.

**Steps**:
1. Run: `python -m pytest tests/test_mcp_protocol.py -v`

**Acceptance criteria**:
- [ ] Initialize response has `protocolVersion`, `serverInfo`, and `instructions`
- [ ] `instructions` field contains "catalog_tools" text
- [ ] `tools/list` returns 4 meta-tools in meta mode
- [ ] Subprocess starts cleanly and responds to JSON-RPC

### Phase 4: Proxy Mode Verification
**Goal**: Backend tools appear directly in `tools/list` with condensed schemas.

**Steps**:
1. Configure `mcp.json` with a real backend server
2. Run: `python -m toolmux.main --mode proxy`
3. Send `tools/list` and verify backend tools appear with condensed schemas
4. Call a backend tool directly by name

**Acceptance criteria**:
- [ ] `tools/list` returns backend tool names (not meta-tools) plus `get_tool_schema`
- [ ] Each tool has condensed `inputSchema` (types only, no descriptions)
- [ ] Calling a backend tool by name routes correctly and returns results
- [ ] First invocation includes full docstring enrichment
- [ ] Second invocation of same tool does NOT include docstring

### Phase 5: Gateway Mode Verification
**Goal**: Tools are grouped by server.

**Steps**:
1. Run: `python -m toolmux.main --mode gateway`
2. Send `tools/list` and verify one tool per backend server

**Acceptance criteria**:
- [ ] `tools/list` returns one tool per configured server plus `get_tool_schema`
- [ ] Each tool's description lists its sub-tools
- [ ] `server_name(tool="sub_tool", arguments={...})` routes correctly

### Phase 6: HTTP Transport Tests
**Goal**: HTTP backend servers work with the new architecture.

**Steps**:
1. Update `tests/test_http_mcp.py` to use `BackendManager` instead of `ToolMux`
2. Run: `python -m pytest tests/test_http_mcp.py tests/test_http_transport.py -v`

**Acceptance criteria**:
- [ ] HttpMcpClient initialization tests pass
- [ ] Mixed transport detection tests pass
- [ ] HTTP config validation tests pass

---

## 13. KEY REFERENCES

### FastMCP API (installed at `/usr/local/lib/python3.11/dist-packages/fastmcp/`)
- **Server constructor**: `FastMCP(name, instructions, version)` → `server/server.py:155`
- **instructions property**: `server/server.py:354-360` — getter/setter
- **add_tool()**: `server/server.py:1862` — register a Tool at runtime
- **remove_tool()**: `server/server.py:1887` — auto-sends list_changed notification
- **tool() decorator**: `server/server.py:1917-1968` — decorator with overloads
- **run()**: `server/server.py:624-643` — `mcp.run(transport="stdio")`
- **Tool base class**: `tools/tool.py:123` — `name`, `description`, `parameters`, `run()`
- **FunctionTool.from_function()**: `tools/tool.py:304-375` — create from callable
- **ToolResult**: `tools/tool.py:74-100` — `content`, `structured_content`, `meta`
- **compress_schema()**: `utilities/json_schema.py:364-394`

### MCP Protocol (installed at `/usr/local/lib/python3.11/dist-packages/mcp/`)
- **InitializeResult with instructions**: `mcp/types.py`
- **TextContent**: `mcp/types.py` — `TextContent(type="text", text="...")`

### Token Analysis (benchmarks)
- `tests/test_token_analysis.py` — 6 approaches compared at scale
- `tests/test_token_analysis_v2.py` — smart condensation + progressive disclosure
- `docs/SMART_PROXY_PLAN.md` — design exploration and trade-off analysis

---

## 14. SUCCESS CRITERIA

1. **Meta mode**: Agent uses ToolMux correctly WITHOUT any AGENT_INSTRUCTIONS.md in context
2. **Proxy mode**: Agent calls backend tools by their real names like any normal MCP server
3. **Gateway mode**: Agent discovers and calls grouped tools naturally
4. **All modes**: First invocation of each tool includes full docstring in result
5. **All modes**: Error results include full schema for self-correction
6. **Backwards compatible**: Old mcp.json configs work without changes
7. **Unit tests**: 17+ tests pass via `pytest tests/test_v2_unit.py`
8. **Protocol tests**: MCP compliance via subprocess passes
9. **Token efficiency**: Meta 93-99%, Proxy 55-75%, Gateway 87-92%
10. **instructions field**: Present in InitializeResult for all modes

---

## 15. FASTMCP 3.0 MIGRATION ROADMAP

FastMCP 3.0 (currently 3.0.0rc2, Feb 2026) introduces a provider/transform architecture that aligns
closely with ToolMux's goals. When 3.0 reaches stable, ToolMux should adopt it as v3.0.

### FastMCP 2.14.x Features Used by ToolMux v2 (Current)

| Feature | ToolMux Usage |
|---------|---------------|
| `FastMCP(name, instructions, version)` | Server with embedded agent instructions |
| `@mcp.tool()` decorator | Meta-tool registration (catalog_tools, invoke, etc.) |
| `server.run(transport="stdio")` | Replaces manual stdin/stdout JSON-RPC loop |
| `Tool` base class + `add_tool()` | Dynamic tool registration for proxy/gateway modes |
| `ToolResult` + `TextContent` | Structured result returns |

### FastMCP 3.0 Features for ToolMux v3 (Future)

| 3.0 Feature | ToolMux Benefit |
|-------------|----------------|
| **ProxyProvider** | Replaces manual backend management |
| **TransformingProvider** | Apply schema condensation as middleware |
| **FileSystemProvider** | Auto-discover backend configs from directory |
| **Component versioning** | Evolve tool APIs across versions |
| **`tool_concurrency`** | Concurrent execution across backends |
| **Session-scoped state** | Per-client progressive disclosure tracking |
| **Background tasks (Docket)** | Long-running backend operations |
| **OpenTelemetry tracing** | Distributed tracing across backends |

### Migration Steps (ToolMux v2 → v3)

1. Wait for FastMCP 3.0 stable release (not RC)
2. Update dependency: `fastmcp>=3.0.0,<4`
3. Replace manual backend management with `ProxyProvider`
4. Replace schema condensation with `TransformingProvider` middleware
5. Replace `_described_tools` set with session-scoped state
6. Add `tool_concurrency` for parallel backend execution
7. Update tests for new provider API
8. Bump ToolMux to v3.0.0
