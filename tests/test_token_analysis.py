#!/usr/bin/env python3
"""
Token analysis: Compare different tool exposure strategies for ToolMux.
Measures approximate token counts for tools/list responses under different modes.
"""
import json
import sys

# Simulate a realistic set of backend tools (from filesystem + search + git MCPs)
SAMPLE_BACKEND_TOOLS = [
    {
        "name": "read_file",
        "description": "Read the complete contents of a file from the file system. Handles various text encodings and provides detailed error messages if the file cannot be read. Use this tool when you need to examine the contents of a single file. Only works within allowed directories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute or relative path to the file to read. Must be within allowed directories."
                }
            },
            "required": ["path"],
            "additionalProperties": False
        },
        "_server": "filesystem"
    },
    {
        "name": "write_file",
        "description": "Create a new file or completely overwrite an existing file with new content. Use with caution as it will overwrite existing files without warning. Creates parent directories as needed. Only works within allowed directories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path where the file should be written"
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file"
                }
            },
            "required": ["path", "content"],
            "additionalProperties": False
        },
        "_server": "filesystem"
    },
    {
        "name": "edit_file",
        "description": "Make line-based edits to a text file. Each edit replaces exact line sequences with new content. Returns the file content after all edits are applied. Only works within allowed directories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to the file to edit"
                },
                "edits": {
                    "type": "array",
                    "description": "Array of edit operations to apply",
                    "items": {
                        "type": "object",
                        "properties": {
                            "oldText": {"type": "string", "description": "The exact text to search for"},
                            "newText": {"type": "string", "description": "The text to replace it with"}
                        },
                        "required": ["oldText", "newText"]
                    }
                },
                "dryRun": {
                    "type": "boolean",
                    "description": "If true, show preview without making changes",
                    "default": False
                }
            },
            "required": ["path", "edits"],
            "additionalProperties": False
        },
        "_server": "filesystem"
    },
    {
        "name": "create_directory",
        "description": "Create a new directory or ensure a directory exists. Can create multiple nested directories in one operation. If the directory already exists, this operation will succeed silently. Only works within allowed directories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path of the directory to create"
                }
            },
            "required": ["path"],
            "additionalProperties": False
        },
        "_server": "filesystem"
    },
    {
        "name": "list_directory",
        "description": "Get a detailed listing of all files and directories in a specified path. Results clearly distinguish between files and directories with [FILE] and [DIR] prefixes. Only works within allowed directories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path of the directory to list"
                }
            },
            "required": ["path"],
            "additionalProperties": False
        },
        "_server": "filesystem"
    },
    {
        "name": "move_file",
        "description": "Move or rename files and directories. Can move files between directories and rename them in a single operation. If the destination exists, the operation will fail. Both source and destination must be within allowed directories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source path of the file or directory"
                },
                "destination": {
                    "type": "string",
                    "description": "Destination path"
                }
            },
            "required": ["source", "destination"],
            "additionalProperties": False
        },
        "_server": "filesystem"
    },
    {
        "name": "search_files",
        "description": "Recursively search for files and directories matching a pattern. Searches through all subdirectories from the starting path. The search is case-insensitive and matches partial names. Returns full paths of all matching items.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The starting directory for the search"
                },
                "pattern": {
                    "type": "string",
                    "description": "The search pattern to match against file/directory names"
                },
                "excludePatterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns to exclude from search results"
                }
            },
            "required": ["path", "pattern"],
            "additionalProperties": False
        },
        "_server": "filesystem"
    },
    {
        "name": "get_file_info",
        "description": "Retrieve detailed metadata about a file or directory. Returns comprehensive information including size, creation time, last modified time, permissions, and type. Only works within allowed directories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path to get information about"
                }
            },
            "required": ["path"],
            "additionalProperties": False
        },
        "_server": "filesystem"
    },
    {
        "name": "read_multiple_files",
        "description": "Read the contents of multiple files simultaneously. This is more efficient than reading files one by one when you need to analyze or compare multiple files. Each file's content is returned with its path as a reference.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of file paths to read"
                }
            },
            "required": ["paths"],
            "additionalProperties": False
        },
        "_server": "filesystem"
    },
    {
        "name": "list_allowed_directories",
        "description": "Returns the list of directories that this server is allowed to access. Use this to understand which directories are available before trying to read or write files.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False
        },
        "_server": "filesystem"
    },
    # Simulate a brave-search MCP
    {
        "name": "brave_web_search",
        "description": "Performs a web search using the Brave Search API, ideal for general queries, news, articles, and online content. Use this for broad information gathering, recent events, or when you need diverse web sources. Supports pagination, content filtering, and freshness parameters. Maximum 20 results per request.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (max 400 chars, 50 words)"
                },
                "count": {
                    "type": "integer",
                    "description": "Number of results (1-20, default 10)",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 20
                },
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset (max 9, default 0)",
                    "default": 0
                },
                "freshness": {
                    "type": "string",
                    "description": "Filter by content age",
                    "enum": ["pd", "pw", "pm", "py"]
                }
            },
            "required": ["query"],
            "additionalProperties": False
        },
        "_server": "brave-search"
    },
    {
        "name": "brave_local_search",
        "description": "Searches for local businesses and places using Brave's Local Search API. Best for queries related to physical locations, businesses, restaurants, services, etc. Returns detailed information including business hours, ratings, and contact details when available.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Local search query (e.g., 'pizza near me', 'dentist in San Francisco')"
                },
                "count": {
                    "type": "integer",
                    "description": "Number of results (1-20, default 5)",
                    "default": 5
                }
            },
            "required": ["query"],
            "additionalProperties": False
        },
        "_server": "brave-search"
    },
    # Simulate a git MCP
    {
        "name": "git_status",
        "description": "Shows the working tree status. Displays paths that have differences between the index file and the current HEAD commit, paths that have differences between the working tree and the index file, and paths in the working tree that are not tracked by Git.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the Git repository"
                }
            },
            "required": ["repo_path"],
            "additionalProperties": False
        },
        "_server": "git"
    },
    {
        "name": "git_log",
        "description": "Shows the commit logs. Displays commit history with various formatting options. Supports filtering by date, author, and path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the Git repository"
                },
                "max_count": {
                    "type": "integer",
                    "description": "Maximum number of commits to show",
                    "default": 10
                },
                "author": {
                    "type": "string",
                    "description": "Filter commits by author"
                },
                "since": {
                    "type": "string",
                    "description": "Show commits after date"
                },
                "until": {
                    "type": "string",
                    "description": "Show commits before date"
                },
                "path": {
                    "type": "string",
                    "description": "Filter commits affecting this path"
                }
            },
            "required": ["repo_path"],
            "additionalProperties": False
        },
        "_server": "git"
    },
    {
        "name": "git_diff",
        "description": "Show changes between commits, commit and working tree, etc. Shows the differences in file content between various states of a Git repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the Git repository"
                },
                "target": {
                    "type": "string",
                    "description": "Target to diff against (commit, branch, etc.)"
                },
                "cached": {
                    "type": "boolean",
                    "description": "Show staged changes",
                    "default": False
                }
            },
            "required": ["repo_path"],
            "additionalProperties": False
        },
        "_server": "git"
    },
    {
        "name": "git_commit",
        "description": "Record changes to the repository. Creates a new commit containing the current contents of the index and the given log message describing the changes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the Git repository"
                },
                "message": {
                    "type": "string",
                    "description": "Commit message"
                }
            },
            "required": ["repo_path", "message"],
            "additionalProperties": False
        },
        "_server": "git"
    },
    {
        "name": "git_add",
        "description": "Add file contents to the staging area (index). Updates the index using the current content found in the working tree to prepare the content staged for the next commit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the Git repository"
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files to add to staging area"
                }
            },
            "required": ["repo_path", "files"],
            "additionalProperties": False
        },
        "_server": "git"
    },
    {
        "name": "git_branch",
        "description": "List, create, or delete branches. If no arguments are given, existing branches are listed. With a branch name argument, a new branch is created.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the Git repository"
                },
                "branch_name": {
                    "type": "string",
                    "description": "Name of branch to create"
                },
                "delete": {
                    "type": "boolean",
                    "description": "Delete the branch",
                    "default": False
                }
            },
            "required": ["repo_path"],
            "additionalProperties": False
        },
        "_server": "git"
    },
    {
        "name": "git_checkout",
        "description": "Switch branches or restore working tree files. Updates files in the working tree to match the version in the index or the specified tree.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the Git repository"
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to switch to"
                },
                "create": {
                    "type": "boolean",
                    "description": "Create new branch and switch to it",
                    "default": False
                }
            },
            "required": ["repo_path", "branch"],
            "additionalProperties": False
        },
        "_server": "git"
    },
]


