# ToolMux v2.3

**Efficient MCP server aggregation with FastMCP 3.x foundation**

ToolMux proxies multiple MCP (Model Context Protocol) servers through a single interface, reducing token overhead while maintaining full tool access. It supports five operating modes optimized for different use cases.

## Features

- **FastMCP 3.x Foundation** — Proper MCP protocol compliance via FastMCP framework
- **Five Operating Modes** — Meta (80%+ savings), Gateway (60%+ savings), Proxy (native fastmcp), Search (85%+ savings), Code (90%+ savings)
- **Native Proxy Mode** — Uses fastmcp 3.0's `create_proxy()` for true transparent proxying with session isolation and MCP feature forwarding
- **CondenseTransform** — Token optimization via fastmcp's Transform system: condensed descriptions/schemas in tools/list, full details on demand via helper tools
- **Smart Description Condensation** — First-sentence extraction with filler phrase removal
- **Schema Condensation** — Strips verbose extras, keeps names/types/required
- **Progressive Disclosure** — Full descriptions via `list_all_tools()` and `get_tool_schema()`, condensed in tools/list
- **Self-Healing Bundle Resolution** — Auto-resolves broken server configs from mcp-registry, user bundles, XDG, Claude Desktop, and Cursor bundles
- **Parallel Backend Init** — Thread pool (10 workers, 30s timeout) for fast startup
- **MCP Instructions** — All modes embed instructions in the MCP `initialize` response telling the LLM to call `list_all_tools()` first
- **LLM-Powered Description Optimization** — `optimize_descriptions` tool lets the connected LLM generate high-quality tool descriptions, replacing algorithmic condensation
- **Tool Collision Resolution** — Automatic server-name prefixing for duplicate tool names

## Installation

```bash
# Via PyPI
pip install toolmux

# Via uvx (recommended, no install needed)
uvx toolmux

# From source
git clone https://github.com/subnetangel/ToolMux.git
cd ToolMux
pip install -e .

# Verify
toolmux --version
```

## Quick Start

### 1. Configure backend servers

Create `~/shared/toolmux/mcp.json` (or `~/toolmux/mcp.json`):

```json
{
  "mode": "gateway",
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
    },
    "git": {
      "command": "uvx",
      "args": ["mcp-server-git", "--repository", "/path/to/repo"]
    }
  }
}
```

### 2. Run ToolMux

```bash
# Default gateway mode
toolmux

# Specific mode
toolmux --mode meta
toolmux --mode proxy

# Custom config
toolmux --config /path/to/mcp.json
```

### 3. Use with any MCP client

Add to your MCP client configuration (e.g., Claude Desktop, Cursor, Kiro, VS Code):
```json
{
  "mcpServers": {
    "toolmux": {
      "command": "toolmux",
      "args": ["--mode", "gateway"]
    }
  }
}
```

## Operating Modes

ToolMux offers three modes that trade off between token savings and tool transparency. All modes share a common set of helper tools (`list_all_tools`, `get_tool_schema`, `get_tool_count`, `manage_servers`, `optimize_descriptions`) and embed MCP instructions telling the LLM to call `list_all_tools()` first.

### Mode Comparison

| | Gateway (default) | Meta | Proxy | Search (new) | Code (new) |
|---|---|---|---|---|---|
| **Token savings** | ~60-85% | ~80-93% | ~69% | ~85-95% | ~90-97% |
| **tools/list size** | 1 tool per server + helpers | 5 meta-tools | All backend tools (condensed) | 2 synthetic + helpers | 3 synthetic + helpers |
| **Tool invocation** | `server(tool="name", arguments={...})` | `invoke(name="name", args={...})` | `tool_name(param="value")` | `call_tool(name="name", arguments={...})` | `execute(code="await call_tool(...)")` |
| **Backend init** | BackendManager (parallel threads) | BackendManager (parallel threads) | fastmcp `create_proxy()` | fastmcp `create_proxy()` | fastmcp `create_proxy()` |
| **Best for** | Balanced savings + usability | Maximum savings, many servers | Full MCP compliance, advanced features | Large catalogs (100+ tools) | Multi-step workflows |

