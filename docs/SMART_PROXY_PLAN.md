# ToolMux Smart Proxy - Design Plan

## Problem Statement

Current ToolMux exposes 4 meta-tools (`catalog_tools`, `get_tool_schema`, `invoke`, `get_tool_count`). This achieves ~98% token reduction but creates a fundamental UX problem: **agents don't know how to use these tools without extra context/instructions**.

A normal MCP server exposes `read_file`, `write_file`, etc. - agents see them and naturally call them. ToolMux exposes `invoke` which means nothing to an agent without being taught the catalog→schema→invoke workflow via `AGENT_INSTRUCTIONS.md`.

**Goal**: Make ToolMux work like any normal MCP server while maintaining 90-95% token efficiency.

## Token Analysis Results

We measured 6 different approaches against a realistic 19-tool, 3-server setup, then projected to 20/50/100/200 tools:

| Approach | 20 tools | 50 tools | 100 tools | 200 tools | Agent UX |
|----------|----------|----------|-----------|-----------|----------|
| Full Passthrough | 0% | 0% | 0% | 0% | Native |
| **Current Meta (4 tools)** | **94%** | **97.6%** | **98.8%** | **99.4%** | **Requires instructions** |
| Condensed Proxy | 58.3% | 59.6% | 59.9% | 59.9% | Native |
| Ultra-Condensed Proxy | 73.9% | 75.1% | 75.7% | 75.6% | Native |
| Hybrid Grouped | 86.7% | 87.6% | 88.1% | 88.0% | Near-native |
| Enhanced Meta | 77.1% | 82.0% | 83.8% | 84.2% | Good |

**None of the measured approaches hit 90% while maintaining native UX.**

But there's an approach we didn't measure: **Ultra-Minimal Real Tools** - expose all backend tools with just name + short description + empty schema. No parameter info in the schema at all. Parameters are passed through transparently. Agent calls tools by their real names.

### Ultra-Minimal Token Math

Per tool (compact JSON): `{"name":"read_file","description":"Read file content","inputSchema":{}}` = ~15 tokens

| Tool Count | Ultra-Minimal Tokens | Full Tokens | Savings |
|------------|---------------------|-------------|---------|
| 20 | ~340 | ~2,700 | 87.4% |
| 50 | ~800 | ~6,800 | 88.2% |
| 100 | ~1,550 | ~13,500 | 88.5% |
| 200 | ~3,100 | ~27,000 | 88.5% |

Close to 90% but not quite. **To push past 90%, we combine ultra-minimal tools with a hybrid description strategy**: tools with obvious names get NO description (just the name), while ambiguous tools get a very short one.

`{"name":"read_file","inputSchema":{}}` = ~10 tokens

| Tool Count | No-Desc Tokens | Full Tokens | Savings |
|------------|---------------|-------------|---------|
| 50 | ~550 | ~6,800 | 91.9% |
| 100 | ~1,050 | ~13,500 | 92.2% |
| 200 | ~2,100 | ~27,000 | 92.2% |

**This hits 90-92% savings with fully native agent UX.**

## Proposed Architecture: Three Modes

### Mode 1: `proxy` (NEW DEFAULT)

**How it works**: Expose all backend tools directly with ultra-condensed schemas. Agent calls tools by their real names. ToolMux transparently routes to the correct backend.

**tools/list response**:
```json
{
  "tools": [
    {"name": "read_file", "description": "Read file content", "inputSchema": {"type": "object"}},
    {"name": "write_file", "description": "Write content to file", "inputSchema": {"type": "object"}},
    {"name": "search_files", "description": "Search for files by pattern", "inputSchema": {"type": "object"}},
    ...all backend tools ultra-condensed...
    {"name": "get_tool_schema", "description": "Get full parameter schema for any tool by name",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}
  ]
}
```

**Agent workflow** (no instructions needed):
1. Agent sees `read_file` in tools/list -> calls `read_file(path="/tmp/x")`
2. ToolMux finds `read_file` belongs to `filesystem` server -> routes there
3. If agent doesn't know params, calls `get_tool_schema(name="read_file")` -> gets full schema
4. If backend returns param error, agent can self-correct

**Token savings**: 88-92%
**Agent UX**: Fully native - identical to any normal MCP
**Extra context needed**: None

### Mode 2: `hybrid`

**How it works**: Group tools by server. Each server becomes a single MCP tool with sub-tools listed in the description.