def approx_token_count(text: str) -> int:
    """Rough token estimation: ~4 chars per token for English/JSON."""
    return len(text) // 4


def strip_internal_keys(tool: dict) -> dict:
    """Remove internal metadata keys."""
    return {k: v for k, v in tool.items() if not k.startswith("_")}


def build_current_meta_tools():
    """Current ToolMux: 4 meta-tools only."""
    return [
        {
            "name": "catalog_tools",
            "description": "List all available tools from backend MCP servers",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "get_tool_schema",
            "description": "Get schema for a specific tool",
            "inputSchema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"]
            }
        },
        {
            "name": "invoke",
            "description": "Execute a backend tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "args": {"type": "object"}
                },
                "required": ["name"]
            }
        },
        {
            "name": "get_tool_count",
            "description": "Get count of available tools by server",
            "inputSchema": {"type": "object", "properties": {}}
        }
    ]


def build_full_passthrough(tools):
    """Full passthrough: all tools with original schemas."""
    return [strip_internal_keys(t) for t in tools]


def condense_tool_minimal(tool: dict) -> dict:
    """Condensed: required params only, no descriptions, short tool description."""
    schema = tool.get("inputSchema", {})
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    condensed_props = {}
    for prop_name in required:
        if prop_name in properties:
            prop_type = properties[prop_name].get("type", "string")
            condensed_props[prop_name] = {"type": prop_type}

    desc = tool.get("description", "")
    # First sentence, max 60 chars
    short_desc = desc.split(".")[0][:60]
    server = tool.get("_server", "unknown")

    result = {
        "name": tool["name"],
        "description": f"{short_desc} [{server}]",
        "inputSchema": {"type": "object"}
    }
    if condensed_props:
        result["inputSchema"]["properties"] = condensed_props
    if required:
        result["inputSchema"]["required"] = required

    return result


