# ToolMux v2.3.0 — Search Mode & Code Mode

**Date:** 2026-04-06
**Status:** Approved
**Scope:** Add two new operating modes leveraging FastMCP 3.1+ native transforms

---

## Problem

ToolMux's existing modes (gateway, meta, proxy) all require the agent to load or scan the full tool catalog. For deployments with 100+ tools, this wastes tokens on tools the agent never uses. Multi-step workflows also suffer from round-trip overhead — each intermediate result burns context tokens.

## Solution

Two new modes built on FastMCP's native transform system:

- **search mode** — BM25-ranked tool discovery via `BM25SearchTransform`
- **code mode** — BM25 discovery + sandboxed multi-step execution via `CodeMode`

Both run on ToolMux's existing native proxy infrastructure (`create_proxy` + per-server mounting), gaining session isolation, MCP feature forwarding, and error isolation for free.

## Mode Comparison (updated)

| Mode | Token Savings | Discovery | Execution | Best For |
|---|---|---|---|---|
| gateway (default) | ~60-85% | One tool per server | `server(tool=, args=)` | Small-medium setups |
| meta | ~80-93% | Flat catalog dump | `invoke(name, args)` | Token-constrained envs |
| proxy | ~69% | All tools (condensed) | Direct `tool_name()` | Full MCP compliance |
| **search** (new) | ~85-95% | BM25 ranked top-k | `call_tool(name, args)` | Large catalogs (100+) |
| **code** (new) | ~90-97% | BM25 ranked | Sandboxed Python | Multi-step workflows |

---

## Architecture

### Search Mode

```python
def run_search_mode(servers, config, config_path):
    # Same proxy setup as run_proxy_native()
    mcp_config = _build_proxy_mcp_config(servers)
    
    # Mount backends with error isolation (same as proxy mode)
    proxy = FastMCP(name="ToolMux", version=VERSION)
    for name, srv_cfg in mcp_config["mcpServers"].items():
        single = {"mcpServers": {name: srv_cfg}}
        backend = create_proxy(single, name=f"Proxy-{name}")
        proxy.mount(backend, namespace=name)
    
    # Add BM25SearchTransform instead of CondenseTransform
    from fastmcp.server.transforms.search.bm25 import BM25SearchTransform
    proxy.add_transform(BM25SearchTransform(max_results=10))
    
    # Register ToolMux helper tools (list_all_tools, get_tool_count, manage_servers)
    # These bypass the transform via direct catalog access
    
    proxy.run(show_banner=False)
```

The `BM25SearchTransform` intercepts `tools/list` and replaces all backend tools with two synthetic tools:
- `search_tools(query, limit)` — returns BM25-ranked results
- `call_tool(name, arguments)` — proxies to any backend tool

ToolMux's helper tools (`list_all_tools`, `get_tool_schema`, `get_tool_count`, `manage_servers`) are registered directly on the proxy, so they appear alongside the transform's synthetic tools.

### Code Mode

```python
def run_code_mode(servers, config, config_path):
    # Same proxy setup
    mcp_config = _build_proxy_mcp_config(servers)
    
    proxy = FastMCP(name="ToolMux", version=VERSION)
    for name, srv_cfg in mcp_config["mcpServers"].items():
        single = {"mcpServers": {name: srv_cfg}}
        backend = create_proxy(single, name=f"Proxy-{name}")
        proxy.mount(backend, namespace=name)
    
    # Add CodeMode transform
    from fastmcp.experimental.transforms.code_mode import CodeMode
    proxy.add_transform(CodeMode())
    
    # Register ToolMux helper tools
    
    proxy.run(show_banner=False)
```

`CodeMode` replaces the catalog with three synthetic tools:
- `search(query, tags, detail, limit)` — BM25 search with detail levels (brief/detailed/full)
- `get_schema(tools, detail)` — parameter schemas for named tools
- `execute(code)` — runs Python in a pydantic-monty sandbox with `call_tool()` available

### MCP Instructions

Each mode embeds instructions in the `initialize` response:

**Search mode:**
```
You are connected to ToolMux, an MCP tool proxy in search mode.

Available tools:
  - search_tools(query="...") — Find tools by natural language query (BM25 ranked)
  - call_tool(name="tool_name", arguments={...}) — Execute any tool
  - list_all_tools() — Full catalog grouped by server
  - get_tool_count() — Tool count statistics
  - manage_servers(action="list|add|remove|validate|test") — Manage backends

Workflow:
1. search_tools(query="what you need") to discover tools
2. call_tool(name="tool_name", arguments={...}) to execute
```

