# ToolMux - Agent Instructions

## Overview
You are connected to ToolMux that provides **98.65% token efficiency** by exposing only 4 meta-tools instead of loading hundreds of tool schemas directly.

## Available Tools
You have access to **4 meta-tools only** (not direct backend tools):

### 1. `catalog_tools`
- **Purpose**: Discover all available tools from backend MCP servers
- **Usage**: `catalog_tools` (no parameters)
- **Returns**: List of all tools with server names and descriptions

### 2. `get_tool_schema`
- **Purpose**: Get input schema for a specific tool
- **Usage**: `get_tool_schema({"name": "tool_name"})`
- **Returns**: Tool parameters and requirements

### 3. `invoke`
- **Purpose**: Execute any backend tool
- **Usage**: `invoke({"name": "tool_name", "args": {...}})`
- **Returns**: Tool execution results

### 4. `get_tool_count`
- **Purpose**: Show statistics about loaded servers and tools
- **Usage**: `get_tool_count` (no parameters)
- **Returns**: Tool count by server

## Recommended Workflow

### For New Tasks
1. **Discovery**: Start with `catalog_tools` to see available tools
2. **Schema**: Use `get_tool_schema("tool_name")` to understand parameters
3. **Execute**: Call `invoke("tool_name", {args})` to run the tool

### Example Session
```
User: "Read the file /tmp/test.txt"

Agent Steps:
1. catalog_tools → See "read_file" tool available
2. get_tool_schema({"name": "read_file"}) → Learn it needs "path" parameter
3. invoke({"name": "read_file", "args": {"path": "/tmp/test.txt"}}) → Execute
```

## Important Notes

- **Never call tools directly** - Always use `invoke()`
- **Always discover first** - Use `catalog_tools` for new sessions
- **Check schemas** - Use `get_tool_schema()` for unfamiliar tools
- **Efficiency focus** - This approach saves 98.65% of token usage

## Error Handling

If you get "Tool not found" errors:
1. Run `catalog_tools` to see available tools
2. Check exact tool name spelling
3. Verify the tool exists in the backend servers

## Transport Support

ToolMux v1.2.1+ supports **mixed transport configurations**:

### Supported Transports
- **stdio**: Traditional subprocess-based MCP servers
- **HTTP/SSE**: Remote HTTP-based MCP servers with authentication

### Mixed Configuration Benefits
- **Unified Interface**: All tools appear through the same 4 meta-tools
- **Transparent Routing**: ToolMux handles protocol translation automatically
- **Authentication**: Support for Bearer tokens, API keys, OAuth headers
- **Scalability**: Combine local stdio + remote HTTP servers seamlessly

### Example Mixed Setup
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
      "headers": {"Authorization": "Bearer token"}
    }
  }
}
```

You don't need to know which transport a tool uses - ToolMux handles everything transparently!

## Benefits

- **98.65% token reduction** compared to direct tool loading
- **On-demand server startup** - servers load only when needed
- **Full functionality** - access to all backend tools through meta-tools
- **Mixed transports** - stdio and HTTP/SSE servers in same configuration
- **Scalable** - works with unlimited MCP servers across any transport
