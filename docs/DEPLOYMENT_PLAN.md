# ToolMux Deployment Plan - UV/UVX Distribution

## Executive Summary

**Goal**: Enable users to install ToolMux with a single command: `uvx toolmux`

**Primary Strategy**: PyPI package distribution with UV/UVX support
**Timeline**: Ready for implementation
**User Experience**: Zero-friction installation with automatic configuration

## Recommended Implementation: PyPI + UVX

### Why This Approach

✅ **Frictionless User Experience**: `uvx toolmux` - one command, instant usage  
✅ **Professional Distribution**: PyPI is the expected channel for Python tools  
✅ **Automatic Dependency Management**: UV handles Python versions, isolation, dependencies  
✅ **Easy Updates**: `uvx toolmux@latest` for latest version  
✅ **Existing Infrastructure**: Current `pyproject.toml` is 90% ready  
✅ **Industry Standard**: Follows modern Python packaging best practices  

### Implementation Steps

#### Phase 1: Package Preparation
1. **Update `pyproject.toml`**:
   - Add console script entry point: `toolmux = "toolmux:main"`
   - Verify dependencies and version constraints
   - Ensure proper metadata (description, keywords, classifiers)

2. **Create Main Entry Point**:
   - Add `main()` function to `toolmux.py` or create `__main__.py`
   - Handle command-line argument parsing
   - Implement configuration discovery logic

3. **Configuration Management**:
   - First-run setup: auto-create `~/.config/toolmux/mcp.json`
   - Copy example configurations from package
   - Support environment variable: `TOOLMUX_CONFIG`
   - CLI flag: `--config` for custom paths

#### Phase 2: Build and Test
1. **Local Testing**:
   ```bash
   uv build
   uvx --from ./dist/toolmux-*.whl toolmux --help
   ```

2. **Git Installation Testing**:
   ```bash
   uvx --from git+https://github.com/jpruiz/toolmux toolmux
   ```

3. **Validation**:
   - Test on clean systems (Docker containers)
   - Verify configuration auto-creation
   - Test with various Python versions (3.10, 3.11, 3.12)

#### Phase 3: PyPI Publication
1. **PyPI Account Setup**:
   - Create PyPI account if needed
   - Generate API token for publishing
   - Configure UV with credentials

2. **Initial Release**:
   ```bash
   uv publish
   ```

3. **User Testing**:
   ```bash
   uvx toolmux
   ```

### Configuration Strategy

#### Simple, Visible Configuration
- **Primary**: `~/toolmux/mcp.json` (visible, easy to find)
- **Current Directory**: `./mcp.json` (project-specific configs)
- **CLI Override**: `--config path/to/config.json`