**Code mode:**
```
You are connected to ToolMux, an MCP tool proxy in code mode.

Available tools:
  - search(query="...") — Find tools by natural language query
  - get_schema(tools=["tool_name"]) — Get parameter details
  - execute(code="...") — Run Python code that chains tool calls
  - list_all_tools() — Full catalog grouped by server
  - get_tool_count() — Tool count statistics
  - manage_servers(action="list|add|remove|validate|test") — Manage backends

Workflow:
1. search(query="...") to discover tools
2. get_schema(tools=["name"]) for parameter details
3. execute(code="result = await call_tool('name', {args}); return result")

For multi-step workflows, chain calls in execute():
  execute(code='''
  data = await call_tool("read_file", {"path": "/tmp/data.json"})
  processed = transform(data)
  await call_tool("write_file", {"path": "/tmp/out.json", "content": processed})
  return {"status": "done"}
  ''')
```

---

## Dependencies

### pyproject.toml changes

```toml
dependencies = [
    "fastmcp>=3.1.1,<4",
    "mcp>=1.20.0",
    "click>=8.0.0",
    "pydantic>=2.6.0",
    "httpx>=0.24.0",
    "websockets>=11.0.0",
    "python-dotenv>=1.0.1",
    "pydantic-monty<0.0.8",     # NEW — sandbox for code mode
]
```

`pydantic-monty` is pinned below 0.0.8 to match FastMCP's own pin (v3.1.1 fix for breaking change in Monty 0.0.8).

---

## CLI Changes

Update argparse `--mode` choices:

```python
parser.add_argument("--mode", choices=["proxy", "meta", "gateway", "search", "code"],
                    help="Operating mode (default: gateway)")
```

No other CLI changes.

---

## Version Bump

- `toolmux/main.py`: `VERSION = "2.3.0"`
- `pyproject.toml`: `version = "2.3.0"`
- `toolmux/__init__.py`: update `__version__` if present

---

## Code Structure

All new code goes in `toolmux/main.py` (following the single-module design convention). Two new functions:

- `run_search_mode(servers, config, config_path)` — ~50 lines
- `run_code_mode(servers, config, config_path)` — ~50 lines

Both follow the pattern of existing `run_proxy_native()`. The `main()` function gets two new branches in the mode router.

---

## Testing

### New test file: `tests/test_search_code_modes.py`

Tests needed:

1. **Search mode — tools/list returns synthetic tools**: Connect to search mode, verify `tools/list` contains `search_tools` and `call_tool` (not backend tools)
2. **Search mode — search returns ranked results**: Call `search_tools` with a query, verify results are ranked and relevant
3. **Search mode — call_tool routes correctly**: Call `call_tool` with a backend tool name, verify it executes
4. **Code mode — tools/list returns synthetic tools**: Connect to code mode, verify `tools/list` contains `search`, `get_schema`, `execute`
5. **Code mode — search returns results**: Call `search` with a query, verify results
6. **Code mode — execute runs code**: Call `execute` with simple `call_tool()` code, verify it executes and returns
7. **Code mode — execute chains calls**: Call `execute` with multi-step code, verify intermediate results don't leak
8. **Helper tools available in both modes**: Verify `list_all_tools`, `get_tool_count` appear alongside synthetic tools
9. **Single-server search mode**: Verify tools are unprefixed with one backend
10. **Multi-server search mode**: Verify tools are prefixed with multiple backends
11. **Failed backend in search mode**: Verify one crashing backend doesn't take down others

### Existing tests: no changes

Existing test files cover gateway, meta, and proxy modes. They should continue passing unchanged.

---

## Deployment

1. Implement in `/tmp/toolmux-github` (public repo)
2. Run tests
3. Commit and push to GitHub
4. Publish v2.3.0 to PyPI
5. Copy changes to `/tmp/toolmux-internal` (internal repo)
6. Push to internal repo

---

## What Is NOT Changing

- Gateway mode — unchanged
- Meta mode — unchanged
- Proxy mode — unchanged
- BackendManager — unchanged (not used by new modes)
- Build cache system — not applicable to new modes (they use FastMCP's native catalog)
- Config format — no new fields needed (just `"mode": "search"` or `"mode": "code"`)