**tools/list response**:
```json
{
  "tools": [
    {"name": "filesystem", "description": "File tools: read_file, write_file, edit_file, search_files, list_directory, ...",
     "inputSchema": {"type": "object", "properties": {"tool": {"type": "string"}, "arguments": {"type": "object"}}, "required": ["tool"]}},
    {"name": "brave_search", "description": "Search tools: brave_web_search, brave_local_search",
     "inputSchema": {"type": "object", "properties": {"tool": {"type": "string"}, "arguments": {"type": "object"}}, "required": ["tool"]}},
    {"name": "get_tool_schema", "description": "Get full parameter schema for any tool",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}
  ]
}
```

**Agent workflow**: `filesystem(tool="read_file", arguments={"path": "/tmp/x"})`

**Token savings**: 87-92% (scales better with many servers)
**Agent UX**: Near-native - one level of indirection through server name
**Extra context needed**: None

### Mode 3: `meta` (CURRENT, preserved for backwards compatibility)

Existing 4 meta-tools. Requires AGENT_INSTRUCTIONS.md context.

**Token savings**: 94-99%
**Agent UX**: Requires training/context
**Extra context needed**: AGENT_INSTRUCTIONS.md

## Key Implementation Components

### 1. Background Server Initialization (All Modes)

**Problem**: Backend servers must be initialized before tools/list can return real tool names. But initialization can take seconds (especially with many servers or npm-based MCPs).

**Solution**: Start backend initialization immediately on `initialize` response using background threads. Track progress per server.

```python
import threading

class ToolMux:
    def __init__(self, servers_config, mode="proxy"):
        self.mode = mode
        self._init_event = threading.Event()
        self._init_thread = None

    def handle_request(self, request):
        if method == "initialize":
            # Start background init immediately
            self._init_thread = threading.Thread(target=self._background_init)
            self._init_thread.daemon = True
            self._init_thread.start()
            return initialize_response

        elif method == "tools/list":
            if self.mode == "meta":
                return meta_tools_response  # Instant, no backend needed

            # Wait for backends (with timeout)
            self._init_event.wait(timeout=10)

            if self._init_event.is_set():
                return condensed_tools_response  # Backends ready
            else:
                # Backends still loading - return meta-tools as fallback
                # Send list_changed notification when ready
                return meta_tools_fallback_response
```

**Parallel initialization**: Each server starts in its own thread, so slow servers don't block fast ones. The `_init_event` is set when ALL servers are done (or timed out).

### 2. Schema Condensation

Function that takes a full tool definition and returns an ultra-condensed version:

```python
def condense_tool(tool: dict, include_description: bool = True) -> dict:
    """Create ultra-condensed tool for proxy mode."""
    result = {
        "name": tool["name"],
        "inputSchema": {"type": "object"}
    }
    if include_description:
        desc = tool.get("description", "")
        # First sentence, max 60 chars
        short = desc.split(".")[0][:60].strip()
        if short:
            result["description"] = short
    return result
```

### 3. Direct Tool Routing

When `tools/call` receives a request, check if the tool name is a meta-tool or a backend tool:

```python
def handle_request(self, request):
    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        # Check meta-tools first
        if tool_name == "get_tool_schema":
            return self._handle_get_schema(tool_args)
        elif tool_name == "catalog_tools":
            return self._handle_catalog()

        # Direct routing: treat as backend tool call
        result = self.call_tool(tool_name, tool_args)
        return jsonrpc_result(request, result)
```

In proxy mode, the agent calls `read_file(path="/tmp/x")` and it arrives as:
```json
{"method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "/tmp/x"}}}
```

ToolMux looks up `read_file` → finds it belongs to `filesystem` server → routes to that backend.

### 4. tools/list_changed Notification

After background init completes, if the initial tools/list returned a fallback (meta-tools), send a notification so the client re-requests:

```python
def _background_init(self):
    self.get_all_tools()  # Initializes all backends
    self._init_event.set()

    # If we returned fallback on first tools/list, notify client
    if self._sent_fallback:
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/tools/list_changed"
        }
        print(json.dumps(notification))
        sys.stdout.flush()
```

### 5. CLI Configuration

```bash
toolmux --mode proxy    # NEW DEFAULT: Ultra-condensed real tools
toolmux --mode hybrid   # Server-grouped tools
toolmux --mode meta     # Current 4 meta-tools (requires AGENT_INSTRUCTIONS)
toolmux --mode full     # Full passthrough (no optimization)
```