def condense_tool_ultra(tool: dict) -> dict:
    """Ultra-condensed: name + very short desc + empty schema."""
    desc = tool.get("description", "")
    short_desc = desc.split(".")[0][:40]
    server = tool.get("_server", "unknown")

    return {
        "name": tool["name"],
        "description": f"{short_desc} [{server}]",
        "inputSchema": {"type": "object"}
    }


def build_condensed_proxy(tools):
    """Condensed proxy: real tools with minimal schemas + get_tool_schema helper."""
    condensed = [condense_tool_minimal(t) for t in tools]
    condensed.append({
        "name": "get_tool_schema",
        "description": "Get full parameter schema for any tool when you need detailed parameter info",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"]
        }
    })
    return condensed


def build_ultra_condensed_proxy(tools):
    """Ultra-condensed: name + short desc + empty schema."""
    condensed = [condense_tool_ultra(t) for t in tools]
    condensed.append({
        "name": "get_tool_schema",
        "description": "Get full parameter schema for any tool when you need detailed parameter info",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"]
        }
    })
    return condensed


def build_hybrid_grouped(tools):
    """Hybrid: group tools by server into single tools with sub-tool enum."""
    servers = {}
    for tool in tools:
        server = tool.get("_server", "unknown")
        if server not in servers:
            servers[server] = []
        servers[server].append(tool["name"])

    grouped = []
    for server_name, tool_names in servers.items():
        tools_list = ", ".join(tool_names)
        grouped.append({
            "name": server_name,
            "description": f"Tools: {tools_list}",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "enum": tool_names},
                    "arguments": {"type": "object"}
                },
                "required": ["tool"]
            }
        })

    grouped.append({
        "name": "get_tool_schema",
        "description": "Get full parameter schema for any tool",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"]
        }
    })
    return grouped


def build_enhanced_meta_tools(tools):
    """Enhanced meta-tools: current 4 tools but with dynamic descriptions."""
    tool_names = [t["name"] for t in tools]
    tools_summary = ", ".join(tool_names)

    # Build param hints for invoke description
    param_hints = []
    for t in tools:
        required = t.get("inputSchema", {}).get("required", [])
        if required:
            param_hints.append(f"{t['name']}({', '.join(required)})")
        else:
            param_hints.append(f"{t['name']}()")
    invoke_hints = "; ".join(param_hints)

    return [
        {
            "name": "catalog_tools",
            "description": f"List all available tools with descriptions and parameter info. Available tools: {tools_summary}",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "get_tool_schema",
            "description": "Get the full input parameter schema for a specific tool. Use when you need to know exact parameter names, types, and requirements.",
            "inputSchema": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Tool name"}},
                "required": ["name"]
            }
        },
        {
            "name": "invoke",
            "description": f"Execute any tool by name with arguments. Tool signatures: {invoke_hints}",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": tool_names,
                             "description": "Tool name to execute"},
                    "args": {"type": "object",
                             "description": "Tool arguments as key-value pairs"}
                },
                "required": ["name"]
            }
        },
        {
            "name": "get_tool_count",
            "description": "Get count of available tools grouped by server",
            "inputSchema": {"type": "object", "properties": {}}
        }
    ]