### Gateway Mode (Default) — ~60-85% Token Savings

Collapses each backend server into a single tool. The LLM sees one tool per server (e.g., `filesystem`, `git`) instead of dozens of individual tools. Each server-tool's description lists all its sub-tools with their purpose and required parameters.

**How it works:**

1. On startup, `BackendManager` initializes all backends in parallel (10-worker thread pool, 30s timeout). If a build cache exists (`.toolmux_cache.json`), tools are loaded instantly from cache and backends init in the background.
2. Tools are grouped by server. For each server, a single FastMCP tool is registered with a rich description listing all sub-tools (e.g., `"Tools: read_file (Read complete file contents; required: path), write_file (...), ..."`).
3. The LLM calls `list_all_tools()` first to discover all available tools with full descriptions.
4. To invoke a sub-tool, the LLM calls the server-tool with `tool=` and `arguments=` parameters: `filesystem(tool="read_file", arguments={"path": "/tmp/example.txt"})`.
5. On first invocation of each sub-tool, the response is enriched with the full description and parameter schema (progressive disclosure). On errors, the full schema is always appended.

```
tools/list returns:
  - filesystem (server-tool): "Tools: read_file, write_file, ..."
  - git (server-tool): "Tools: git_status, git_log, ..."
  - list_all_tools (native): MUST call first — full descriptions grouped by server
  - get_tool_schema (native): Get full parameter details for any tool
  - get_tool_count (native): Get tool count statistics by server
  - manage_servers (native): Add, remove, validate, test backend servers
  - optimize_descriptions (native): LLM-powered description optimization

Calling pattern:
  list_all_tools()  # discover all tools with full descriptions
  filesystem(tool="read_file", arguments={"path": "/tmp/example.txt"})
```

**Token savings mechanism:** Instead of exposing N tools with full descriptions and schemas in `tools/list`, gateway exposes ~S server-tools (where S << N) plus helper tools. Descriptions are condensed to first-sentence + required params. Full details are disclosed progressively on first use.

### Meta Mode — ~80-93% Token Savings

Exposes only 5 generic meta-tools regardless of how many backend tools exist. The LLM discovers tools via `list_all_tools()` / `catalog_tools()`, inspects schemas via `get_tool_schema()`, and executes via `invoke()`.

**How it works:**

1. Same `BackendManager` parallel init as gateway mode.
2. Instead of registering per-server or per-tool entries, 5 fixed tools are registered: `list_all_tools`, `catalog_tools`, `get_tool_schema`, `invoke`, `get_tool_count`.
3. `catalog_tools()` returns a JSON array of all backend tools with name, server, condensed description, and parameter names.
4. `get_tool_schema(name="tool_name")` returns the full description and `inputSchema` for a specific tool.
5. `invoke(name="tool_name", args={...})` routes the call to the correct backend server. Results are enriched with full docstrings on first invocation.

```
tools/list returns:
  - list_all_tools: MUST call first — full descriptions grouped by server
  - catalog_tools: List all backend tools with name, server, description
  - get_tool_schema: Get full schema for a tool
  - invoke: Execute a backend tool
  - get_tool_count: Tool count by server
  - manage_servers: Add, remove, validate, test backend servers
  - optimize_descriptions: LLM-powered description optimization

Workflow: list_all_tools() → get_tool_schema("tool") → invoke("tool", args)
```

**Token savings mechanism:** `tools/list` always returns exactly 7 tools (5 meta + 2 management) regardless of backend count. A setup with 200 backend tools still only shows 7 in `tools/list`. The tradeoff is an extra round-trip: the LLM must call `get_tool_schema()` before `invoke()` to know the parameters.

### Proxy Mode — Native FastMCP Proxy with Token Optimization

Uses fastmcp 3.0's native `create_proxy()` for true transparent proxying. All backend tools are exposed directly — the LLM calls them by name just like normal MCP tools. Token optimization is applied via `CondenseTransform`, which condenses descriptions and schemas in `tools/list` while helper tools return full uncondensed details.

**How it works:**

