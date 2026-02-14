#!/usr/bin/env python3
"""
Token analysis v2: Progressive Disclosure architecture for ToolMux.

Compares the TOTAL token cost across an entire session, not just tools/list.
Measures: discovery cost (tools/list) + operational cost (invocation enrichment).

Key new concepts:
- Smart description condensation (not dumb truncation)
- Schema condensation (required params with types, drop verbose extras)
- First-invocation docstring enrichment (full description on first call per tool)
- Total session cost = discovery + operational
"""
import json
import re
import sys

# ============================================================================
# REALISTIC BACKEND TOOLS (filesystem + search + git MCPs)
# ============================================================================
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
                "path": {"type": "string", "description": "The path where the file should be written"},
                "content": {"type": "string", "description": "The content to write to the file"}
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
                "path": {"type": "string", "description": "The path to the file to edit"},
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
                "dryRun": {"type": "boolean", "description": "If true, show preview without making changes", "default": False}
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
            "properties": {"path": {"type": "string", "description": "The path of the directory to create"}},
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
            "properties": {"path": {"type": "string", "description": "The path of the directory to list"}},
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
                "source": {"type": "string", "description": "Source path of the file or directory"},
                "destination": {"type": "string", "description": "Destination path"}
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
                "path": {"type": "string", "description": "The starting directory for the search"},
                "pattern": {"type": "string", "description": "The search pattern to match"},
                "excludePatterns": {"type": "array", "items": {"type": "string"}, "description": "Patterns to exclude"}
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
            "properties": {"path": {"type": "string", "description": "The path to get information about"}},
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
            "properties": {"paths": {"type": "array", "items": {"type": "string"}, "description": "Array of file paths to read"}},
            "required": ["paths"],
            "additionalProperties": False
        },
        "_server": "filesystem"
    },
    {
        "name": "list_allowed_directories",
        "description": "Returns the list of directories that this server is allowed to access. Use this to understand which directories are available before trying to read or write files.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "_server": "filesystem"
    },
    {
        "name": "brave_web_search",
        "description": "Performs a web search using the Brave Search API, ideal for general queries, news, articles, and online content. Use this for broad information gathering, recent events, or when you need diverse web sources. Supports pagination, content filtering, and freshness parameters. Maximum 20 results per request.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (max 400 chars, 50 words)"},
                "count": {"type": "integer", "description": "Number of results (1-20, default 10)", "default": 10, "minimum": 1, "maximum": 20},
                "offset": {"type": "integer", "description": "Pagination offset (max 9, default 0)", "default": 0},
                "freshness": {"type": "string", "description": "Filter by content age", "enum": ["pd", "pw", "pm", "py"]}
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
                "query": {"type": "string", "description": "Local search query"},
                "count": {"type": "integer", "description": "Number of results (1-20, default 5)", "default": 5}
            },
            "required": ["query"],
            "additionalProperties": False
        },
        "_server": "brave-search"
    },
    {
        "name": "git_status",
        "description": "Shows the working tree status. Displays paths that have differences between the index file and the current HEAD commit, paths that have differences between the working tree and the index file, and paths in the working tree that are not tracked by Git.",
        "inputSchema": {
            "type": "object",
            "properties": {"repo_path": {"type": "string", "description": "Path to the Git repository"}},
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
                "repo_path": {"type": "string", "description": "Path to the Git repository"},
                "max_count": {"type": "integer", "description": "Maximum number of commits to show", "default": 10},
                "author": {"type": "string", "description": "Filter commits by author"},
                "since": {"type": "string", "description": "Show commits after date"},
                "until": {"type": "string", "description": "Show commits before date"},
                "path": {"type": "string", "description": "Filter commits affecting this path"}
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
                "repo_path": {"type": "string", "description": "Path to the Git repository"},
                "target": {"type": "string", "description": "Target to diff against (commit, branch, etc.)"},
                "cached": {"type": "boolean", "description": "Show staged changes", "default": False}
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
                "repo_path": {"type": "string", "description": "Path to the Git repository"},
                "message": {"type": "string", "description": "Commit message"}
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
                "repo_path": {"type": "string", "description": "Path to the Git repository"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Files to add"}
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
                "repo_path": {"type": "string", "description": "Path to the Git repository"},
                "branch_name": {"type": "string", "description": "Name of branch to create"},
                "delete": {"type": "boolean", "description": "Delete the branch", "default": False}
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
                "repo_path": {"type": "string", "description": "Path to the Git repository"},
                "branch": {"type": "string", "description": "Branch to switch to"},
                "create": {"type": "boolean", "description": "Create new branch and switch to it", "default": False}
            },
            "required": ["repo_path", "branch"],
            "additionalProperties": False
        },
        "_server": "git"
    },
]