def analyze_approach(name, tools_list):
    """Analyze token cost of a tools/list response."""
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": tools_list}
    }
    json_str = json.dumps(response, indent=2)
    json_compact = json.dumps(response, separators=(",", ":"))
    tokens_pretty = approx_token_count(json_str)
    tokens_compact = approx_token_count(json_compact)
    return {
        "name": name,
        "tool_count": len(tools_list),
        "json_chars_pretty": len(json_str),
        "json_chars_compact": len(json_compact),
        "approx_tokens_pretty": tokens_pretty,
        "approx_tokens_compact": tokens_compact,
    }


def main():
    tools = SAMPLE_BACKEND_TOOLS
    print(f"Sample backend tools: {len(tools)} tools from "
          f"{len(set(t['_server'] for t in tools))} servers")
    print(f"Servers: {', '.join(sorted(set(t['_server'] for t in tools)))}")
    print("=" * 80)

    approaches = [
        ("1. Full Passthrough (no optimization)", build_full_passthrough(tools)),
        ("2. Current Meta-Tools (4 tools)", build_current_meta_tools()),
        ("3. Condensed Proxy (real tools, minimal schema)", build_condensed_proxy(tools)),
        ("4. Ultra-Condensed Proxy (real tools, empty schema)", build_ultra_condensed_proxy(tools)),
        ("5. Hybrid Grouped (per-server tools)", build_hybrid_grouped(tools)),
        ("6. Enhanced Meta-Tools (dynamic descriptions)", build_enhanced_meta_tools(tools)),
    ]

    results = []
    baseline = None

    for name, tool_list in approaches:
        result = analyze_approach(name, tool_list)
        results.append(result)
        if baseline is None:
            baseline = result

    print(f"\n{'Approach':<55} {'Tools':>5} {'Chars':>7} {'~Tokens':>8} {'Savings':>8}")
    print("-" * 90)

    for r in results:
        savings = (1 - r["approx_tokens_compact"] / baseline["approx_tokens_compact"]) * 100
        print(f"{r['name']:<55} {r['tool_count']:>5} "
              f"{r['json_chars_compact']:>7} {r['approx_tokens_compact']:>8} "
              f"{savings:>7.1f}%")

    # Show sample condensed tool
    print("\n" + "=" * 80)
    print("SAMPLE: Full vs Condensed tool comparison")
    print("=" * 80)

    sample = tools[0]
    print(f"\nFULL ({approx_token_count(json.dumps(strip_internal_keys(sample)))} tokens):")
    print(json.dumps(strip_internal_keys(sample), indent=2)[:500])

    condensed = condense_tool_minimal(sample)
    print(f"\nCONDENSED ({approx_token_count(json.dumps(condensed))} tokens):")
    print(json.dumps(condensed, indent=2))

    ultra = condense_tool_ultra(sample)
    print(f"\nULTRA-CONDENSED ({approx_token_count(json.dumps(ultra))} tokens):")
    print(json.dumps(ultra, indent=2))

    # Show enhanced meta invoke description
    print("\n" + "=" * 80)
    print("SAMPLE: Enhanced Meta-Tools invoke description")
    print("=" * 80)
    enhanced = build_enhanced_meta_tools(tools)
    invoke_tool = [t for t in enhanced if t["name"] == "invoke"][0]
    print(f"\n({approx_token_count(json.dumps(invoke_tool))} tokens):")
    print(json.dumps(invoke_tool, indent=2))

    # Scale analysis
    print("\n" + "=" * 80)
    print("SCALE ANALYSIS: Projected savings at different tool counts")
    print("=" * 80)

    # Generate scaled tool sets
    for scale in [20, 50, 100, 200]:
        scaled_tools = []
        for i in range(scale):
            base = tools[i % len(tools)].copy()
            base["name"] = f"tool_{i}_{base['name']}"
            base["_server"] = f"server_{i // 10}"
            scaled_tools.append(base)

        full = analyze_approach("full", build_full_passthrough(scaled_tools))
        meta = analyze_approach("meta", build_current_meta_tools())
        condensed = analyze_approach("condensed", build_condensed_proxy(scaled_tools))
        ultra = analyze_approach("ultra", build_ultra_condensed_proxy(scaled_tools))
        hybrid = analyze_approach("hybrid", build_hybrid_grouped(scaled_tools))
        enhanced = analyze_approach("enhanced", build_enhanced_meta_tools(scaled_tools))

        print(f"\n--- {scale} tools ---")
        for label, r in [("Full", full), ("Meta (current)", meta),
                         ("Condensed", condensed), ("Ultra-condensed", ultra),
                         ("Hybrid grouped", hybrid), ("Enhanced meta", enhanced)]:
            savings = (1 - r["approx_tokens_compact"] / full["approx_tokens_compact"]) * 100
            print(f"  {label:<25} {r['approx_tokens_compact']:>6} tokens  "
                  f"({savings:>5.1f}% savings)")


if __name__ == "__main__":
    main()
