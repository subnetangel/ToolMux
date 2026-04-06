# ToolMux Configuration Examples

This directory contains **real working examples** based on actual production configurations, anonymized for security.

## 📁 Available Examples

### `q-cli-agent-config.json`
**Q CLI Agent Configuration**
- **Purpose**: Complete Q CLI agent setup with ToolMux integration
- **Location**: `~/.aws/amazonq/cli-agents/your-agent.json`
- **Features**: Agent definition with hooks, resources, and tool allowlists
- **Based on**: Real Q CLI agent configuration

### `q-cli-toolmux-config.json`
**Q CLI Backend Configuration**
- **Purpose**: ToolMux backend server configuration for Q CLI
- **Location**: Custom path (referenced by agent config)
- **Features**: Enterprise MCP servers, AWS tools, development utilities
- **Based on**: Real backend server configuration

### `kiro-mcp-config.json`
**Kiro IDE Configuration**
- **Purpose**: ToolMux integration for Kiro IDE
- **Location**: `.kiro/settings/mcp.json`
- **Features**: IDE-optimized ToolMux setup with custom config path
- **Based on**: Real Kiro IDE configuration

### `example_mcp.json`
**General ToolMux Configuration**
- **Purpose**: Default ToolMux backend configuration
- **Location**: `~/toolmux/mcp.json` (default location)
- **Features**: Complete set of enterprise and development MCP servers
- **Based on**: Real production configuration (anonymized)

## 🚀 Quick Setup

### For Q CLI
```bash
# 1. Copy agent configuration
cp toolmux/examples/q-cli-agent-config.json ~/.aws/amazonq/cli-agents/my-toolmux-agent.json

# 2. Copy backend configuration  
cp toolmux/examples/q-cli-toolmux-config.json ~/my-toolmux-config.json

# 3. Edit agent config to reference your backend config
# Update paths and credentials as needed
```

### For Kiro IDE
```bash
# 1. Copy Kiro configuration
cp toolmux/examples/kiro-mcp-config.json .kiro/settings/mcp.json

# 2. Copy backend configuration
cp toolmux/examples/example_mcp.json ~/toolmux/mcp.json

# 3. Customize paths and credentials
```

### For General Use
```bash
# Copy main configuration
cp toolmux/examples/example_mcp.json ~/toolmux/mcp.json

# Edit paths and credentials
$EDITOR ~/toolmux/mcp.json
```

## 🔧 Example MCP Servers Included

All examples can be customized to include your preferred MCP servers:

- **`filesystem`**: Local filesystem access tools
- **`brave-search`**: Brave search integration
- **`github-mcp`**: GitHub repository tools
- **`url-to-markdown`**: Convert URLs to markdown
- **`outlook-mcp-server`**: Outlook for Mac integration

## 🎯 Customization Required

### 1. Update Paths
Replace anonymized paths with your actual paths:
```bash
# Replace user paths
sed -i 's|/Users/user/|/Users/yourusername/|g' ~/toolmux/mcp.json
```

### 2. Add Credentials
Update placeholder credentials:
- `your-api-token-here` → Your actual API token
- `user@example.com` → Your actual email address

### 3. Adjust Development Paths
Update paths to match your development setup:
- `/Users/user/dev/mcp/` → Your MCP development directory
- `/Users/user/projects/` → Your projects directory

### 4. Configure Server Status
Use the `disabled` flag to control which servers are active:
```json
{
  "server-name": {
    "command": "...",
    "disabled": true
  }
}
```

## ✅ Testing Your Configuration

### Test ToolMux Backend
```bash
# List configured servers
toolmux --config ~/toolmux/mcp.json --list-servers

# Test interactive mode
toolmux --config ~/toolmux/mcp.json
```

### Test Q CLI Integration
```bash
# Test agent with ToolMux
q --agent my-toolmux-agent "catalog_tools"

# Test tool discovery
q --agent my-toolmux-agent "get_tool_count"
```

### Test Kiro IDE Integration
1. Open Kiro IDE in your project
2. Check MCP server status in IDE settings
3. Verify ToolMux shows 4 meta-tools available
4. Test with: "catalog_tools" command

## 🆘 Troubleshooting

### Common Setup Issues
1. **Path Errors**: Ensure all `/Users/user/` paths are updated to your actual paths
2. **Permission Errors**: Make sure MCP server executables have proper permissions
3. **Timeout Issues**: Increase timeout values if servers are slow to start
4. **Missing Dependencies**: Install required tools (uvx, node, python environments)

### Server-Specific Requirements
- **Node.js servers**: Require Node.js runtime and built dist files
- **Python servers**: Require Python virtual environments and dependencies

### Configuration Validation
```bash
# Validate JSON syntax
python -m json.tool ~/toolmux/mcp.json

# Test server connectivity
toolmux --config ~/toolmux/mcp.json --list-servers
```

## 📚 Additional Resources

- **Main Documentation**: [README.md](../../README.md)
- **Agent Instructions**: [AGENT_INSTRUCTIONS.md](../../AGENT_INSTRUCTIONS.md)
- **Architecture Guide**: [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md)
- **Repository**: https://github.com/subnetangel/ToolMux

---

**Note**: These examples are based on real production configurations used with ToolMux v1.1.1. All sensitive information has been anonymized for security.