1. Server configs are converted to standard `mcpServers` format and passed to `create_proxy()`, which creates a FastMCP proxy with `MCPConfigTransport` for each backend.
2. `CondenseTransform` (a fastmcp `Transform` subclass) is applied to the proxy. It intercepts `tools/list` responses and replaces each tool's description with a condensed version (first sentence, filler removed, max 80 chars) and each schema with a minimal version (property names + types + required only).
3. Helper tools (`list_all_tools`, `get_tool_schema`, `get_tool_count`) are registered directly on the proxy. They query the proxy's internal tool list *before* the transform is applied, so they return full uncondensed descriptions and schemas.
4. For multi-server setups, tools are prefixed as `{server}_{tool}` (e.g., `filesystem_read_file`). Single-server setups leave tools unprefixed.
5. Sessions are persistent and reused across tool calls (fastmcp 3.1.1+).

```
tools/list returns all backend tools with CONDENSED descriptions/schemas.
  - Single server: tools unprefixed (echo_tool)
  - Multi server: tools prefixed as {server}_{tool}

Helper tools (return FULL uncondensed info):
  - list_all_tools(): MUST call first — full descriptions grouped by server
  - get_tool_schema(name): full description + full inputSchema
  - get_tool_count(): tool counts by server
  - manage_servers: Add, remove, validate, test backend servers

Call directly: echo_tool(message="hello")
```

**Proxy mode features:**
- True transparent proxying via fastmcp's `MCPConfigTransport`
- Session isolation per request
- Automatic MCP feature forwarding (sampling, elicitation, logging, progress)
- `CondenseTransform` for ~69% token reduction in `tools/list`
- Progressive disclosure: condensed by default, full on demand via helper tools

**Token savings mechanism:** All tools appear in `tools/list` (unlike gateway/meta), but descriptions are condensed from paragraphs to single sentences and schemas are stripped to names/types/required. The LLM calls `list_all_tools()` once to get full descriptions, then calls tools directly.

### Search Mode — ~85-95% Token Savings

Uses FastMCP's `BM25SearchTransform` to replace the full tool catalog with ranked search. The LLM discovers tools by querying `search_tools(query="what I need")` and gets back only the top-k relevant results. Execution via `call_tool(name, arguments)`.

**How it works:**
1. Same per-server proxy setup as proxy mode (error isolation, session persistence)
2. `BM25SearchTransform` intercepts `tools/list` — replaces all backend tools with `search_tools` and `call_tool`
3. BM25 indexes tool names, descriptions, and parameter names for natural language ranking
4. Helper tools (`list_all_tools`, `get_tool_schema`, `get_tool_count`) bypass the transform for full catalog access

```
tools/list returns:
  - search_tools: Find tools by natural language query (BM25 ranked)
  - call_tool: Execute any tool by name
  - list_all_tools: Full catalog grouped by server
  - get_tool_schema: Full parameter details
  - get_tool_count: Tool count statistics
  - manage_servers: Backend management

Workflow: search_tools("read file") → call_tool("filesystem_read_file", {"path": "..."})
```

**Token savings mechanism:** The LLM never sees tools it doesn't need. A search for "calendar" against 258 tools returns ~10 relevant results (~400 tokens) instead of the full catalog (~5,000 tokens).

### Code Mode — ~90-97% Token Savings

Uses FastMCP's experimental `CodeMode` transform for sandboxed multi-step execution. The LLM discovers tools via BM25 search, then writes Python code that chains multiple `call_tool()` calls in a sandbox. Intermediate results stay in the sandbox — only the final result enters the context window.

**How it works:**
1. Same per-server proxy setup as proxy mode
2. `CodeMode` replaces tools with `search`, `get_schema`, and `execute`
3. `execute(code)` runs Python in a pydantic-monty sandbox with `call_tool()` available
4. Multiple tool calls can be chained in a single `execute()` invocation
5. Helper tools bypass the transform for full catalog access

```
tools/list returns:
  - search: Find tools by query (BM25 ranked, with detail levels)
  - get_schema: Get parameter details for specific tools
  - execute: Run Python code with call_tool() in sandbox
  - list_all_tools: Full catalog grouped by server
  - get_tool_count: Tool count statistics
  - manage_servers: Backend management

Workflow: search("calendar") → get_schema(["calendar_view"]) → execute("result = await call_tool(...)")
```