# ============================================================================
# TOKEN ESTIMATION
# ============================================================================

def approx_token_count(text: str) -> int:
    """Rough token estimation: ~4 chars per token for English/JSON."""
    return len(text) // 4


def strip_internal_keys(tool: dict) -> dict:
    return {k: v for k, v in tool.items() if not k.startswith("_")}


# ============================================================================
# SMART DESCRIPTION CONDENSATION
# ============================================================================

def condense_description_smart(description: str, max_len: int = 80) -> str:
    """Intelligently condense a tool description.

    Strategy:
    1. Extract first sentence (the action statement)
    2. Remove filler phrases that don't add selection value
    3. Preserve the core verb + object + key qualifier
    4. Never cut mid-word
    """
    if not description:
        return ""

    # Extract first sentence
    # Split on '. ' to avoid splitting on decimals/abbreviations
    match = re.match(r'^(.+?\.)\s', description + ' ')
    first_sentence = match.group(1) if match else description

    # Remove common filler phrases that don't help tool selection
    fillers = [
        r'\s*Only works within allowed directories\.?',
        r'\s*Use this tool when you need to\s+',
        r'\s*Use this for\s+',
        r'\s*Use with caution as\s+',
        r'\s*This is (?:more )?(?:useful|efficient)\s+',
    ]
    cleaned = first_sentence
    for filler in fillers:
        cleaned = re.sub(filler, '', cleaned, flags=re.IGNORECASE)

    # Trim to max_len without cutting mid-word
    if len(cleaned) <= max_len:
        return cleaned.strip().rstrip('.')

    # Find last space before max_len
    truncated = cleaned[:max_len]
    last_space = truncated.rfind(' ')
    if last_space > max_len // 2:
        truncated = truncated[:last_space]

    return truncated.strip().rstrip('.')


# ============================================================================
# SCHEMA CONDENSATION
# ============================================================================

def condense_schema(schema: dict) -> dict:
    """Condense inputSchema: keep required params with types, drop descriptions/defaults/enums.

    Rules:
    - Keep ALL property names and their types (required AND optional)
    - Drop: property descriptions, default values, enum lists, examples
    - Drop: additionalProperties, min/max constraints
    - Simplify nested objects: keep type but drop nested property descriptions
    - Simplify arrays: keep type + items type
    """
    if not schema or not schema.get("properties"):
        return {"type": "object"}

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    condensed_props = {}
    for prop_name, prop_def in properties.items():
        prop_type = prop_def.get("type", "string")

        if prop_type == "array":
            items = prop_def.get("items", {})
            items_type = items.get("type", "string")
            if items_type == "object":
                # Nested object array - simplify
                condensed_props[prop_name] = {"type": "array", "items": {"type": "object"}}
            else:
                condensed_props[prop_name] = {"type": "array", "items": {"type": items_type}}
        elif prop_type == "object":
            condensed_props[prop_name] = {"type": "object"}
        else:
            condensed_props[prop_name] = {"type": prop_type}

    result = {
        "type": "object",
        "properties": condensed_props,
    }
    if required:
        result["required"] = required

    return result


