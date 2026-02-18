# ToolMux v2.0 - FastMCP Rewrite Specification

## Document Purpose
This is a complete implementation spec for rewriting ToolMux to use FastMCP as its foundation. It covers the current state, what's wrong, what to build, and exactly how each piece works. This spec is self-contained - everything needed to implement is here.

---

## 1. PROJECT CONTEXT

### What ToolMux Is
ToolMux is an MCP (Model Context Protocol) server that acts as a **proxy/gateway** for multiple backend MCP servers. Instead of an agent connecting to 10 MCP servers individually (loading hundreds of tool schemas), it connects to one ToolMux instance that aggregates everything.

- **Repository**: `/home/user/ToolMux/`
- **Current Version**: 1.2.1
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
│   ├── test_simple.py       # Basic functionality
│   ├── test_mcp_protocol.py # MCP protocol compliance
│   ├── test_e2e.py          # End-to-end integration
│   ├── test_token_analysis.py     # Token comparison (v1)
│   └── test_token_analysis_v2.py  # Token comparison (v2, progressive disclosure)
├── docs/
│   └── SMART_PROXY_PLAN.md  # Previous design exploration
├── pyproject.toml
├── requirements.txt
├── mcp.json                 # Default server config
└── CLAUDE.md                # Project conventions
```

### Key Convention
**Single-module design**: All core logic lives in `toolmux/main.py`. Do NOT split into sub-modules without strong justification. The rewrite should maintain this pattern - one main file.

---

## 2. CURRENT STATE (What Exists Today)

### Architecture
The current implementation is **hand-rolled JSON-RPC over stdio**. It does NOT use FastMCP despite listing it as a dependency. The entire server is a manual stdin/stdout JSON-RPC loop.

### Current Classes in `toolmux/main.py`

**`HttpMcpClient`** (lines 19-145): HTTP/SSE client for remote MCP servers.
- Makes JSON-RPC POST requests to `/mcp` (fallback `/rpc`)
- Handles initialize handshake, tools/list, tools/call
- Manages auth headers, timeouts

**`ToolMux`** (lines 147-478): Core multiplexer.
- `__init__(servers_config)` - takes parsed mcp.json servers dict
- `start_server(name)` - spawns stdio subprocess OR creates HttpMcpClient
- `get_all_tools()` - iterates all servers, initializes each, fetches tools/list, caches result. Injects `_server` and `_transport` metadata keys into each tool dict.
- `call_tool(name, arguments)` - looks up tool in cache, routes to correct backend
- `handle_request(request)` - processes JSON-RPC: initialize, tools/list, tools/call
- `run()` - stdin readline loop, parses JSON, dispatches to handle_request

### Current tools/list Response (The Problem)
Returns exactly 4 hardcoded meta-tools:
```json
{
  "tools": [
    {"name": "catalog_tools", "description": "List all available tools from backend MCP servers", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_tool_schema", "description": "Get schema for a specific tool", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "invoke", "description": "Execute a backend tool", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "args": {"type": "object"}}, "required": ["name"]}},
    {"name": "get_tool_count", "description": "Get count of available tools by server", "inputSchema": {"type": "object", "properties": {}}}
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
**No `instructions` field.** This is why agents don't know how to use the meta-tools without an external AGENT_INSTRUCTIONS.md file injected into context.

### What's Wrong (Problems to Solve)

1. **FastMCP is a dependency but never imported or used.** The entire server is manually coded JSON-RPC. This means no protocol compliance guarantees, no transport abstraction, no built-in features.

2. **Agents can't use the meta-tools without external instructions.** When an agent sees `invoke`, `catalog_tools`, etc., it has no idea what backend tools exist or what workflow to follow. It requires the `AGENT_INSTRUCTIONS.md` content injected into the system prompt separately.

3. **No `instructions` field in initialize response.** The MCP protocol (2024-11-05+) supports an `instructions` field that clients automatically inject into agent context. ToolMux doesn't send it.

4. **Dumb description truncation.** `catalog_tools` truncates descriptions at 80 chars (`desc[:80]`), which can cut mid-word and lose meaning.

5. **Full docstrings lost after discovery.** The full tool descriptions are cached internally but never provided to the agent at invocation time. The agent only gets truncated summaries at catalog time and raw results at invoke time.

6. **No schema optimization.** When `get_tool_schema` returns a schema, it's the raw full schema. When tools are condensed for display, no intelligent schema reduction happens.

7. **Lazy loading blocks on first tool call.** Backend servers aren't started until `catalog_tools` or another meta-tool triggers `get_all_tools()`. All servers initialize sequentially (not in parallel).

---

## 3. TARGET STATE (What To Build)

### Core Principle
Rewrite `toolmux/main.py` to use **FastMCP** as the server framework. This gives us proper MCP protocol handling, the `instructions` field, dynamic tool registration, `notifications/tools/list_changed`, and clean transport management - all for free.

### Three Operating Modes

The server supports three modes, selectable via `--mode` CLI flag or `"mode"` field in mcp.json:

#### Mode 1: `meta` (current behavior, improved)
- **tools/list**: Returns the 4 meta-tools (catalog_tools, get_tool_schema, invoke, get_tool_count)
- **NEW**: The `instructions` field in the initialize response contains the full agent workflow guide (replaces AGENT_INSTRUCTIONS.md)
- **NEW**: `catalog_tools` uses smart description condensation (not dumb truncation)
- **NEW**: First invocation of each tool via `invoke` includes the full docstring in the result
- **Token savings**: 93-99%
- **Agent UX**: Self-documenting via `instructions` field - no external file needed

#### Mode 2: `proxy` (NEW - default mode)
- **tools/list**: Returns ALL backend tools with condensed schemas + `get_tool_schema` as a helper
- Agent calls tools **directly by their real names** (e.g., `read_file`, not `invoke`)
- ToolMux transparently routes to the correct backend
- Full docstring included in result on first invocation of each unique tool
- Full schema included in result on invocation errors
- **Token savings**: 55-75% (varies by tool complexity and count)
- **Agent UX**: Fully transparent - identical to connecting to the backend directly

#### Mode 3: `gateway` (NEW)
- **tools/list**: Tools grouped by server (one MCP tool per backend server)
- Each server-tool lists sub-tools in its description
- Calling pattern: `filesystem(tool="read_file", arguments={"path": "/tmp/x"})`
- **Token savings**: 87-92%
- **Agent UX**: Near-transparent, one level of indirection

### Configuration Format

**mcp.json** (extended):
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

## 4. IMPLEMENTATION SPEC

### 4.1 FastMCP Server Foundation

Replace the hand-rolled JSON-RPC loop with FastMCP. The server initialization:

```python
from fastmcp import FastMCP

# The instructions text replaces AGENT_INSTRUCTIONS.md entirely
# MCP clients inject this into agent context automatically
INSTRUCTIONS_META = """You are connected to ToolMux, an MCP tool proxy.

Available tools:
- catalog_tools: Discover all backend tools (names, descriptions, parameters). Call this first.
- get_tool_schema(name): Get full parameter schema for any tool before calling it.
- invoke(name, args): Execute any backend tool. Example: invoke(name="read_file", args={"path": "/tmp/x"})
- get_tool_count: Get tool count statistics by server.

Workflow: catalog_tools -> get_tool_schema -> invoke"""

INSTRUCTIONS_PROXY = """You are connected to ToolMux, an MCP tool proxy.

All tools listed are from backend servers. Call them directly by name.
If you need full parameter details for a tool, call get_tool_schema(name="tool_name").
On first use of each tool, additional context about the tool will be provided with the result."""

INSTRUCTIONS_GATEWAY = """You are connected to ToolMux, an MCP tool proxy.

Each tool represents a backend server with multiple sub-tools listed in its description.
Call format: server_name(tool="sub_tool_name", arguments={...})
Use get_tool_schema(name="sub_tool_name") for full parameter details."""


def create_server(mode: str) -> FastMCP:
    instructions = {
        "meta": INSTRUCTIONS_META,
        "proxy": INSTRUCTIONS_PROXY,
        "gateway": INSTRUCTIONS_GATEWAY,
    }
    return FastMCP(
        name="ToolMux",
        instructions=instructions[mode],
        version="2.0.0",
    )
```

**Key point**: The `instructions` parameter is part of the MCP protocol spec. It's included in the `InitializeResult` message. MCP-compliant clients (Claude Desktop, Cursor, Cline, Claude Code) read this field and inject it into the agent's system context. This completely eliminates the need for `AGENT_INSTRUCTIONS.md`.

**Reference**: MCP SDK source at `mcp/types.py:698`:
```python
class InitializeResult:
    protocolVersion: str
    capabilities: ServerCapabilities
    serverInfo: Implementation
    instructions: str | None = None  # "Instructions describing how to use the server and its features."
```

### 4.2 Smart Description Condensation

Replace dumb `desc[:80]` truncation with intelligent condensation. This function is used in ALL modes (for catalog responses and for condensed tool descriptions in proxy/gateway modes).

```python
import re

def condense_description(description: str, max_len: int = 80) -> str:
    """Intelligently condense a tool description.

    Strategy:
    1. Extract first sentence (the action statement - MCP tools almost always lead with this)
    2. Remove filler phrases that don't help tool selection
    3. Never cut mid-word
    """
    if not description:
        return ""

    # Extract first sentence (split on '. ' to avoid decimals/abbreviations)
    match = re.match(r'^(.+?\.)\s', description + ' ')
    first_sentence = match.group(1) if match else description

    # Remove filler phrases that waste tokens without aiding selection
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
```

**Examples from real MCP tools:**
| Full (263 chars) | Condensed (57 chars) |
|---|---|
| "Read the complete contents of a file from the file system. Handles various text encodings and provides detailed error messages..." | "Read the complete contents of a file from the file system" |
| "Make line-based edits to a text file. Each edit replaces exact line sequences..." | "Make line-based edits to a text file" |
| "Shows the working tree status. Displays paths that have differences between..." | "Shows the working tree status" |

Average reduction: 74% of description characters removed.

### 4.3 Schema Condensation

For proxy and gateway modes, tool schemas are condensed to reduce token cost while preserving enough information for agents to build payloads.

```python
def condense_schema(schema: dict) -> dict:
    """Condense inputSchema: keep ALL property names with types, drop verbose extras.

    Keep: property names, property types, required array, array item types
    Drop: property descriptions, default values, enum lists, examples,
          additionalProperties, min/max constraints, nested object property descriptions
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

    result = {"type": "object", "properties": condensed_props}
    if required:
        result["required"] = required
    return result
```

**Example - `edit_file` tool:**
```
FULL (139 tokens):
  path: string  "The path to the file to edit"
  edits: array  "Array of edit operations to apply"
    items: object {oldText: string "...", newText: string "..."}
  dryRun: boolean  "If true, show preview" default: false
  additionalProperties: false

CONDENSED (41 tokens):
  path: string
  edits: array [items: object]
  dryRun: boolean
  required: [path, edits]
```

### 4.4 Invocation Enrichment (Progressive Disclosure)

**This is a key architectural feature.** When the agent calls a tool for the first time, the result includes the full original docstring so the agent understands the tool's behavior and output format. On subsequent calls to the same tool, only the raw result is returned.

```python
class ToolMuxServer:
    def __init__(self):
        self._described_tools: set[str] = set()  # Track first-invocation enrichment
        self._tool_cache: dict = {}                # Full tool definitions from backends

    def enrich_result(self, tool_name: str, backend_result: dict) -> dict:
        """Add full docstring to result on first invocation of each unique tool."""
        content = backend_result.get("content", [])

        if tool_name not in self._described_tools:
            self._described_tools.add(tool_name)
            tool_def = self._tool_cache.get(tool_name, {})
            full_desc = tool_def.get("description", "")
            full_schema = tool_def.get("inputSchema", {})

            if full_desc:
                enrichment = (
                    f"[Tool: {tool_name}]\n"
                    f"[Description: {full_desc}]\n"
                    f"[Parameters: {json.dumps(full_schema)}]"
                )
                content.append({"type": "text", "text": enrichment})

        return {"content": content}

    def enrich_error_result(self, tool_name: str, error_result: dict) -> dict:
        """On errors, always include full schema to help agent self-correct."""
        content = error_result.get("content", [])
        tool_def = self._tool_cache.get(tool_name, {})
        full_schema = tool_def.get("inputSchema", {})

        content.append({
            "type": "text",
            "text": f"[Schema for {tool_name}: {json.dumps(full_schema)}]"
        })
        return {"content": content}
```

**Token economics of progressive disclosure:**
- Discovery (tools/list): 100 tools x ~55 tokens condensed = ~5,500 tokens (vs ~13,000 full = 58% savings)
- First invocations: ~15 unique tools x ~56 tokens enrichment = ~840 tokens (one-time per tool)
- Subsequent invocations: 0 extra tokens
- The enrichment cost is AMORTIZED - you only pay for tools you actually use

### 4.5 Backend Server Management

Keep the existing `HttpMcpClient` class largely as-is. It handles HTTP/SSE backend servers well. For stdio backends, keep the subprocess management but add parallel initialization.

```python
import threading
import concurrent.futures

class BackendManager:
    """Manages connections to backend MCP servers (stdio + HTTP)."""

    def __init__(self, servers_config: dict):
        self.servers = servers_config
        self.server_processes: dict = {}
        self.tool_cache: list[dict] | None = None
        self._init_complete = threading.Event()

    def initialize_all_async(self):
        """Start all backend servers in parallel threads. Non-blocking."""
        thread = threading.Thread(target=self._init_all, daemon=True)
        thread.start()

    def _init_all(self):
        """Initialize all servers in parallel using thread pool."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
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
        # ... existing start_server + tools/list logic per server ...
        pass

    def wait_for_tools(self, timeout: float = 15.0) -> list[dict]:
        """Block until backends are ready, return all tools."""
        self._init_complete.wait(timeout=timeout)
        return self.get_all_tools()

    # ... existing start_server(), get_all_tools(), call_tool() methods
    # These are preserved from current implementation with minor refactoring
```

### 4.6 Mode-Specific Tool Registration

After backends are initialized, register tools with FastMCP based on the selected mode.

#### Meta Mode
Register the 4 meta-tools as FastMCP tool functions:

```python
@mcp.tool()
def catalog_tools() -> str:
    """Discover all available backend tools with descriptions and parameter summaries."""
    tools = backend_manager.get_all_tools()
    catalog = []
    for tool in tools:
        schema = tool.get("inputSchema", {})
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        # Build parameter hint: "path(string, required), content(string, required)"
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
    tools = backend_manager.get_all_tools()
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
def invoke(name: str, args: dict | None = None) -> str:
    """Execute any backend tool by name with arguments."""
    result = backend_manager.call_tool(name, args or {})
    enriched = enrich_result(name, result)
    return json.dumps(enriched, indent=2)

@mcp.tool()
def get_tool_count() -> str:
    """Get count of available tools grouped by server."""
    tools = backend_manager.get_all_tools()
    servers = {}
    for tool in tools:
        s = tool["_server"]
        servers[s] = servers.get(s, 0) + 1
    return json.dumps({"total_tools": len(tools), "by_server": servers}, indent=2)
```

#### Proxy Mode
Dynamically register each backend tool as a real FastMCP tool with condensed schema. Use FastMCP's `add_tool()` method.

```python
def register_proxy_tools(mcp: FastMCP, backend_manager: BackendManager):
    """Register all backend tools as condensed real tools."""
    tools = backend_manager.wait_for_tools()

    for tool_def in tools:
        tool_name = tool_def["name"]
        condensed_desc = condense_description(tool_def.get("description", ""))

        # Create a closure that routes to the correct backend
        def make_handler(tn):
            async def handler(**kwargs) -> str:
                result = backend_manager.call_tool(tn, kwargs)
                enriched = enrich_result(tn, result)
                return json.dumps(enriched)
            handler.__name__ = tn
            handler.__doc__ = condensed_desc
            return handler

        fn = make_handler(tool_name)

        # Use add_tool with the condensed schema
        # Note: FastMCP's add_tool_from_fn or direct Tool construction
        mcp.add_tool(
            Tool.from_function(
                fn,
                name=tool_name,
                description=condensed_desc,
                # Override auto-generated schema with our condensed version
            )
        )

    # Also register get_tool_schema as a helper
    @mcp.tool()
    def get_tool_schema(name: str) -> str:
        """Get full parameter details and description for any tool."""
        # ... same as meta mode ...
```

**Important**: The exact API for `add_tool` with custom schemas needs to be verified against FastMCP 2.14.x. The Tool class has a `from_function()` or direct construction path. Check `fastmcp/tools/tool.py` for the exact interface. You may need to construct a `Tool` object directly with `name`, `description`, `inputSchema`, and a `run()` callable.

#### Gateway Mode
Group tools by server and register one tool per server:

```python
def register_gateway_tools(mcp: FastMCP, backend_manager: BackendManager):
    """Register one tool per backend server with sub-tool listing."""
    tools = backend_manager.wait_for_tools()

    # Group by server
    servers: dict[str, list[dict]] = {}
    for tool in tools:
        server = tool["_server"]
        servers.setdefault(server, []).append(tool)

    for server_name, server_tools in servers.items():
        tool_names = [t["name"] for t in server_tools]
        desc = f"Tools: {', '.join(tool_names)}"

        def make_handler(sn):
            async def handler(tool: str, arguments: dict | None = None) -> str:
                result = backend_manager.call_tool(tool, arguments or {})
                enriched = enrich_result(tool, result)
                return json.dumps(enriched)
            handler.__name__ = sn
            handler.__doc__ = desc
            return handler

        fn = make_handler(server_name)
        mcp.add_tool_from_fn(fn, name=server_name, description=desc)

    # Also register get_tool_schema helper
    # ... same as other modes ...
```

### 4.7 Main Entry Point

```python
def main():
    parser = argparse.ArgumentParser(
        description="ToolMux - MCP proxy/gateway with token optimization"
    )
    parser.add_argument("--config", help="Path to mcp.json config file")
    parser.add_argument("--version", action="version", version="ToolMux 2.0.0")
    parser.add_argument("--mode", choices=["proxy", "meta", "gateway"], default=None,
                        help="Operating mode (default: proxy, or from config)")
    parser.add_argument("--list-servers", action="store_true")

    args = parser.parse_args()

    # Load config
    config = load_config(args.config)  # existing function, returns servers dict

    # Determine mode: CLI flag > config file > default
    mode = args.mode or config.get("mode", "proxy")

    if args.list_servers:
        # ... existing list-servers logic ...
        return

    servers = config.get("servers", config)  # handle both old and new format

    # Create backend manager
    backend_manager = BackendManager(servers)

    # Create FastMCP server with mode-appropriate instructions
    mcp = create_server(mode)

    # Start backend initialization in background
    backend_manager.initialize_all_async()

    # Register tools based on mode
    if mode == "meta":
        register_meta_tools(mcp, backend_manager)
    elif mode == "proxy":
        register_proxy_tools(mcp, backend_manager)
    elif mode == "gateway":
        register_gateway_tools(mcp, backend_manager)

    # Run the server (FastMCP handles stdio/transport)
    mcp.run()
```

### 4.8 Tool Name Collision Handling

When two backends expose a tool with the same name:

```python
def resolve_collisions(tools: list[dict]) -> list[dict]:
    """Handle duplicate tool names across servers by prefixing with server name."""
    seen: dict[str, str] = {}  # name -> first server that claimed it

    for tool in tools:
        name = tool["name"]
        server = tool["_server"]

        if name in seen and seen[name] != server:
            # Collision - prefix both with server name
            # Rename the first one (find it in the list)
            for t in tools:
                if t["name"] == name and t["_server"] == seen[name]:
                    t["name"] = f"{seen[name]}_{name}"
                    break
            tool["name"] = f"{server}_{name}"
            print(f"Warning: tool name collision '{name}' - "
                  f"renamed to {seen[name]}_{name} and {server}_{name}",
                  file=sys.stderr)
        else:
            seen[name] = server

    return tools
```

---

## 5. VERSION SYNC

When updating the version, ALL of these locations must match:
1. `pyproject.toml` line 7: `version = "X.Y.Z"`
2. `toolmux/__init__.py` line 8: `__version__ = "X.Y.Z"`
3. `toolmux/main.py` - in `FastMCP(version="X.Y.Z")` and `argparse --version`
4. `toolmux/main.py` - in `HttpMcpClient` clientInfo version

Target version for this rewrite: **2.0.0**

---

## 6. CONFIGURATION FORMAT

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
The `"servers"` field format is unchanged - full backwards compatibility.

---

## 7. DEPENDENCIES

### Update `requirements.txt`:
```
fastmcp>=2.14.0,<3
mcp>=1.20.0
httpx>=0.24.0
python-dotenv>=1.0.1
```

### Update `pyproject.toml` dependencies:
```toml
dependencies = [
    "fastmcp>=2.14.0,<3",
    "mcp>=1.20.0",
    "httpx>=0.24.0",
    "python-dotenv>=1.0.1",
]
```

**Removed**: `click` (FastMCP handles CLI), `pydantic` (comes with FastMCP), `websockets` (comes with FastMCP)

**Changed**: `fastmcp>=0.2.0` → `fastmcp>=2.14.0,<3` (pinned to latest stable 2.x series; see section 13 for 3.0 migration path)

**Added**: `mcp>=1.20.0` - explicit dependency on MCP SDK (previously only transitive via FastMCP)

### Why Pin `<3`

FastMCP 3.0 (currently RC2, Feb 2026) introduces breaking changes including the provider/transform
architecture redesign. Key incompatibilities:
- `FastMCPProxy` is replaced by `ProxyProvider`
- Constructor kwargs like `ui=` changed to `app=` with `AppConfig`
- 16 `FastMCP()` constructor kwargs removed
- `fastmcp dev` became `fastmcp dev inspector`

We should adopt 3.0 features in a separate major version (ToolMux 3.0) after FastMCP 3.0 reaches
stable release. See section 13 for the migration roadmap.

---

## 8. TESTING REQUIREMENTS

### Update existing tests
The existing tests check for exact meta-tool names in tools/list:
```python
expected_tools = {"catalog_tools", "get_tool_schema", "invoke", "get_tool_count"}
```
These tests should still pass in `--mode meta`. For proxy mode, tests should verify backend tools appear directly.

### New tests needed

1. **test_instructions_field.py**: Verify the `instructions` field is present in initialize response for each mode, and contains appropriate content.

2. **test_proxy_mode.py**:
   - tools/list returns real backend tool names (not meta-tools)
   - Agent can call backend tools directly by name
   - `get_tool_schema` is available as helper
   - Results are properly passthrough'd from backends

3. **test_gateway_mode.py**:
   - tools/list returns server-grouped tools
   - Calling `server_name(tool="x", arguments={...})` routes correctly

4. **test_description_condensation.py**:
   - Smart condensation extracts first sentence
   - Filler phrases are removed
   - Never cuts mid-word
   - Empty descriptions handled

5. **test_schema_condensation.py**:
   - All property names preserved
   - Types preserved
   - Descriptions stripped
   - Defaults/enums stripped
   - Nested objects simplified
   - Required array preserved

6. **test_invocation_enrichment.py**:
   - First call includes full docstring
   - Second call to same tool does NOT include docstring
   - Error results include full schema

7. **test_parallel_init.py**:
   - Backend servers initialize in parallel
   - Slow server doesn't block fast ones
   - Timeout handling works

8. **test_collision_handling.py**:
   - Duplicate tool names across servers get prefixed

### Keep existing tests
- `test_simple.py` - update to test with `--mode meta`
- `test_mcp_protocol.py` - should work against any mode
- `test_e2e.py` - update for proxy mode as default
- `test_token_analysis.py` / `test_token_analysis_v2.py` - keep as reference/benchmarks

---

## 9. FILES TO MODIFY

| File | Action | Notes |
|------|--------|-------|
| `toolmux/main.py` | **Rewrite** | Replace entire implementation with FastMCP-based server. Keep HttpMcpClient class, rewrite ToolMux class, rewrite main(). |
| `toolmux/__init__.py` | **Update** | Version to 2.0.0, update exports |
| `pyproject.toml` | **Update** | Version, dependencies |
| `requirements.txt` | **Update** | Dependencies |
| `toolmux/Prompt/AGENT_INSTRUCTIONS.md` | **Keep** | Preserve for documentation, but note it's no longer required (instructions embedded in MCP protocol) |
| `tests/test_simple.py` | **Update** | Add mode flag support |
| `tests/test_mcp_protocol.py` | **Update** | Verify instructions field |
| `tests/test_e2e.py` | **Update** | Default mode is now proxy |
| `mcp.json` | **Keep** | Backwards compatible |

---

## 10. IMPLEMENTATION ORDER

### Phase 1: FastMCP Foundation + Meta Mode with Instructions
1. Rewrite `main()` to use `FastMCP(instructions=...)`
2. Register 4 meta-tools as `@mcp.tool()` functions
3. Add smart description condensation to `catalog_tools`
4. Add `--mode` CLI argument (only `meta` working initially)
5. Verify: `instructions` field appears in initialize response
6. Verify: existing meta-mode tests pass

### Phase 2: Backend Manager with Parallel Init
1. Extract backend management into `BackendManager` class
2. Add `threading`-based parallel initialization
3. Add `initialize_all_async()` and `wait_for_tools()`
4. Verify: backends start faster with parallelism

### Phase 3: Invocation Enrichment
1. Add `_described_tools` tracking set
2. Add `enrich_result()` - full docstring on first call
3. Add `enrich_error_result()` - full schema on errors
4. Apply enrichment in `invoke()` (meta), direct handlers (proxy), server handlers (gateway)
5. Verify: first call includes docstring, second doesn't

### Phase 4: Proxy Mode (New Default)
1. Add `register_proxy_tools()` - dynamic registration of condensed tools
2. Add `condense_schema()` for schema optimization
3. Add direct routing (tool call → backend lookup → forward)
4. Add collision handling
5. Verify: agent can call `read_file(path="/tmp/x")` directly
6. Set as default mode

### Phase 5: Gateway Mode
1. Add `register_gateway_tools()` - server-grouped tools
2. Route `server_name(tool="x", arguments={...})` to backend
3. Verify: tools are grouped correctly

### Phase 6: Polish
1. Update all version strings to 2.0.0
2. Update dependencies in pyproject.toml and requirements.txt
3. Update existing tests
4. Write new tests
5. Clean up AGENT_INSTRUCTIONS.md (note it's now embedded)

---

## 11. KEY REFERENCES

### FastMCP API (installed at `/usr/local/lib/python3.11/dist-packages/fastmcp/`)
- **Server constructor**: `FastMCP(name, instructions, version)` → `fastmcp/server/server.py:156`
- **instructions property**: `server.py:355-360` - getter/setter, passed to low-level server
- **add_tool()**: `server.py:1862` - register a Tool object at runtime
- **add_tool_from_fn()**: via ToolManager at `tools/tool_manager.py:78`
- **remove_tool()**: `server.py:1887` - auto-sends `notifications/tools/list_changed`
- **Tool class**: `fastmcp/tools/tool.py` - FunctionTool, Tool base
- **Proxy pattern**: `fastmcp/server/proxy.py` - ProxyToolManager, FastMCPProxy
- **mount()**: `server.py:2647` - compose servers

### MCP Protocol (installed at `/usr/local/lib/python3.11/dist-packages/mcp/`)
- **InitializeResult with instructions**: `mcp/types.py:695-699`
- **Server session sends instructions**: `mcp/server/session.py:183`
- **Low-level server stores instructions**: `mcp/server/lowlevel/server.py:142,152,188`

### Token Analysis (our benchmarks)
- `tests/test_token_analysis.py` - 6 approaches compared at scale
- `tests/test_token_analysis_v2.py` - smart condensation + progressive disclosure measurements
- `docs/SMART_PROXY_PLAN.md` - design exploration and trade-off analysis

---

## 12. SUCCESS CRITERIA

1. **Meta mode**: Agent uses ToolMux correctly WITHOUT any AGENT_INSTRUCTIONS.md in context (instructions embedded via MCP protocol)
2. **Proxy mode**: Agent calls backend tools by their real names like any normal MCP server
3. **Gateway mode**: Agent discovers and calls grouped tools naturally
4. **All modes**: First invocation of each tool includes full docstring in result
5. **All modes**: Error results include full schema for self-correction
6. **Backwards compatible**: Old mcp.json configs work without changes
7. **Existing tests**: Pass with `--mode meta`
8. **Token efficiency**: Meta 93-99%, Proxy 55-75%, Gateway 87-92% (measured vs full passthrough)

---

## 13. FASTMCP 3.0 MIGRATION ROADMAP

FastMCP 3.0 (currently 3.0.0rc2, Feb 2026) introduces a provider/transform architecture that aligns
closely with ToolMux's goals. When 3.0 reaches stable, ToolMux should adopt it as v3.0.

### FastMCP 2.14.x Features Used by ToolMux v2 (Current)

| Feature | ToolMux Usage |
|---------|---------------|
| `FastMCP(name, instructions, version)` | Server with embedded agent instructions |
| `@mcp.tool()` decorator | Meta-tool registration (catalog_tools, invoke, etc.) |
| `FastMCP.as_proxy(backend)` | One-liner to proxy each backend server |
| `server.mount(other_server, prefix=)` | Compose multiple backends into one server |
| `MCPConfig` / `StdioMCPServer` / `RemoteMCPServer` | Native mcp.json parsing |
| `ProxyToolManager` | Auto-discover + route tools from backends |
| `ToolTransformConfig` | Rename tools on collision, filter by tags |
| `compress_schema()` | Built-in schema compression (prune titles, defs, additionalProperties) |
| `server.run(transport="stdio")` | Replaces manual stdin/stdout JSON-RPC loop |
| `Tool.from_function()` / `add_tool()` | Dynamic tool registration for proxy mode |

### FastMCP 3.0 Features for ToolMux v3 (Future)

| 3.0 Feature | ToolMux Benefit |
|-------------|----------------|
| **ProxyProvider** | Replaces `FastMCPProxy` — cleaner, composable provider for each backend |
| **TransformingProvider** | Apply schema condensation as middleware without modifying tool sources |
| **FileSystemProvider** | Auto-discover backend configs from a directory of mcp.json files |
| **Component versioning** (`@tool(version="2.0")`) | Evolve tool APIs across ToolMux versions |
| **`tool_concurrency` parameter** | Concurrent execution across aggregated backends |
| **Session-scoped state** (`ctx.set_state/get_state`) | Per-client `_described_tools` tracking (progressive disclosure) |
| **`ctx.enable_components()`** | Dynamic per-session tool visibility |
| **ResourcesAsTools / PromptsAsTools** | Expose backend resources and prompts through tool-only clients |
| **Background tasks (Docket)** | Long-running backend operations with progress reporting |
| **`--reload` flag** | Dev-time auto-restart when config or code changes |
| **OpenTelemetry tracing** | Distributed tracing across ToolMux → backend calls |

### Migration Steps (ToolMux v2 → v3)

1. Wait for FastMCP 3.0 stable release (not RC)
2. Update dependency: `fastmcp>=3.0.0,<4`
3. Replace `FastMCPProxy` with `ProxyProvider` for each backend
4. Replace manual schema condensation with `TransformingProvider` middleware
5. Replace `_described_tools` set with session-scoped state
6. Add `tool_concurrency` for parallel backend execution
7. Consider `FileSystemProvider` for config-driven backend discovery
8. Update tests for new provider API
9. Bump ToolMux to v3.0.0