#### Configuration Discovery Order
1. `--config` CLI argument (explicit override)
2. `./mcp.json` (current directory - project-specific)
3. `~/toolmux/mcp.json` (user's main config)

#### First-Run Experience
```bash
$ uvx toolmux
ToolMux v1.1.0 - First run detected
✅ Created configuration directory: ~/toolmux/
✅ Installed example configuration: ~/toolmux/mcp.json
✅ Installed example configurations: ~/toolmux/examples/

📝 Edit ~/toolmux/mcp.json to add your MCP servers
📚 See ~/toolmux/examples/ for configuration templates
🚀 Run 'toolmux' to start with your configured servers
```

### Alternative Approaches (Fallback Options)

#### Option 2: Git Direct Install
- **Command**: `uvx --from git+https://github.com/jpruiz/toolmux toolmux`
- **Use Case**: Testing, pre-release versions, development
- **Benefits**: No PyPI dependency, can install from branches/tags

#### Option 3: GitHub Releases + Wheel
- **Command**: `uvx --from https://github.com/jpruiz/toolmux/releases/download/v1.1.0/toolmux-1.1.0-py3-none-any.whl toolmux`
- **Use Case**: Controlled distribution, enterprise environments
- **Benefits**: No PyPI dependency, version control

## Documentation-First Configuration

### Design Principles
1. **Visible Configuration**: `~/toolmux/mcp.json` not hidden in dotfiles
2. **Rich Examples**: Comprehensive example configurations included
3. **Clear Documentation**: Step-by-step instructions for common servers
4. **Copy-Paste Friendly**: Examples ready to copy into user config
5. **Validation**: Basic config validation with helpful error messages

### Bundled Examples Structure
```
~/toolmux/
├── mcp.json                    # User's main configuration
└── examples/
    ├── filesystem.json         # Filesystem server example
    ├── brave-search.json       # Web search example
    ├── sqlite.json            # Database example
    ├── mixed-servers.json      # stdio + HTTP mixed example
    ├── http-servers.json       # HTTP-only servers
    └── kiro-integration.json   # Kiro IDE integration
```

### Documentation Approach
- **README**: Clear "Adding Servers" section with copy-paste examples
- **Inline Comments**: JSON examples with explanatory comments
- **Error Messages**: Helpful validation errors pointing to documentation
- **Common Patterns**: Pre-built configs for popular use cases

## Technical Requirements

### pyproject.toml Updates Needed
```toml
[project.scripts]
toolmux = "toolmux:main"

[project.optional-dependencies]
dev = ["pytest", "black", "ruff", "mypy"]
```

### Entry Point Implementation
- Create `main()` function in `toolmux.py`
- Handle CLI argument parsing with `click` or `argparse`
- Implement configuration discovery and validation
- Add first-run setup logic
- **Add MCP server management commands** (critical for user experience)

### Package Structure
```
toolmux/
├── toolmux.py          # Main application with main() entry point
├── pyproject.toml      # Updated with console script entry
├── examples/           # Configuration examples (included in package)
│   ├── example_mcp.json
│   ├── mixed_servers.json
│   └── kiro_integration.json
├── README.md           # Updated with uvx installation instructions
└── DEPLOYMENT_PLAN.md  # This file
```

## Clear Configuration Management (User-Friendly Approach)

### Core Principle: Visible, Editable Configuration
Users edit `~/toolmux/mcp.json` directly with clear examples and documentation.

### Configuration Location
- **Main Config**: `~/toolmux/mcp.json` (visible, not hidden)
- **Examples**: `~/toolmux/examples/` (reference configurations)
- **Project-Specific**: `./mcp.json` (optional, for project contexts)

### User Experience Flow
```bash
# Day 1: Install
uvx toolmux                     # Creates ~/toolmux/mcp.json with examples

# Day 2: Configure
$EDITOR ~/toolmux/mcp.json      # Edit configuration directly
toolmux                         # Run with your servers

# Day 3: Add more servers
# Copy from ~/toolmux/examples/ or documentation
# Paste into ~/toolmux/mcp.json
```

### Example Configuration Structure
```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
    },
    "brave-search": {
      "command": "uvx",
      "args": ["mcp-server-brave-search"],
      "env": {"BRAVE_API_KEY": "your-key-here"}
    },
    "custom-http": {
      "transport": "http",
      "base_url": "https://api.example.com/mcp",
      "headers": {"Authorization": "Bearer your-token"}
    }
  }
}
```

## User Documentation Updates

### Installation Section (README.md)
```markdown
## Installation

### Quick Install (Recommended)
```bash
uvx toolmux
```

### First-Time Setup
```bash
# First run creates config and examples
toolmux

# Edit your configuration
$EDITOR ~/toolmux/mcp.json

# Run with your servers
toolmux
```

### Alternative Methods
```bash
# Install as persistent tool
uv tool install toolmux

# Install from git (development)
uvx --from git+https://github.com/jpruiz/toolmux toolmux

# Install specific version
uvx toolmux@1.1.0
```

### Getting Started
```bash
# First run creates configuration
uvx toolmux

# Edit your configuration
$EDITOR ~/.config/toolmux/mcp.json

# Run with custom config
uvx toolmux --config /path/to/custom.json
```

## Success Metrics

### User Experience Goals
- **Installation**: Single command (`uvx toolmux`)
- **Configuration**: Auto-created on first run
- **Updates**: Simple version management
- **Cross-platform**: Works on macOS, Linux, Windows

### Technical Goals
- **Package size**: < 1MB wheel
- **Cold start**: < 2 seconds first run
- **Dependencies**: Minimal, well-maintained packages
- **Python support**: 3.10, 3.11, 3.12

## Risk Mitigation

### Potential Issues
1. **PyPI name conflicts**: Check availability of `toolmux` name
2. **Dependency conflicts**: Pin versions appropriately
3. **Configuration complexity**: Provide clear examples
4. **Platform differences**: Test on all target platforms

### Mitigation Strategies
1. **Namespace**: Consider `@toolmux/toolmux` or similar if name taken
2. **Version pinning**: Use conservative version constraints
3. **Documentation**: Comprehensive examples and troubleshooting
4. **CI/CD**: Automated testing on multiple platforms

## Next Steps for Implementation

### Tomorrow's Tasks
1. **Review current `pyproject.toml`** - identify needed changes
2. **Create entry point function** - implement `main()` in `toolmux.py`
3. **Add configuration discovery** - implement `~/toolmux/mcp.json` support
4. **Create comprehensive examples** - bundle example configs for popular servers
5. **Add config validation** - helpful error messages for invalid configs
6. **Test local build** - `uv build` and local testing
7. **Update documentation** - README with clear "Adding Servers" section

### Week 1 Goals
- [ ] Complete package preparation with simple config management
- [ ] Create comprehensive example configurations
- [ ] Write clear "Adding Servers" documentation
- [ ] Local testing and validation
- [ ] Git installation testing
- [ ] Documentation updates with copy-paste examples

### Week 2 Goals
- [ ] PyPI account setup
- [ ] Initial PyPI release
- [ ] User testing and feedback
- [ ] Iteration based on feedback

## Conclusion

The PyPI + UVX approach provides the best balance of user experience, maintainability, and professional distribution. With ToolMux's existing structure, implementation should be straightforward and can be completed within 1-2 weeks.

The key success factor is maintaining the "one command installation" goal while providing flexible configuration options for power users.