def condense_schema_required_only(schema: dict) -> dict:
    """Even more aggressive: only required params, with types."""
    if not schema or not schema.get("properties"):
        return {"type": "object"}

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    if not required:
        return {"type": "object"}

    condensed_props = {}
    for prop_name in required:
        if prop_name in properties:
            prop_def = properties[prop_name]
            prop_type = prop_def.get("type", "string")
            if prop_type == "array":
                items = prop_def.get("items", {})
                condensed_props[prop_name] = {"type": "array", "items": {"type": items.get("type", "string")}}
            else:
                condensed_props[prop_name] = {"type": prop_type}

    return {
        "type": "object",
        "properties": condensed_props,
        "required": required,
    }


# ============================================================================
# APPROACH BUILDERS
# ============================================================================

def build_full_passthrough(tools):
    """Baseline: all tools with original schemas."""
    return [strip_internal_keys(t) for t in tools]


def build_current_meta(tools):
    """Current ToolMux: 4 meta-tools, no backend tool info."""
    return [
        {"name": "catalog_tools", "description": "List all available tools from backend MCP servers",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "get_tool_schema", "description": "Get schema for a specific tool",
         "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        {"name": "invoke", "description": "Execute a backend tool",
         "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "args": {"type": "object"}}, "required": ["name"]}},
        {"name": "get_tool_count", "description": "Get count of available tools by server",
         "inputSchema": {"type": "object", "properties": {}}},
    ]


def build_smart_proxy_all_params(tools):
    """NEW - Smart Proxy: smart description + ALL params with types (no descriptions)."""
    condensed = []
    for tool in tools:
        condensed.append({
            "name": tool["name"],
            "description": condense_description_smart(tool.get("description", "")),
            "inputSchema": condense_schema(tool.get("inputSchema", {})),
        })
    # Add get_tool_schema helper
    condensed.append({
        "name": "get_tool_schema",
        "description": "Get full parameter details and description for any tool",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    })
    return condensed


def build_smart_proxy_required_only(tools):
    """NEW - Smart Proxy: smart description + REQUIRED params only."""
    condensed = []
    for tool in tools:
        condensed.append({
            "name": tool["name"],
            "description": condense_description_smart(tool.get("description", "")),
            "inputSchema": condense_schema_required_only(tool.get("inputSchema", {})),
        })
    condensed.append({
        "name": "get_tool_schema",
        "description": "Get full parameter details and description for any tool",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    })
    return condensed


# ============================================================================
# ANALYSIS
# ============================================================================

def analyze_tools_list(name, tools_list):
    """Measure token cost of a tools/list response."""
    response = {"jsonrpc": "2.0", "id": 1, "result": {"tools": tools_list}}
    json_compact = json.dumps(response, separators=(",", ":"))
    return {
        "name": name,
        "tool_count": len(tools_list),
        "chars": len(json_compact),
        "tokens": approx_token_count(json_compact),
    }


def measure_invocation_enrichment(tools, unique_tools_used=15):
    """Measure the token cost of including full descriptions on first invocation.

    In progressive disclosure: the full docstring is sent as part of the
    tool result on the FIRST call to each unique tool. This is the
    'operational' token cost.
    """
    # Pick the first N unique tools as a realistic usage pattern
    used = tools[:unique_tools_used]

    total_desc_tokens = 0
    for tool in used:
        desc = tool.get("description", "")
        # Format: "[Tool: name] Full description\n\nResult:\n..."
        enrichment = f"[{tool['name']}] {desc}"
        total_desc_tokens += approx_token_count(enrichment)

    return {
        "unique_tools_used": len(used),
        "enrichment_tokens": total_desc_tokens,
        "avg_per_tool": total_desc_tokens // max(len(used), 1),
    }


def main():
    tools = SAMPLE_BACKEND_TOOLS
    print(f"Backend tools: {len(tools)} tools from "
          f"{len(set(t['_server'] for t in tools))} servers")
    print(f"Servers: {', '.join(sorted(set(t['_server'] for t in tools)))}")

    # ========================================================================
    # PART 1: Smart Description Condensation Examples
    # ========================================================================
    print("\n" + "=" * 90)
    print("PART 1: SMART DESCRIPTION CONDENSATION")
    print("=" * 90)

    for tool in tools:
        full = tool["description"]
        smart = condense_description_smart(full)
        ratio = len(smart) / max(len(full), 1) * 100
        print(f"\n  {tool['name']}:")
        print(f"    FULL  ({len(full):>3} chars): {full[:100]}{'...' if len(full) > 100 else ''}")
        print(f"    SMART ({len(smart):>3} chars): {smart}")
        print(f"    Reduction: {100 - ratio:.0f}%")

    # ========================================================================
    # PART 2: Schema Condensation Examples
    # ========================================================================
    print("\n" + "=" * 90)
    print("PART 2: SCHEMA CONDENSATION")
    print("=" * 90)

    for tool in tools[:5]:  # Show first 5
        full_schema = tool.get("inputSchema", {})
        all_params = condense_schema(full_schema)
        req_only = condense_schema_required_only(full_schema)

        full_str = json.dumps(full_schema, separators=(",", ":"))
        all_str = json.dumps(all_params, separators=(",", ":"))
        req_str = json.dumps(req_only, separators=(",", ":"))

        print(f"\n  {tool['name']}:")
        print(f"    FULL       ({approx_token_count(full_str):>3} tok): {full_str[:120]}{'...' if len(full_str) > 120 else ''}")
        print(f"    ALL_PARAMS ({approx_token_count(all_str):>3} tok): {all_str}")
        print(f"    REQ_ONLY   ({approx_token_count(req_str):>3} tok): {req_str}")

    # ========================================================================
    # PART 3: tools/list Token Comparison
    # ========================================================================
    print("\n" + "=" * 90)
    print("PART 3: tools/list TOKEN COMPARISON (19 tools)")
    print("=" * 90)

    approaches = [
        ("Full Passthrough", build_full_passthrough(tools)),
        ("Current Meta (4 tools)", build_current_meta(tools)),
        ("Smart Proxy (all params)", build_smart_proxy_all_params(tools)),
        ("Smart Proxy (required only)", build_smart_proxy_required_only(tools)),
    ]

    results = []
    for name, tool_list in approaches:
        r = analyze_tools_list(name, tool_list)
        results.append(r)

    baseline = results[0]
    print(f"\n  {'Approach':<40} {'Tools':>5} {'Tokens':>7} {'Savings':>8}")
    print("  " + "-" * 65)
    for r in results:
        savings = (1 - r["tokens"] / baseline["tokens"]) * 100
        print(f"  {r['name']:<40} {r['tool_count']:>5} {r['tokens']:>7} {savings:>7.1f}%")

    # ========================================================================
    # PART 4: Full Session Cost (Discovery + Invocation Enrichment)
    # ========================================================================
    print("\n" + "=" * 90)
    print("PART 4: TOTAL SESSION COST (discovery + first-invocation enrichment)")
    print("=" * 90)

    enrichment = measure_invocation_enrichment(tools, unique_tools_used=10)
    print(f"\n  Scenario: Agent uses 10 unique tools during session")
    print(f"  First-invocation enrichment: {enrichment['enrichment_tokens']} tokens "
          f"(avg {enrichment['avg_per_tool']} per tool)")

    print(f"\n  {'Approach':<40} {'Discovery':>9} {'Enrichment':>11} {'TOTAL':>7} {'vs Full':>8}")
    print("  " + "-" * 80)

    for r in results:
        # Full passthrough has no enrichment cost (descriptions already in tools/list)
        if r["name"] == "Full Passthrough":
            enrich = 0
        elif r["name"] == "Current Meta (4 tools)":
            enrich = 0  # Current meta doesn't do enrichment
        else:
            enrich = enrichment["enrichment_tokens"]

        total = r["tokens"] + enrich
        vs_full = (1 - total / baseline["tokens"]) * 100
        print(f"  {r['name']:<40} {r['tokens']:>9} {enrich:>11} {total:>7} {vs_full:>7.1f}%")

    # ========================================================================
    # PART 5: Scale Analysis
    # ========================================================================
    print("\n" + "=" * 90)
    print("PART 5: SCALE ANALYSIS (projected at different tool counts)")
    print("=" * 90)

    for scale in [20, 50, 100, 200, 500]:
        scaled = []
        for i in range(scale):
            base = tools[i % len(tools)].copy()
            base["name"] = f"{base['name']}_{i}"
            base["_server"] = f"server_{i // 10}"
            scaled.append(base)

        full = analyze_tools_list("full", build_full_passthrough(scaled))
        meta = analyze_tools_list("meta", build_current_meta(scaled))
        smart_all = analyze_tools_list("smart_all", build_smart_proxy_all_params(scaled))
        smart_req = analyze_tools_list("smart_req", build_smart_proxy_required_only(scaled))

        # Enrichment: assume agent uses 15 unique tools regardless of scale
        unique_used = min(15, scale)
        enrich = measure_invocation_enrichment(scaled, unique_used)

        print(f"\n  --- {scale} tools (agent uses {unique_used} unique) ---")
        print(f"  {'Approach':<30} {'Discovery':>8} {'+ Enrich':>9} {'= Total':>8} {'Savings':>8}")
        print("  " + "-" * 70)

        for label, r, has_enrich in [
            ("Full Passthrough", full, False),
            ("Current Meta (4 tools)", meta, False),
            ("Smart Proxy (all params)", smart_all, True),
            ("Smart Proxy (req only)", smart_req, True),
        ]:
            e = enrich["enrichment_tokens"] if has_enrich else 0
            total = r["tokens"] + e
            savings = (1 - total / full["tokens"]) * 100
            print(f"  {label:<30} {r['tokens']:>8} {e:>9} {total:>8} {savings:>7.1f}%")

    # ========================================================================
    # PART 6: Sample Complete tool entry comparison
    # ========================================================================
    print("\n" + "=" * 90)
    print("PART 6: SIDE-BY-SIDE - Full vs Smart Proxy tool entry")
    print("=" * 90)

    # edit_file is a good example (complex schema)
    sample = tools[2]  # edit_file
    print(f"\n  Tool: {sample['name']}")

    full_entry = strip_internal_keys(sample)
    smart_entry = {
        "name": sample["name"],
        "description": condense_description_smart(sample.get("description", "")),
        "inputSchema": condense_schema(sample.get("inputSchema", {})),
    }
    smart_req_entry = {
        "name": sample["name"],
        "description": condense_description_smart(sample.get("description", "")),
        "inputSchema": condense_schema_required_only(sample.get("inputSchema", {})),
    }

    full_json = json.dumps(full_entry, indent=2)
    smart_json = json.dumps(smart_entry, indent=2)
    smart_req_json = json.dumps(smart_req_entry, indent=2)

    print(f"\n  FULL ({approx_token_count(full_json)} tokens):")
    for line in full_json.split('\n'):
        print(f"    {line}")

    print(f"\n  SMART ALL PARAMS ({approx_token_count(smart_json)} tokens):")
    for line in smart_json.split('\n'):
        print(f"    {line}")

    print(f"\n  SMART REQ ONLY ({approx_token_count(smart_req_json)} tokens):")
    for line in smart_req_json.split('\n'):
        print(f"    {line}")

    # Show what gets prepended to invocation result
    enrichment_text = f"[{sample['name']}] {sample['description']}"
    print(f"\n  INVOCATION ENRICHMENT ({approx_token_count(enrichment_text)} tokens):")
    print(f"    {enrichment_text}")


if __name__ == "__main__":
    main()