Also configurable in mcp.json:
```json
{
  "mode": "proxy",
  "servers": { ... }
}
```

## Implementation Order

### Phase 1: Background Initialization
- Add `threading`-based parallel server startup on `initialize`
- Add `_init_event` for readiness tracking
- Add timeout handling (per-server and global)
- **Test**: Verify backends initialize in background, tools/list waits appropriately

### Phase 2: Proxy Mode (New Default)
- Add `condense_tool()` function
- Modify `tools/list` to return condensed real tools when backends ready
- Add direct routing in `tools/call` - any non-meta tool routes to backend
- Keep `get_tool_schema` as the one meta-tool helper
- Keep `catalog_tools` for agents that want full descriptions
- **Test**: Agent can call tools directly by name without any instructions

### Phase 3: Hybrid Mode
- Add server-grouping logic
- Build per-server tools with sub-tool descriptions
- Route `server_name(tool="x", arguments={...})` to correct backend
- **Test**: Agent can discover and call grouped tools naturally

### Phase 4: Mode Configuration
- Add `--mode` CLI argument
- Add `mode` field in mcp.json
- Preserve `meta` mode as backwards-compatible option
- **Test**: All modes work correctly, default is `proxy`

### Phase 5: list_changed Notification
- Send `notifications/tools/list_changed` when background init completes after fallback
- Handle edge case where tools/list is called before init starts
- **Test**: Clients that support list_changed get updated tool list

### Phase 6: Update Tests
- Update `test_simple.py` to test proxy mode (tools/list returns real tools)
- Update `test_mcp_protocol.py` for new default behavior
- Add new test for mode switching
- Add token efficiency measurement test
- Keep meta-mode tests as regression tests

## Decision Points

### Q1: Should proxy mode include descriptions?
**Option A**: Always include short descriptions (~15 tokens/tool, 88% savings)
- Pro: Agent understands tools better
- Con: Less token efficient

**Option B**: No descriptions, just names (~10 tokens/tool, 92% savings)
- Pro: Maximum compression
- Con: Ambiguous tool names harder for agents

**Recommendation**: Option A. The 4% savings difference isn't worth the UX degradation. Most agents benefit significantly from even a short description.

### Q2: Should we include required params in condensed schema?
**Option A**: Empty schema `{"type": "object"}` (~15 tokens/tool)
- Pro: Maximum compression
- Con: Agent must guess or call get_tool_schema

**Option B**: Required params with types only (~25 tokens/tool)
- Pro: Agent can call tools without get_tool_schema for common cases
- Con: More tokens, still may not be enough for complex tools

**Recommendation**: Option A for default proxy mode (maximize compression, agents are good at guessing). Could offer "detailed" sub-mode for Option B.

### Q3: What about the `invoke` tool in proxy mode?
**Option A**: Keep it as a hidden fallback (not in tools/list)
**Option B**: Remove it - direct routing handles everything
**Option C**: Keep it in tools/list alongside real tools

**Recommendation**: Option B. In proxy mode, `invoke` is unnecessary - direct routing achieves the same thing. Simplifies the API. `invoke` only exists in `meta` mode.

### Q4: How to handle tool name collisions across servers?
If two backend servers expose a tool with the same name (e.g., both have `search`):
**Option A**: First server wins
**Option B**: Prefix with server name (`filesystem_search`, `git_search`)
**Option C**: Error on startup

**Recommendation**: Option B for proxy mode (prefix on collision), Option A as fallback. Log a warning on collision.

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Background init blocks tools/list too long | Agent startup delay | 10s timeout, fallback to meta-tools |
| Agent guesses wrong params | Failed tool call | Error message guides agent, get_tool_schema available |
| Tool name collisions | Routing ambiguity | Prefix with server name on collision |
| Backwards incompatibility | Breaks existing users | meta mode preserved, explicit --mode flag |
| list_changed not supported by client | Stale tool list | Fallback meta-tools still functional |

## Success Criteria

1. Agent (Claude/GPT) can use ToolMux tools WITHOUT any AGENT_INSTRUCTIONS context
2. Token efficiency is 88-92% for proxy mode (measured)
3. All existing tests pass in meta mode (backwards compat)
4. Background init doesn't slow agent startup beyond 2-3 seconds
5. Direct tool calling works transparently across stdio and HTTP backends
