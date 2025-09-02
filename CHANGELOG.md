# ToolMux Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.3] - 2025-09-01

### Fixed
- **Version Consistency**: Fixed version string inconsistency where package was 1.1.2 but binary reported 1.1.1
- **Runtime Version**: All version strings now correctly report 1.1.3 in both package metadata and binary output

### Changed
- **Repository URLs**: Updated all GitHub repository references to `subnetangel/ToolMux`
- **Project URLs**: Updated PyPI project URLs to point to correct GitHub repository
- **Documentation**: Updated installation instructions and documentation links

### Technical Details
- Updated `pyproject.toml` project URLs (Homepage, Repository, Issues)
- Updated README.md installation commands for Git-based installation
- Updated help text in CLI to reference correct repository
- Updated all documentation files with correct GitHub URLs
- Synchronized version strings between pyproject.toml and source code

## [1.1.1] - 2025-09-01

### Fixed
- **Empty Input Handling**: Fixed issue where ToolMux would generate error messages for empty lines when run interactively
- **Interactive Mode UX**: Added helpful messages when ToolMux starts in interactive mode to guide users

### Changed
- Empty lines are now silently ignored instead of generating JSON parsing errors
- Interactive mode now displays helpful tips about CLI commands and usage

### Technical Details
- Modified `run()` method in `main.py` to skip empty lines before JSON parsing
- Added terminal detection (`sys.stdin.isatty()`) to show helpful messages only in interactive mode
- Messages are sent to stderr to avoid interfering with MCP protocol on stdout

### User Impact
- **Before**: Running `uvx toolmux` and pressing Enter would show repeated error messages
- **After**: Running `uvx toolmux` shows helpful guidance and ignores empty input gracefully

## [1.1.0] - 2025-09-01

### Added
- **PyPI Publication**: ToolMux is now available on PyPI as `toolmux`
- **UVX Support**: Install and run with `uvx toolmux`
- **First-Run Setup**: Automatic configuration creation on first run
- **Example Configurations**: 9 bundled example configurations
- **CLI Commands**: `--version`, `--help`, `--list-servers`

### Features
- **Token Efficiency**: 98.65% token reduction (4 meta-tools vs individual tools)
- **MCP Protocol**: Full MCP 2024-11-05 compliance
- **Meta-Tools**: `catalog_tools`, `get_tool_schema`, `invoke`, `get_tool_count`
- **Server Aggregation**: Combine multiple MCP servers into single interface

### Configuration
- **Auto-Setup**: Creates `~/toolmux/mcp.json` and examples on first run
- **Default Servers**: Includes filesystem and brave-search server configurations
- **Flexible Config**: Support for custom configuration files

## [1.0.0] - 2025-08-31

### Added
- Initial release of ToolMux
- MCP server aggregation functionality
- HTTP/SSE transport support
- Stdio MCP server support
- Basic CLI interface

### Features
- Server multiplexing and tool aggregation
- On-demand server loading
- Mixed transport support (stdio + HTTP)
- JSON-RPC protocol compliance

---

## Version History Summary

- **1.1.3**: Version consistency fixes and GitHub repository URL updates
- **1.1.1**: Bug fixes for empty input handling and improved UX
- **1.1.0**: PyPI publication with first-run setup and CLI improvements  
- **1.0.0**: Initial release with core MCP aggregation functionality