**Token savings mechanism:** Multi-step workflows execute in one round-trip. Intermediate results (e.g., raw API responses passed between tools) never enter the context window — they exist only inside the sandbox.

## Shared Features

### Progressive Disclosure

All modes use progressive disclosure to minimize tokens while keeping full information accessible:

1. **`tools/list`** — Condensed descriptions and schemas (what the LLM sees on connect)
2. **`list_all_tools()`** — Full descriptions grouped by server (LLM calls this first)
3. **`get_tool_schema(name)`** — Full description + complete `inputSchema` for a specific tool
4. **First-use enrichment** (gateway/meta only) — On the first invocation of each tool, the response includes the full description and parameter schema appended to the result

### Description Condensation

The `condense_description()` function:
1. Normalizes whitespace (collapses newlines and multiple spaces)
2. Removes filler phrases ("Use this tool to", "This tool allows you to", etc.)
3. Capitalizes the first letter after filler removal
4. Extracts the first sentence (up to `.`, `!`, or `?`)
5. Trims to 80 characters without cutting mid-word

### Schema Condensation

The `condense_schema()` function strips schemas down to:
- Property names and types
- Array item types
- Required field list

Removed: descriptions, defaults, examples, enums, pattern constraints, nested object details.

### LLM-Powered Description Optimization

The `optimize_descriptions` tool lets the connected LLM generate higher-quality descriptions than the algorithmic condensation:

1. `optimize_descriptions(action="generate")` — Returns all tools with full descriptions
2. The LLM writes concise (<60 char) descriptions for each tool
3. `optimize_descriptions(action="save", server="name", descriptions={...})` — Saves to cache
4. Restart ToolMux to use the optimized descriptions

Use `optimize_descriptions(action="status")` to check if descriptions have been optimized.

### Build Cache

ToolMux caches tool descriptions in `.toolmux_cache.json` next to the config file. The cache is validated against a SHA-256 hash of `mcp.json` — any config change invalidates it.

- **Cache hit**: Tools load instantly from cache. Backends init in the background for actual tool calls.
- **Cache miss**: Server names are registered as placeholders immediately (so `mcp.run()` starts without delay). Backends init in the background. A cache is auto-generated once backends finish.

### Server Management

The `manage_servers` tool provides runtime server management:

- `manage_servers(action="list")` — List all configured servers
- `manage_servers(action="add", name="my-mcp", command="cmd")` — Add a server (auto-resolves from bundles if no command given)
- `manage_servers(action="remove", name="my-mcp")` — Remove a server
- `manage_servers(action="validate")` — Check all server commands exist on PATH
- `manage_servers(action="test", name="my-mcp")` — Start server and verify it returns tools

## Self-Healing Bundle Resolution

When a configured server command fails or returns 0 tools, ToolMux automatically
searches for the correct launch config in these locations (in order):

1. **mcp-registry bundles** (`~/.config/smithy-mcp/bundles/`)
2. **User bundles** (`~/.aim/bundles/`)
3. **XDG mcp config** (`~/.config/mcp/mcp.json`)
4. **Claude Desktop** (`~/.claude/claude_desktop_config.json`)
5. **Cursor** (`~/.cursor/mcp.json`)

If a fix is found, it's persisted back to `mcp.json` so it only happens once.

## CLI Reference

```
toolmux [OPTIONS]

Options:
  --mode {gateway,meta,proxy,search,code}  Operating mode (default: gateway)
  --config PATH                Path to mcp.json config file
  --version                    Print version and exit
  --list-servers               List configured servers and exit
  --build-cache                Generate LLM description cache and exit
  --manage [list|add|remove|validate|test]  Manage backend servers
```

## Configuration

### Config File Discovery Order

1. `--config` flag (explicit path)
2. `./mcp.json` (project-local)
3. `~/shared/toolmux/mcp.json` (shared environments — persists across sessions)
4. `~/toolmux/mcp.json` (local installs)
5. First-run setup creates `~/shared/toolmux/mcp.json`

