# ToolMux Configuration Examples

This directory contains example configurations for ToolMux v1.1.1 and Q CLI agent integration.

## 🚀 Quick Start Examples

### Q CLI Agent Configurations

#### Simple Configuration
**File**: `q-cli-simple.json`
```bash
# Copy and customize for basic Q CLI integration
cp toolmux/examples/q-cli-simple.json ~/.config/q/agents/my-agent.json
```

#### Complete Configuration  
**File**: `q-cli-agent.json`
```bash
# Full-featured Q CLI agent with all ToolMux capabilities
cp toolmux/examples/q-cli-agent.json ~/.config/q/agents/toolmux-agent.json
```

#### Legacy Configuration
**File**: `example_agent_config.json`
- Updated for v1.1.1 with `uvx toolmux` command
- Includes hooks and resource references

## 🔧 MCP Server Configurations

### Individual Server Examples

#### Filesystem Access
**File**: `filesystem.json`
```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
    }
  }
}
```

#### Web Search (Brave)
**File**: `brave-search.json`
```json
{
  "servers": {
    "brave-search": {
      "command": "uvx",
      "args": ["mcp-server-brave-search"],
      "env": {"BRAVE_API_KEY": "your-api-key"}
    }
  }
}
```

#### Database Access (SQLite)
**File**: `sqlite.json`
```json
{
  "servers": {
    "sqlite": {
      "command": "uvx", 
      "args": ["mcp-server-sqlite", "--db-path", "/path/to/database.sqlite"]
    }
  }
}
```

### Mixed Transport Examples

#### HTTP/SSE Servers
**File**: `http-servers.json`
- Pure HTTP MCP server configurations
- Authentication examples
- Timeout and header configurations

#### Mixed Stdio + HTTP
**File**: `mixed-servers.json`
- Combines stdio and HTTP MCP servers
- Shows ToolMux's transport flexibility
- Real-world deployment example

### IDE Integration

#### Kiro IDE
**File**: `kiro-integration.json`
- Kiro IDE specific configuration
- Development workflow optimization
- Local development setup

## 📋 Usage Instructions

### 1. Choose Your Configuration
```bash
# For Q CLI agents
cp toolmux/examples/q-cli-simple.json ~/.config/q/agents/

# For ToolMux server configuration  
cp toolmux/examples/mixed-servers.json ~/toolmux/mcp.json
```

### 2. Customize Settings
Edit the copied file to:
- Update file paths to match your system
- Add your API keys and tokens
- Adjust server configurations
- Modify agent behavior

### 3. Test Configuration
```bash
# Test ToolMux configuration
toolmux --config ~/toolmux/mcp.json --list-servers

# Test Q CLI agent
q --agent my-agent "catalog_tools"
```

## 🎯 Configuration Tips

### For Q CLI Agents
- **Start Simple**: Use `q-cli-simple.json` first
- **System Prompt**: Include ToolMux workflow explanation
- **Tools**: Use `["*"]` to access all meta-tools
- **Timeout**: Set 30+ seconds for server startup

### For MCP Servers
- **Mixed Transport**: Combine stdio + HTTP servers
- **Environment Variables**: Use for API keys and secrets
- **Descriptions**: Add helpful descriptions for each server
- **Timeouts**: Adjust based on server response times

### For Development
- **Local Paths**: Use absolute paths for development
- **Version Pinning**: Use `uvx toolmux@1.1.1` for consistency
- **Custom Configs**: Use `--config` flag for testing

## 🔍 Example Workflows

### Discovery Workflow
```bash
# 1. List available tools
catalog_tools

# 2. Get tool parameters  
get_tool_schema({"name": "read_file"})

# 3. Execute tool
invoke({"name": "read_file", "args": {"path": "/tmp/test.txt"}})

# 4. Check efficiency
get_tool_count
```

### Multi-Server Setup
```bash
# Configure multiple servers
cp mixed-servers.json ~/toolmux/mcp.json

# Edit to add your servers
$EDITOR ~/toolmux/mcp.json

# Test the configuration
toolmux --list-servers
```

## 📚 Additional Resources

- **Main Documentation**: [README.md](../../README.md)
- **Agent Instructions**: [AGENT_INSTRUCTIONS.md](../../AGENT_INSTRUCTIONS.md)
- **PyPI Package**: https://pypi.org/project/toolmux/
- **Bug Fixes**: [docs/FIX_SUMMARY.md](../../docs/FIX_SUMMARY.md)

## 🆘 Troubleshooting

### Common Issues
1. **Server Not Starting**: Check command paths and permissions
2. **API Key Errors**: Verify environment variables are set
3. **Timeout Issues**: Increase timeout values in configuration
4. **Tool Not Found**: Use `catalog_tools` to verify availability

### Getting Help
- Check the main [README.md](../../README.md) for installation issues
- Review [AGENT_INSTRUCTIONS.md](../../AGENT_INSTRUCTIONS.md) for usage guidance
- See [docs/](../../docs/) for detailed documentation

---

*All examples are tested with ToolMux v1.1.1 and include the latest bug fixes and improvements.*