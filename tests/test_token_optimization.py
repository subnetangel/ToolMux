"""Token optimization benchmarks for ToolMux v2.0 operating modes.

Measures token savings by comparing raw backend tool schemas against
each mode's condensed output. Uses tiktoken-compatible word estimation
(1 token ≈ 0.75 words ≈ 4 chars).
"""
import json
import pytest
from toolmux.main import (
    condense_description, condense_schema, resolve_collisions,
    build_gateway_description, build_gateway_instructions,
    BackendManager,
)
from conftest import tool_dict


def estimate_tokens(text: str) -> int:
    """Estimate token count (1 token ≈ 4 chars)."""
    return max(1, len(text) // 4)


# ─── Realistic tool definitions for benchmarking ───

REALISTIC_TOOLS = [
    {
        "name": "read_file",
        "description": "Read the complete contents of a file from the file system. Handles various text encodings and provides detailed error messages if the file cannot be read. Use this tool when you need to examine the contents of an existing file. Only works within allowed directories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to the file to read"},
                "encoding": {"type": "string", "description": "Text encoding to use", "default": "utf-8", "enum": ["utf-8", "ascii", "latin-1"]},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "_server": "filesystem", "_transport": "stdio",
    },
    {
        "name": "write_file",
        "description": "Create a new file or completely overwrite an existing file with new content. Use this tool when you need to write text content to a file. If the file exists, it will be overwritten. If it doesn't exist, it will be created. Only works within allowed directories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to the file to write"},
                "content": {"type": "string", "description": "The complete content to write to the file"},
                "encoding": {"type": "string", "description": "Text encoding", "default": "utf-8"},
                "create_dirs": {"type": "boolean", "description": "Create parent directories if they don't exist", "default": False},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        "_server": "filesystem", "_transport": "stdio",
    },
    {
        "name": "list_directory",
        "description": "List all files and directories in a given directory path. Returns a detailed listing with file types, sizes, and modification times. Use this tool to explore directory contents before reading or writing files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"},
                "recursive": {"type": "boolean", "description": "List recursively", "default": False},
                "include_hidden": {"type": "boolean", "description": "Include hidden files", "default": False},
                "max_depth": {"type": "integer", "description": "Maximum recursion depth", "minimum": 1, "maximum": 10},
            },
            "required": ["path"],
        },
        "_server": "filesystem", "_transport": "stdio",
    },
    {
        "name": "search_files",
        "description": "Search for files matching a pattern within a directory tree. Supports glob patterns and regular expressions. Returns matching file paths with optional content preview.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Root directory to search from"},
                "pattern": {"type": "string", "description": "Search pattern (glob or regex)"},
                "regex": {"type": "boolean", "description": "Treat pattern as regex", "default": False},
                "max_results": {"type": "integer", "description": "Maximum results to return", "default": 100},
            },
            "required": ["path", "pattern"],
        },
        "_server": "filesystem", "_transport": "stdio",
    },
    {
        "name": "get_file_info",
        "description": "Get detailed metadata about a file including size, permissions, modification time, and MIME type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
            },
            "required": ["path"],
        },
        "_server": "filesystem", "_transport": "stdio",
    },
    {
        "name": "git_status",
        "description": "Show the working tree status including staged, unstaged, and untracked files. Provides a summary of changes in the current repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to the git repository"},
                "short": {"type": "boolean", "description": "Use short format", "default": False},
            },
            "required": ["repo_path"],
        },
        "_server": "git", "_transport": "stdio",
    },
    {
        "name": "git_log",
        "description": "Show commit history for the repository. Returns commit hashes, authors, dates, and messages. Supports filtering by date range, author, and path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to the git repository"},
                "max_count": {"type": "integer", "description": "Maximum commits to show", "default": 10},
                "author": {"type": "string", "description": "Filter by author name or email"},
                "since": {"type": "string", "description": "Show commits after date (ISO 8601)"},
                "until": {"type": "string", "description": "Show commits before date (ISO 8601)"},
                "path": {"type": "string", "description": "Filter by file path"},
            },
            "required": ["repo_path"],
        },
        "_server": "git", "_transport": "stdio",
    },
    {
        "name": "git_diff",
        "description": "Show changes between commits, commit and working tree, etc. Returns unified diff format output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to the git repository"},
                "staged": {"type": "boolean", "description": "Show staged changes", "default": False},
                "commit": {"type": "string", "description": "Compare against specific commit"},
            },
            "required": ["repo_path"],
        },
        "_server": "git", "_transport": "stdio",
    },
]