### Config Format

```json
{
  "mode": "gateway",
  "cache_model": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
  "servers": {
    "server-name": {
      "command": "npx",
      "args": ["-y", "package-name"],
      "env": {"KEY": "value"},
      "cwd": "/optional/working/dir",
      "description": "Optional human description"
    },
    "http-server": {
      "transport": "http",
      "base_url": "https://api.example.com/mcp",
      "headers": {"Authorization": "Bearer token"},
      "timeout": 30
    }
  }
}
```

## Architecture

```
MCP Client (Agent/IDE)
    ↕ stdio JSON-RPC
FastMCP Server (ToolMux)
    ├── Mode Router → meta | gateway | proxy | search | code
    │
    ├── Gateway/Meta Mode
    │   ├── BackendManager (parallel init, tool routing)
    │   ├── Pure Functions (condense, enrich, collisions)
    │   ├── Build Cache (SHA-256 validated, auto-generated)
    │   ├── Self-Healing Bundle Resolution
    │   └── manage_servers + optimize_descriptions
    │
    ├── Proxy Mode (fastmcp native)
    │   ├── create_proxy(mcpServers config)
    │   ├── CondenseTransform (token optimization)
    │   ├── Helper tools (list_all_tools, get_tool_schema, get_tool_count)
    │   ├── manage_servers
    │   └── Session isolation + MCP feature forwarding
    │
    ├── Search Mode (fastmcp native)
    │   ├── create_proxy(mcpServers config)
    │   ├── BM25SearchTransform (replaces catalog with search_tools + call_tool)
    │   ├── Helper tools (list_all_tools, get_tool_schema, get_tool_count)
    │   └── manage_servers
    │
    └── Code Mode (fastmcp native)
        ├── create_proxy(mcpServers config)
        ├── CodeMode transform (search + get_schema + execute sandbox)
        ├── pydantic-monty sandbox (intermediate results stay in sandbox)
        ├── Helper tools (list_all_tools, get_tool_count)
        └── manage_servers
```

## Development

```bash
# Install in development mode
pip install -e ".[dev]"

# Run tests
python3 -m pytest tests/ -v

# Run with benchmark output
python3 -m pytest tests/test_token_optimization.py -v -s
```

### Test Suite

| File | Tests | Coverage |
|------|-------|----------|
| `test_pure_functions.py` | 24 | Property-based (hypothesis) + unit tests for all pure functions |
| `test_list_all_tools.py` | 20 | list_all_tools across all modes, server filtering, cache integration |
| `test_bundle_resolution.py` | 20 | Self-healing bundle resolution across 5 config sources |
| `test_config_cli.py` | 15 | Config discovery, CLI args, version sync, build cache |
| `test_backend.py` | 11 | BackendManager, HttpMcpClient, parallel init |
| `test_protocol_e2e.py` | 11 | MCP protocol compliance, end-to-end mode workflows |
| `test_token_optimization.py` | 6 | Token savings benchmarks per mode |
| **Total** | **107** | **0 failures** |

## Version History

| Version | Changes |
|---------|---------|
| 2.1.0 | Native proxy mode via fastmcp `create_proxy()`, `CondenseTransform` for proxy token optimization, helper tools (`list_all_tools`/`get_tool_schema`/`get_tool_count`) bypass transform in proxy mode, session isolation per request, MCP feature forwarding (sampling, elicitation, logging, progress) |
| 2.0.8 | `list_all_tools` in all modes, MCP instructions in `initialize` response, `.gitignore` bundle fix |
| 2.0.7 | Self-healing bundle resolution (5 config sources), 8 test fixes, publish script symlink fix |
| 2.0.6 | `list_all_tools` gateway tool with server filtering and cached description support |
| 2.0.5 | Cache-first startup (no more init timeout), graceful stdin EOF handling, stderr suppression, version sync |
| 2.0.0 | Initial v2: FastMCP foundation, 3 operating modes, BackendManager, parallel init, smart condensation, build cache, collision resolution |

## License

MIT