def raw_tools_tokens(tools):
    """Calculate tokens for raw tool schemas (no condensation)."""
    total = 0
    for t in tools:
        entry = {"name": t["name"], "description": t["description"],
                 "inputSchema": t["inputSchema"]}
        total += estimate_tokens(json.dumps(entry))
    return total


class TestTokenOptimization:
    """Benchmark token savings for each operating mode."""

    def test_meta_mode_token_savings(self):
        """Meta mode: 4 meta-tools + instructions vs raw tools."""
        raw = raw_tools_tokens(REALISTIC_TOOLS)

        # Meta mode exposes 4 fixed tools + instructions
        meta_tools = [
            {"name": "catalog_tools", "description": "List all available tools from backend MCP servers",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "get_tool_schema", "description": "Get full description and inputSchema for a specific tool",
             "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
            {"name": "invoke", "description": "Execute a backend tool by name",
             "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "args": {"type": "object"}}, "required": ["name"]}},
            {"name": "get_tool_count", "description": "Get count of available tools by server",
             "inputSchema": {"type": "object", "properties": {}}},
        ]
        meta_tokens = raw_tools_tokens(meta_tools)
        from toolmux.main import INSTRUCTIONS_META_TEMPLATE
        meta_tokens += estimate_tokens(INSTRUCTIONS_META_TEMPLATE.format(optimization_hint=""))

        savings = (1 - meta_tokens / raw) * 100
        print(f"\n{'='*60}")
        print(f"META MODE TOKEN ANALYSIS")
        print(f"{'='*60}")
        print(f"  Raw tools tokens:    {raw:>6}")
        print(f"  Meta mode tokens:    {meta_tokens:>6}")
        print(f"  Token savings:       {savings:>5.1f}%")
        print(f"  Target range:        93-99%")
        assert savings > 50, f"Meta mode savings {savings:.1f}% below minimum"

    def test_proxy_mode_token_savings(self):
        """Proxy mode: condensed descriptions + condensed schemas."""
        raw = raw_tools_tokens(REALISTIC_TOOLS)

        proxy_tokens = 0
        for t in REALISTIC_TOOLS:
            desc = condense_description(t["description"])
            schema = condense_schema(t["inputSchema"])
            entry = {"name": t["name"], "description": desc, "inputSchema": schema}
            proxy_tokens += estimate_tokens(json.dumps(entry))
        # Add get_tool_schema helper
        proxy_tokens += estimate_tokens(json.dumps({
            "name": "get_tool_schema", "description": "Get full parameter details",
            "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}))
        from toolmux.main import INSTRUCTIONS_PROXY_TEMPLATE
        proxy_tokens += estimate_tokens(INSTRUCTIONS_PROXY_TEMPLATE.format(optimization_hint=""))

        savings = (1 - proxy_tokens / raw) * 100
        print(f"\n{'='*60}")
        print(f"PROXY MODE TOKEN ANALYSIS")
        print(f"{'='*60}")
        print(f"  Raw tools tokens:    {raw:>6}")
        print(f"  Proxy mode tokens:   {proxy_tokens:>6}")
        print(f"  Token savings:       {savings:>5.1f}%")
        print(f"  Target range:        55-75%")
        assert savings > 30, f"Proxy mode savings {savings:.1f}% below minimum"

    def test_gateway_mode_token_savings(self):
        """Gateway mode: server-grouped tools with rich descriptions."""
        raw = raw_tools_tokens(REALISTIC_TOOLS)

        # Group by server
        servers = {}
        for t in REALISTIC_TOOLS:
            servers.setdefault(t["_server"], []).append(t)

        gateway_tokens = 0
        for server_name, tools in servers.items():
            desc = build_gateway_description(tools)
            entry = {"name": server_name, "description": desc,
                     "inputSchema": {"type": "object", "properties": {
                         "tool": {"type": "string"}, "arguments": {"type": "object"}},
                         "required": ["tool"]}}
            gateway_tokens += estimate_tokens(json.dumps(entry))

        # Native tools
        for native in [
            {"name": "get_tool_schema", "description": "Get full parameter details",
             "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
            {"name": "get_tool_count", "description": "Get tool count by server",
             "inputSchema": {"type": "object", "properties": {}}},
        ]:
            gateway_tokens += estimate_tokens(json.dumps(native))

        # Instructions
        counts = {s: len(t) for s, t in servers.items()}
        instructions = build_gateway_instructions(counts)
        gateway_tokens += estimate_tokens(instructions)

        savings = (1 - gateway_tokens / raw) * 100
        print(f"\n{'='*60}")
        print(f"GATEWAY MODE TOKEN ANALYSIS")
        print(f"{'='*60}")
        print(f"  Raw tools tokens:    {raw:>6}")
        print(f"  Gateway mode tokens: {gateway_tokens:>6}")
        print(f"  Token savings:       {savings:>5.1f}%")
        print(f"  Target range:        85-93%")
        assert savings > 30, f"Gateway mode savings {savings:.1f}% below minimum"

    def test_condensation_quality(self):
        """Verify condensation produces meaningful output."""
        print(f"\n{'='*60}")
        print(f"CONDENSATION QUALITY SAMPLES")
        print(f"{'='*60}")
        for t in REALISTIC_TOOLS:
            original = t["description"]
            condensed = condense_description(original)
            orig_tokens = estimate_tokens(original)
            cond_tokens = estimate_tokens(condensed)
            savings = (1 - cond_tokens / orig_tokens) * 100 if orig_tokens else 0
            print(f"  {t['name']:20s}: {condensed:50s} ({savings:4.0f}% saved)")
            # Condensed should be non-empty and shorter
            assert len(condensed) > 0
            assert len(condensed) <= len(original)

    def test_schema_condensation_quality(self):
        """Verify schema condensation removes verbose fields."""
        print(f"\n{'='*60}")
        print(f"SCHEMA CONDENSATION SAMPLES")
        print(f"{'='*60}")
        for t in REALISTIC_TOOLS:
            original = t["inputSchema"]
            condensed = condense_schema(original)
            orig_tokens = estimate_tokens(json.dumps(original))
            cond_tokens = estimate_tokens(json.dumps(condensed))
            savings = (1 - cond_tokens / orig_tokens) * 100 if orig_tokens else 0
            print(f"  {t['name']:20s}: {orig_tokens:>4} → {cond_tokens:>4} tokens ({savings:4.0f}% saved)")
            # Properties preserved
            assert set(condensed.get("properties", {}).keys()) == set(original.get("properties", {}).keys())

    def test_mode_comparison_summary(self):
        """Print a comparison table of all modes."""
        raw = raw_tools_tokens(REALISTIC_TOOLS)

        # Meta
        from toolmux.main import INSTRUCTIONS_META_TEMPLATE, INSTRUCTIONS_PROXY_TEMPLATE
        meta_tools_json = json.dumps([
            {"name": "catalog_tools", "inputSchema": {"type": "object"}},
            {"name": "get_tool_schema", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}}},
            {"name": "invoke", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "args": {"type": "object"}}}},
            {"name": "get_tool_count", "inputSchema": {"type": "object"}},
        ])
        meta = estimate_tokens(meta_tools_json) + estimate_tokens(INSTRUCTIONS_META_TEMPLATE.format(optimization_hint=""))

        # Proxy
        proxy = sum(estimate_tokens(json.dumps({
            "name": t["name"],
            "description": condense_description(t["description"]),
            "inputSchema": condense_schema(t["inputSchema"]),
        })) for t in REALISTIC_TOOLS) + estimate_tokens(INSTRUCTIONS_PROXY_TEMPLATE.format(optimization_hint=""))

        # Gateway
        servers = {}
        for t in REALISTIC_TOOLS:
            servers.setdefault(t["_server"], []).append(t)
        gateway = sum(estimate_tokens(json.dumps({
            "name": s, "description": build_gateway_description(tools),
        })) for s, tools in servers.items())
        gateway += estimate_tokens(build_gateway_instructions({s: len(t) for s, t in servers.items()}))

        print(f"\n{'='*60}")
        print(f"MODE COMPARISON ({len(REALISTIC_TOOLS)} tools, {len(servers)} servers)")
        print(f"{'='*60}")
        print(f"  {'Mode':<12} {'Tokens':>8} {'Savings':>10} {'Target':>12}")
        print(f"  {'-'*44}")
        print(f"  {'Raw':12} {raw:>8}")
        print(f"  {'Meta':12} {meta:>8} {(1-meta/raw)*100:>9.1f}% {'93-99%':>12}")
        print(f"  {'Gateway':12} {gateway:>8} {(1-gateway/raw)*100:>9.1f}% {'85-93%':>12}")
        print(f"  {'Proxy':12} {proxy:>8} {(1-proxy/raw)*100:>9.1f}% {'55-75%':>12}")
