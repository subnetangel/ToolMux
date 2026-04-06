#!/usr/bin/env python3
"""
ToolMux v2.0 - MCP server aggregation with FastMCP foundation
Three operating modes: meta, proxy, gateway (default)
Smart description/schema condensation, progressive disclosure, parallel init
"""
import json
import sys
import subprocess
import os
import re
import argparse
import hashlib
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

import httpx
from fastmcp import FastMCP
from fastmcp.server import create_proxy
from fastmcp.server.transforms import Transform
from fastmcp.tools import Tool

VERSION = "2.2.1"


def _is_client_disconnect(exc: BaseException) -> bool:
    """Check if exception (or nested ExceptionGroup) is only client disconnect errors."""
    import anyio
    if isinstance(exc, (anyio.ClosedResourceError, BrokenPipeError)):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return all(_is_client_disconnect(e) for e in exc.exceptions)
    return False

# ─── Filler phrases to remove from descriptions ───
FILLER_PHRASES = [
    "Only works within allowed directories",
    "Use this tool when you need to",
    "Use this tool to",
    "This tool allows you to",
    "This tool is used to",
    "This tool can be used to",
    "This tool will",
    "You can use this tool to",
]

# ─── Instructions constants ───

_OPTIMIZE_HINT = """\

Note: Tool descriptions are currently auto-generated. For higher quality descriptions, \
ask the user: "Would you like me to optimize ToolMux tool descriptions? This is a one-time \
process that improves how tools are presented." If yes, call optimize_descriptions(action="generate")."""

_OPTIMIZE_DONE = ""

def _optimization_hint(cache_model: Optional[str]) -> str:
    return _OPTIMIZE_HINT if cache_model in (None, "algorithmic") else _OPTIMIZE_DONE

INSTRUCTIONS_META_TEMPLATE = """\
You are connected to ToolMux, an MCP tool proxy in meta mode.

IMPORTANT: You MUST call list_all_tools() as your first action in every session \
to discover all available tools and their descriptions.

Available tools:
  - list_all_tools() — MUST call first. Lists all tools grouped by server.
  - catalog_tools() — list all backend tools with name, server, and description
  - get_tool_schema(name="tool_name") — get full parameter details for a tool
  - invoke(name="tool_name", args={{...}}) — execute a backend tool
  - get_tool_count() — get tool count statistics by server
  - manage_servers(action="list|add|remove|validate|test") — manage backend MCP servers
  - optimize_descriptions(action="generate|save|status") — improve tool descriptions using your intelligence

Workflow:
1. Call list_all_tools() to discover all available tools
2. Call get_tool_schema(name="tool_name") for parameter details
3. Call invoke(name="tool_name", args={{...}}) to execute{optimization_hint}"""

INSTRUCTIONS_PROXY_TEMPLATE = """\
You are connected to ToolMux, an MCP tool proxy in native proxy mode.

IMPORTANT: You MUST call list_all_tools() as your first action in every session \
to discover all available tools and their full descriptions.

All backend tools are exposed directly. Call any tool directly: tool_name(param="value")

Helper tools:
  - list_all_tools() — MUST call first. Lists all tools with full descriptions grouped by server.
  - get_tool_schema(name="tool_name") — get full parameter details for a tool
  - get_tool_count() — get tool count statistics by server
  - manage_servers(action="list|add|remove|validate|test") — manage backend MCP servers{optimization_hint}"""


# ─── Pure Functions ───

def condense_description(desc: str, max_len: int = 80) -> str:
    """Extract first sentence, remove filler phrases, trim to max_len without mid-word cut."""
    if not desc:
        return ""
    desc = desc.strip()
    # Normalize whitespace (collapse newlines and multiple spaces)
    desc = re.sub(r'\s+', ' ', desc).strip()
    # Remove filler phrases (case-insensitive)
    for filler in FILLER_PHRASES:
        pattern = re.compile(re.escape(filler), re.IGNORECASE)
        desc = pattern.sub("", desc).strip()
        # Clean up leading punctuation/whitespace after removal
        desc = re.sub(r'^[\s,.:;]+', '', desc)
    if not desc:
        return ""
    # Capitalize first letter after filler removal
    if desc and desc[0].islower():
        desc = desc[0].upper() + desc[1:]
    # Extract first sentence
    match = re.match(r'^(.+?[.!?])(?:\s|$)', desc)
    if match:
        desc = match.group(1)
    # Remove trailing period
    desc = desc.rstrip('.')
    if len(desc) <= max_len:
        return desc
    # Trim to max_len without cutting mid-word
    truncated = desc[:max_len]
    last_space = truncated.rfind(' ')
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated.rstrip()


def condense_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Strip verbose extras, keep property names, types, required array."""
    if not schema or "properties" not in schema:
        return {"type": "object"}
    result = {"type": "object", "properties": {}}
    for name, prop in schema["properties"].items():
        condensed = {}
        if "type" in prop:
            condensed["type"] = prop["type"]
            if prop["type"] == "array" and "items" in prop:
                items = prop["items"]
                condensed["items"] = {"type": items["type"]} if "type" in items else {}
        result["properties"][name] = condensed
    if "required" in schema:
        result["required"] = schema["required"]
    return result


class CondenseTransform(Transform):
    """FastMCP Transform that condenses tool descriptions and schemas for token savings."""

    async def list_tools(self, tools):
        from collections.abc import Sequence
        result = []
        for tool in tools:
            new_desc = condense_description(tool.description or "")
            new_params = condense_schema(tool.parameters)
            result.append(tool.model_copy(update={"description": new_desc, "parameters": new_params}))
        return result


def resolve_collisions(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Prefix duplicate tool names with server name. If still colliding, append index."""
    name_counts: Dict[str, int] = {}
    for tool in tools:
        n = tool["name"]
        name_counts[n] = name_counts.get(n, 0) + 1
    colliding = {n for n, c in name_counts.items() if c > 1}
    if not colliding:
        return tools
    result = []
    seen: Dict[str, int] = {}
    for tool in tools:
        t = dict(tool)
        if t["name"] in colliding:
            new_name = f"{t['_server']}_{t['name']}"
            # Handle case where prefixed name still collides
            if new_name in seen:
                seen[new_name] += 1
                new_name = f"{new_name}_{seen[new_name]}"
            else:
                seen[new_name] = 0
            t["name"] = new_name
        result.append(t)
    return result


def _extract_text(result: Dict[str, Any]) -> str:
    """Extract text content from a backend tool result."""
    content = result.get("content", [])
    if isinstance(content, list):
        parts = [c.get("text", "") for c in content if isinstance(c, dict)]
        return "\n".join(parts)
    return json.dumps(result)


def _build_enrichment_text(tool_name: str, tool_cache: List[Dict[str, Any]],
                           include_desc: bool = True) -> str:
    """Build enrichment text block for a tool."""
    for tool in tool_cache:
        if tool["name"] == tool_name:
            parts = [f"\n[Tool: {tool_name}]"]
            if include_desc:
                parts.append(f"[Description: {tool.get('description', '')}]")
            parts.append(f"[Parameters: {json.dumps(tool.get('inputSchema', {}))}]")
            return "\n".join(parts)
    return ""


def enrich_result(
    tool_name: str,
    result: Dict[str, Any],
    described_tools: Set[str],
    tool_cache: List[Dict[str, Any]],
) -> str:
    """Return result text, adding full docstring on first invocation."""
    text = _extract_text(result)
    if tool_name not in described_tools:
        enrichment = _build_enrichment_text(tool_name, tool_cache, include_desc=True)
        if enrichment:
            described_tools.add(tool_name)
            text += enrichment
    return text


def enrich_error_result(
    tool_name: str,
    error_result: Dict[str, Any],
    tool_cache: List[Dict[str, Any]],
) -> str:
    """Return error text with full schema always appended."""
    text = _extract_text(error_result)
    for tool in tool_cache:
        if tool["name"] == tool_name:
            text += f"\n[Schema for {tool_name}: {json.dumps(tool.get('inputSchema', {}))}]"
            break
    return text


def build_gateway_description(
    server_tools: List[Dict[str, Any]],
    cached_descriptions: Optional[Dict[str, str]] = None,
) -> str:
    """Build rich sub-tool listing for a gateway server-tool description."""
    parts = []
    for tool in server_tools:
        name = tool["name"]
        if cached_descriptions and name in cached_descriptions:
            desc = cached_descriptions[name]
        else:
            desc = condense_description(tool.get("description", ""), max_len=60)
        schema = tool.get("inputSchema", {})
        required = schema.get("required", [])
        if required:
            parts.append(f"{name} ({desc}; required: {', '.join(required)})")
        else:
            parts.append(f"{name} ({desc})")
    return "Tools: " + ", ".join(parts)


def build_gateway_instructions(servers_with_counts: Dict[str, int],
                               cache_model: Optional[str] = None) -> str:
    """Build dynamic gateway instructions with server summary."""
    server_lines = "\n".join(
        f"  - {name}: {count} tools" for name, count in servers_with_counts.items()
    )
    hint = _optimization_hint(cache_model)
    return f"""\
You are connected to ToolMux, an MCP tool proxy in gateway mode.

IMPORTANT: You MUST call list_all_tools() as your first action in every session \
to discover all available tools across all servers.

Available servers:
{server_lines}

Each server tool's description lists its sub-tools with their purpose and required parameters.

Workflow:
1. Call list_all_tools() to discover all available tools (MUST do first)
2. Pick the sub-tool you need
3. Call: server_name(tool="sub_tool_name", arguments={{...}})
4. For complex parameters, use get_tool_schema(name="sub_tool_name") to get full details

Example: filesystem(tool="read_file", arguments={{"path": "/tmp/example.txt"}})

Native tools (call directly by name, not via server pattern):
  - list_all_tools() — MUST call first. Lists all tools grouped by server.
  - get_tool_schema(name="tool_name") — get full parameter details for any sub-tool
  - get_tool_count() — get tool count statistics by server
  - manage_servers(action="list|add|remove|validate|test") — manage backend MCP servers
  - optimize_descriptions(action="generate|save|status") — improve tool descriptions using your intelligence

On first use of each sub-tool, additional context (full description and parameters) \
will be provided with the result.{hint}"""


# ─── HttpMcpClient (preserved from v1.2.1, version bump) ───

class HttpMcpClient:
    """HTTP/SSE MCP client for remote MCP servers."""

    def __init__(self, base_url: str, headers: Optional[Dict[str, str]] = None,
                 timeout: int = 30, sse_endpoint: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.headers = headers or {}
        self.timeout = timeout
        self.sse_endpoint = sse_endpoint or "/sse"
        self.client = httpx.Client(
            headers=self.headers,
            timeout=httpx.Timeout(timeout, connect=timeout / 2),
        )
        self._initialized = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        if hasattr(self, 'client'):
            self.client.close()

    def call_rpc(self, method: str, params: Optional[Dict[str, Any]] = None,
                 request_id: int = 1) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": request_id}
        if params:
            payload["params"] = params
        try:
            response = self.client.post(f"{self.base_url}/mcp", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                try:
                    response = self.client.post(f"{self.base_url}/rpc", json=payload)
                    response.raise_for_status()
                    return response.json()
                except Exception:
                    pass
            return {"jsonrpc": "2.0", "id": request_id, "error": {
                "code": -32603, "message": f"HTTP {e.response.status_code}: {e}",
                "data": {"transport": "http", "url": self.base_url}}}
        except httpx.TimeoutException:
            return {"jsonrpc": "2.0", "id": request_id, "error": {
                "code": -32603, "message": f"Request timeout after {self.timeout}s",
                "data": {"transport": "http", "url": self.base_url}}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": request_id, "error": {
                "code": -32603, "message": f"Connection error: {e}",
                "data": {"transport": "http", "url": self.base_url}}}

    def initialize(self) -> bool:
        if self._initialized:
            return True
        init_response = self.call_rpc("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "ToolMux", "version": VERSION}})
        if "error" in init_response:
            return False
        self.call_rpc("notifications/initialized")
        self._initialized = True
        return True

    def get_tools(self) -> List[Dict[str, Any]]:
        if not self.initialize():
            return []
        response = self.call_rpc("tools/list")
        if "error" in response:
            return []
        return response.get("result", {}).get("tools", [])

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self.initialize():
            return {"error": "Failed to initialize HTTP MCP connection"}
        response = self.call_rpc("tools/call", {"name": tool_name, "arguments": arguments})
        if "error" in response:
            return {"error": response["error"]["message"]}
        return response.get("result", {"error": "No result returned"})


# ─── BackendManager ───

class BackendManager:
    """Manages connections to backend MCP servers (stdio and HTTP)."""

    def __init__(self, servers_config: Dict[str, Dict[str, Any]]):
        self.servers = servers_config
        self.server_processes: Dict[str, Any] = {}
        self.tool_cache: List[Dict[str, Any]] = []
        self._described_tools: Set[str] = set()
        self._init_complete = threading.Event()
        self._lock = threading.Lock()
        self._bundle_fixes: Dict[str, Dict[str, Any]] = {}  # servers fixed via bundle fallback

    def initialize_all_async(self):
        """Start parallel initialization in a background thread."""
        t = threading.Thread(target=self._init_all, daemon=True)
        t.start()

    def _init_all(self):
        """Initialize all backends in parallel using a thread pool."""
        try:
            with ThreadPoolExecutor(max_workers=min(10, len(self.servers) or 1)) as pool:
                futures = {pool.submit(self._init_server, name): name
                           for name in self.servers}
                for future in as_completed(futures, timeout=30):
                    name = futures[future]
                    try:
                        tools = future.result()
                        if tools:
                            with self._lock:
                                self.tool_cache.extend(tools)
                    except Exception:
                        pass  # Silent — don't write to stderr during stdio mode
        except Exception:
            pass  # Silent
        self._init_complete.set()

    def _init_server(self, server_name: str) -> List[Dict[str, Any]]:
        """Initialize a single backend server and return its tools.

        If the server starts but returns 0 tools, retries with bundle config
        (which may have different args the server needs).
        """
        tools = self._try_init_server(server_name)
        if tools:
            return tools
        # Server returned 0 tools — check if bundle has different args
        bundle = resolve_bundle(server_name)
        if not bundle:
            return []
        current = self.servers[server_name]
        bundle_args = bundle.get("args", [])
        if bundle_args != current.get("args", []) or bundle["command"] != current.get("command"):
            # Kill the failed process and retry with bundle config
            proc = self.server_processes.pop(server_name, None)
            if proc and hasattr(proc, "terminate"):
                try:
                    proc.terminate()
                except Exception:
                    pass
            patched = dict(current)
            patched["command"] = bundle["command"]
            patched["args"] = bundle_args
            self.servers[server_name] = patched
            self._bundle_fixes[server_name] = patched
            return self._try_init_server(server_name)
        return []

    def _try_init_server(self, server_name: str) -> List[Dict[str, Any]]:
        """Single attempt to init a server and get its tools."""
        server = self.start_server(server_name)
        if not server:
            return []
        tools: List[Dict[str, Any]] = []
        try:
            if isinstance(server, HttpMcpClient):
                raw_tools = server.get_tools()
                for tool in raw_tools:
                    tool["_server"] = server_name
                    tool["_transport"] = "http"
                    tools.append(tool)
            else:
                init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "ToolMux", "version": VERSION}}}
                server.stdin.write(json.dumps(init_req) + "\n")
                server.stdin.flush()
                server.stdout.readline()
                notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                server.stdin.write(json.dumps(notif) + "\n")
                server.stdin.flush()
                tools_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
                server.stdin.write(json.dumps(tools_req) + "\n")
                server.stdin.flush()
                line = server.stdout.readline()
                if line:
                    resp = json.loads(line)
                    for tool in resp.get("result", {}).get("tools", []):
                        tool["_server"] = server_name
                        tool["_transport"] = "stdio"
                        tools.append(tool)
        except Exception:
            pass
        return tools

    def start_server(self, server_name: str):
        """Start a single backend server (stdio or HTTP).

        If the configured command fails, automatically checks mcp-registry
        bundle files for the correct launch config and retries.
        """
        if server_name in self.server_processes:
            return self.server_processes[server_name]
        config = self.servers[server_name]
        if config.get("transport") == "http":
            try:
                client = HttpMcpClient(
                    base_url=config["base_url"],
                    headers=config.get("headers"),
                    timeout=config.get("timeout", 30),
                    sse_endpoint=config.get("sse_endpoint"))
                self.server_processes[server_name] = client
                return client
            except Exception as e:
                return None
        proc = self._start_stdio_server(server_name, config)
        if proc:
            return proc
        # Command failed — try bundle fallback
        bundle = resolve_bundle(server_name)
        if bundle and bundle["command"] != config.get("command"):
            patched = dict(config)
            patched["command"] = bundle["command"]
            patched["args"] = bundle.get("args", [])
            proc = self._start_stdio_server(server_name, patched)
            if proc:
                self.servers[server_name] = patched
                self._bundle_fixes[server_name] = patched
                return proc
        return None

    def _start_stdio_server(self, server_name: str, config: Dict[str, Any]):
        """Attempt to start a stdio subprocess for the given config."""
        cmd = config.get("command", "")
        if not shutil.which(cmd):
            return None
        env = os.environ.copy()
        env.update(config.get("env", {}))
        try:
            proc = subprocess.Popen(
                [cmd] + config.get("args", []),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, env=env, cwd=config.get("cwd"))
            self.server_processes[server_name] = proc
            return proc
        except Exception:
            return None

    def wait_for_tools(self, timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Block until initialization completes and return all tools."""
        self._init_complete.wait(timeout=timeout)
        with self._lock:
            return list(self.tool_cache)

    def get_all_tools(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.tool_cache)

    def persist_fixes(self, config: Dict[str, Any], config_path: Path) -> None:
        """Write any bundle-resolved fixes back to mcp.json so they stick."""
        if not self._bundle_fixes:
            return
        for name, patched in self._bundle_fixes.items():
            config.setdefault("servers", {})[name] = patched
        _save_config(config, config_path)

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Route a tool call to the correct backend server."""
        # Wait for backends if still initializing (first call after no-cache start)
        if not self._init_complete.is_set():
            self._init_complete.wait(timeout=30)
        target_server = None
        for tool in self.tool_cache:
            if tool["name"] == name:
                target_server = tool["_server"]
                break
        if not target_server:
            # In gateway mode, name IS the server name
            if name in self.servers:
                target_server = name
            else:
                return {"content": [{"type": "text", "text": f"Tool '{name}' not found"}], "isError": True}
        server = self.server_processes.get(target_server)
        if not server:
            return {"content": [{"type": "text", "text": f"Server '{target_server}' not available"}], "isError": True}
        try:
            if isinstance(server, HttpMcpClient):
                return server.call_tool(name, arguments)
            req = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                   "params": {"name": name, "arguments": arguments}}
            server.stdin.write(json.dumps(req) + "\n")
            server.stdin.flush()
            line = server.stdout.readline()
            if line:
                resp = json.loads(line)
                return resp.get("result", {"error": "No result"})
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
        return {"content": [{"type": "text", "text": "Tool execution failed"}], "isError": True}

    def shutdown(self):
        """Terminate all backend server processes and close HTTP connections."""
        for server in self.server_processes.values():
            try:
                if isinstance(server, HttpMcpClient):
                    server.close()
                else:
                    try:
                        server.stdin.close()
                    except Exception:
                        pass
                    server.terminate()
            except Exception:
                pass
        self.server_processes.clear()


# ─── Native Management Tool ───

def register_manage_tool(mcp: FastMCP, config_path: Path, config: Dict[str, Any]):
    """Register manage_servers and optimize_descriptions native tools."""

    @mcp.tool()
    def manage_servers(action: str, name: Optional[str] = None,
                       command: Optional[str] = None,
                       args: Optional[List[str]] = None,
                       description: Optional[str] = None,
                       transport: Optional[str] = None,
                       base_url: Optional[str] = None) -> str:
        """Manage ToolMux backend MCP servers. Actions: list, add, remove, validate, test.

        Examples:
          manage_servers(action="list")
          manage_servers(action="add", name="my-mcp", command="my-mcp-server", description="My MCP")
          manage_servers(action="remove", name="my-mcp")
          manage_servers(action="validate")
          manage_servers(action="test", name="my-server")
        """
        servers = config.get("servers", {})

        if action == "list":
            entries = []
            for sname, cfg in servers.items():
                t = cfg.get("transport", "stdio")
                cmd = cfg.get("command", cfg.get("base_url", "?"))
                entries.append({"name": sname, "transport": t, "command": cmd,
                                "description": cfg.get("description", "")})
            return json.dumps({"servers": entries, "total": len(entries),
                               "config_path": str(config_path)}, indent=2)

        elif action == "add":
            if not name:
                return json.dumps({"error": "Required: name"})
            if name in servers:
                return json.dumps({"error": f"Server '{name}' already exists. Remove it first."})
            # If no command/base_url provided, try bundle resolution
            if not command and not base_url:
                bundle = resolve_bundle(name)
                if bundle:
                    command = bundle["command"]
                    args = args or bundle["args"]
                else:
                    return json.dumps({"error": "Required: name + command (stdio) or name + base_url (http). "
                                                f"No bundle found for '{name}'."})
            if transport == "http" or base_url:
                entry: Dict[str, Any] = {"transport": "http", "base_url": base_url or "", "timeout": 30}
            else:
                entry = {"command": command, "args": args or [], "timeout": 120000}
            if description:
                entry["description"] = description
            config.setdefault("servers", {})[name] = entry
            _save_config(config, config_path)
            return json.dumps({"success": True, "message": f"Added '{name}'",
                               "note": "Restart ToolMux to load the new server"})

        elif action == "remove":
            if not name:
                return json.dumps({"error": "Required: name"})
            if name not in servers:
                return json.dumps({"error": f"Server '{name}' not found",
                                   "available": list(servers.keys())})
            del config["servers"][name]
            _save_config(config, config_path)
            return json.dumps({"success": True, "message": f"Removed '{name}'",
                               "note": "Restart ToolMux to apply changes"})

        elif action == "validate":
            results = []
            for sname, cfg in servers.items():
                if cfg.get("transport") == "http":
                    ok = bool(cfg.get("base_url"))
                    results.append({"name": sname, "valid": ok,
                                    "detail": cfg.get("base_url", "missing base_url")})
                else:
                    cmd = cfg.get("command", "")
                    found = bool(shutil.which(cmd))
                    detail = f"{cmd} {'found' if found else 'NOT FOUND'}"
                    if not found:
                        bundle = resolve_bundle(sname)
                        if bundle and shutil.which(bundle["command"]):
                            detail += (f" (bundle has '{bundle['command']}' "
                                       f"{' '.join(bundle['args'])} — fixable)")
                    results.append({"name": sname, "valid": found, "detail": detail})
            return json.dumps({"results": results,
                               "total": len(results),
                               "errors": sum(1 for r in results if not r["valid"])}, indent=2)

        elif action == "test":
            targets = {name: servers[name]} if name and name in servers else servers
            if name and name not in servers:
                return json.dumps({"error": f"Server '{name}' not found",
                                   "available": list(servers.keys())})
            bm = BackendManager(targets)
            bm.initialize_all_async()
            tools = bm.wait_for_tools(timeout=15)
            by_server: Dict[str, int] = {}
            for t in tools:
                by_server[t["_server"]] = by_server.get(t["_server"], 0) + 1
            results = []
            for sname in targets:
                count = by_server.get(sname, 0)
                results.append({"name": sname, "tools": count, "ok": count > 0})
            bm.shutdown()
            return json.dumps({"results": results, "total_tools": len(tools)}, indent=2)

        return json.dumps({"error": f"Unknown action '{action}'",
                           "valid_actions": ["list", "add", "remove", "validate", "test"]})

    @mcp.tool()
    def optimize_descriptions(action: str, server: Optional[str] = None,
                    descriptions: Optional[Dict[str, str]] = None) -> str:
        """Optimize ToolMux tool descriptions using your intelligence as the LLM. Produces higher-quality descriptions than the auto-generated algorithmic ones.

        Actions:
          status — Check if descriptions have been optimized or are still algorithmic.
          generate — Returns all tools with their full descriptions. Read them and generate concise (<60 char) versions.
          save — Save your optimized descriptions for a server.

        Workflow:
          1. optimize_descriptions(action="generate") → review all tools
          2. For each server, write concise descriptions capturing the action verb and key object
          3. optimize_descriptions(action="save", server="server_name", descriptions={"tool1": "desc1", ...})
          4. Restart ToolMux to use optimized descriptions
        """
        if action == "status":
            cache_file = config_path.parent / ".toolmux_cache.json"
            if not cache_file.exists():
                return json.dumps({"cached": False, "message": "No cache file. Use optimize_descriptions(action='generate') to start."})
            try:
                cache = json.loads(cache_file.read_text())
                total = sum(len(s.get("descriptions", {})) for s in cache.get("servers", {}).values())
                return json.dumps({
                    "cached": True, "generated_at": cache.get("generated_at"),
                    "model": cache.get("model"), "total_descriptions": total,
                    "servers": {s: {"tool_count": d.get("tool_count"), "descriptions": len(d.get("descriptions", {}))}
                                for s, d in cache.get("servers", {}).items()}})
            except Exception as e:
                return json.dumps({"cached": False, "error": str(e)})

        elif action == "generate":
            tools = config.get("_backend_tools", [])
            if not tools:
                return json.dumps({"error": "No backend tools loaded. ToolMux must be running with backends initialized."})
            server_tools: Dict[str, List[Dict[str, str]]] = {}
            for t in tools:
                s = t.get("_server", "unknown")
                server_tools.setdefault(s, []).append({
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "required": t.get("inputSchema", {}).get("required", []),
                })
            result = {"instruction": (
                "For each server below, generate a concise description (<60 chars) for each tool. "
                "Focus on the action verb and key object. Then call: "
                "optimize_descriptions(action='save', server='server_name', descriptions={'tool': 'desc', ...}) "
                "for each server."),
                "servers": {}}
            for sname, stools in server_tools.items():
                result["servers"][sname] = {
                    "tool_count": len(stools),
                    "tools": [{
                        "name": t["name"],
                        "description": t["description"][:200],
                        "required": t["required"],
                    } for t in stools]}
            return json.dumps(result, indent=2)

        elif action == "save":
            if not server or not descriptions:
                return json.dumps({"error": "Required: server and descriptions"})
            # Load or create cache
            cache_file = config_path.parent / ".toolmux_cache.json"
            if cache_file.exists():
                try:
                    cache = json.loads(cache_file.read_text())
                except Exception:
                    cache = {}
            else:
                cache = {}
            cache["version"] = "1.0"
            cache["generated_at"] = datetime.now(timezone.utc).isoformat()
            cache["config_hash"] = compute_config_hash(config_path)
            cache["model"] = "agent-generated"
            cache.setdefault("servers", {})
            # Count tools for this server
            tools = config.get("_backend_tools", [])
            count = sum(1 for t in tools if t.get("_server") == server)
            cache["servers"][server] = {
                "tool_count": count,
                "descriptions": descriptions,
            }
            cache_file.write_text(json.dumps(cache, indent=2))
            return json.dumps({"success": True,
                               "message": f"Saved {len(descriptions)} descriptions for '{server}'",
                               "note": "Restart ToolMux to use new cache"})

        return json.dumps({"error": f"Unknown action '{action}'",
                           "valid_actions": ["generate", "save", "status"]})


# ─── Mode Registration Functions ───

def register_meta_tools(mcp: FastMCP, backend: BackendManager,
                        cached_descriptions: Optional[Dict[str, Dict[str, str]]] = None):
    """Register 4 meta-tools for meta mode."""

    @mcp.tool()
    def catalog_tools() -> str:
        """List all available tools from backend MCP servers."""
        tools = backend.get_all_tools()
        catalog = []
        for tool in tools:
            name = tool["name"]
            server = tool["_server"]
            # Use cached description if available
            if cached_descriptions and server in cached_descriptions and name in cached_descriptions[server]:
                desc = cached_descriptions[server][name]
            else:
                desc = condense_description(tool.get("description", ""))
            schema = tool.get("inputSchema", {})
            params = list(schema.get("properties", {}).keys())
            catalog.append({"name": name, "server": server,
                            "description": desc, "parameters": params})
        return json.dumps(catalog, indent=2)

    @mcp.tool()
    def get_tool_schema(name: str) -> str:
        """Get full description and inputSchema for a specific tool."""
        for tool in backend.get_all_tools():
            if tool["name"] == name:
                return json.dumps({
                    "name": name, "server": tool["_server"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("inputSchema", {})}, indent=2)
        return json.dumps({"error": f"Tool '{name}' not found"})

    @mcp.tool()
    def invoke(name: str, args: Optional[Dict[str, Any]] = None) -> str:
        """Execute a backend tool by name."""
        result = backend.call_tool(name, args or {})
        text = enrich_result(name, result, backend._described_tools, backend.tool_cache)
        if isinstance(result, dict) and result.get("isError"):
            text = enrich_error_result(name, result, backend.tool_cache)
        return text

    @mcp.tool()
    def get_tool_count() -> str:
        """Get count of available tools by server."""
        tools = backend.get_all_tools()
        by_server: Dict[str, int] = {}
        for tool in tools:
            s = tool["_server"]
            by_server[s] = by_server.get(s, 0) + 1
        return json.dumps({"total_tools": len(tools), "by_server": by_server}, indent=2)

    @mcp.tool()
    def list_all_tools(server: Optional[str] = None) -> str:
        """List all tool names and descriptions grouped by server. Optionally filter by server name."""
        all_tools = backend.get_all_tools()
        by_server: Dict[str, List[Dict[str, str]]] = {}
        for t in all_tools:
            s = t["_server"]
            if server and s != server:
                continue
            name = t["name"]
            if cached_descriptions and s in cached_descriptions and name in cached_descriptions[s]:
                desc = cached_descriptions[s][name]
            else:
                desc = condense_description(t.get("description", ""), max_len=80)
            by_server.setdefault(s, []).append({"name": name, "description": desc})
        return json.dumps({"total_tools": sum(len(v) for v in by_server.values()),
                           "servers": {s: {"tool_count": len(tl), "tools": tl}
                                       for s, tl in by_server.items()}}, indent=2)


def register_proxy_tools(mcp: FastMCP, backend: BackendManager,
                         cached_descriptions: Optional[Dict[str, Dict[str, str]]] = None,
                         preloaded_tools: Optional[List[Dict[str, Any]]] = None):
    """Register all backend tools directly with condensed schemas for proxy mode."""
    tools = resolve_collisions(preloaded_tools if preloaded_tools is not None else backend.wait_for_tools())

    @mcp.tool()
    def get_tool_schema(name: str) -> str:
        """Get full description and inputSchema for a specific tool."""
        for tool in backend.get_all_tools():
            if tool["name"] == name:
                return json.dumps({
                    "name": name, "server": tool["_server"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("inputSchema", {})}, indent=2)
        return json.dumps({"error": f"Tool '{name}' not found"})

    @mcp.tool()
    def list_all_tools(server: Optional[str] = None) -> str:
        """List all tool names and descriptions grouped by server. Optionally filter by server name."""
        all_tools = backend.get_all_tools()
        by_server: Dict[str, List[Dict[str, str]]] = {}
        for t in all_tools:
            s = t["_server"]
            if server and s != server:
                continue
            name = t["name"]
            if cached_descriptions and s in cached_descriptions and name in cached_descriptions[s]:
                desc = cached_descriptions[s][name]
            else:
                desc = condense_description(t.get("description", ""), max_len=80)
            by_server.setdefault(s, []).append({"name": name, "description": desc})
        return json.dumps({"total_tools": sum(len(v) for v in by_server.values()),
                           "servers": {s: {"tool_count": len(tl), "tools": tl}
                                       for s, tl in by_server.items()}}, indent=2)

    @mcp.tool()
    def get_tool_count() -> str:
        """Get count of available tools by server."""
        all_tools = backend.get_all_tools()
        by_server: Dict[str, int] = {}
        for t in all_tools:
            s = t["_server"]
            by_server[s] = by_server.get(s, 0) + 1
        return json.dumps({"total_tools": len(all_tools), "by_server": by_server}, indent=2)

    for tool in tools:
        tool_name = tool["name"]
        server = tool["_server"]
        if cached_descriptions and server in cached_descriptions and tool_name in cached_descriptions[server]:
            desc = cached_descriptions[server][tool_name]
        else:
            desc = condense_description(tool.get("description", ""))
        schema = condense_schema(tool.get("inputSchema", {}))

        def make_handler(tn: str, tool_desc: str):
            async def handler(arguments: Optional[Dict[str, Any]] = None) -> str:
                result = backend.call_tool(tn, arguments or {})
                text = enrich_result(tn, result, backend._described_tools, backend.tool_cache)
                if isinstance(result, dict) and result.get("isError"):
                    text = enrich_error_result(tn, result, backend.tool_cache)
                return text
            handler.__name__ = tn
            handler.__doc__ = tool_desc
            return handler

        fn = make_handler(tool_name, desc)
        mcp.add_tool(Tool.from_function(fn, name=tool_name, description=desc))


def _build_proxy_mcp_config(servers: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Convert ToolMux servers config to standard mcpServers format for fastmcp.

    For stdio servers, resolves commands through the bundle system (same as
    BackendManager) so that AIM-installed and mcp-registry servers work in
    proxy mode without requiring the bare command name on PATH.
    """
    mcp_servers: Dict[str, Any] = {}
    for name, cfg in servers.items():
        entry: Dict[str, Any] = {}
        if cfg.get("transport") == "http" or "base_url" in cfg or "url" in cfg:
            entry["url"] = cfg.get("base_url") or cfg.get("url", "")
            entry["transport"] = "streamable-http"
        else:
            cmd = cfg.get("command", name)
            args = cfg.get("args", [])
            if not shutil.which(cmd):
                bundle = resolve_bundle(name)
                if bundle:
                    cmd = bundle["command"]
                    args = bundle.get("args", [])
            entry["command"] = cmd
            entry["args"] = args
        if cfg.get("env"):
            entry["env"] = cfg["env"]
        mcp_servers[name] = entry
    return {"mcpServers": mcp_servers}


def run_proxy_native(servers: Dict[str, Dict[str, Any]], config: Dict[str, Any],
                     config_path: Path):
    """Run proxy mode using per-server isolated proxies.

    Each backend is mounted as an independent proxy so that one crashing
    server cannot take down the others.  Tools are exposed with
    {server}_{tool} prefixing, and CondenseTransform reduces token usage.
    """
    mcp_config = _build_proxy_mcp_config(servers)
    cache_model = _get_cache_model(config_path)
    instructions = INSTRUCTIONS_PROXY_TEMPLATE.format(
        optimization_hint=_optimization_hint(cache_model))

    # Build composite ourselves instead of create_proxy(multi_server_config)
    # so each backend gets its own transport — one crash can't kill the rest.
    failed_servers: Dict[str, str] = {}
    if len(mcp_config["mcpServers"]) == 1:
        # Single server: use create_proxy directly to keep tools unprefixed
        proxy = create_proxy(mcp_config, name="ToolMux",
                             instructions=instructions, version=VERSION)
    else:
        # Multiple servers: mount each independently for error isolation
        proxy = FastMCP(name="ToolMux", instructions=instructions, version=VERSION)
        for name, srv_cfg in mcp_config["mcpServers"].items():
            try:
                single = {"mcpServers": {name: srv_cfg}}
                backend = create_proxy(single, name=f"Proxy-{name}")
                proxy.mount(backend, namespace=name)
            except Exception as e:
                failed_servers[name] = str(e)
                print(f"⚠ ToolMux: skipping {name}: {e}", file=sys.stderr)

    proxy.add_transform(CondenseTransform())

    # Helper tools that provide full (uncondensed) tool info on demand.
    # These bypass the CondenseTransform since they query the proxy's
    # internal tool list before transforms are applied.

    @proxy.tool()
    async def list_all_tools(server: Optional[str] = None) -> str:
        """List all tool names and descriptions grouped by server. Optionally filter by server name."""
        # Get raw tools before CondenseTransform is applied
        raw_tools = list(await proxy._list_tools())
        by_server: Dict[str, List[Dict[str, str]]] = {}
        for t in raw_tools:
            name = t.name
            s = "default"
            for srv in servers:
                if name.startswith(f"{srv}_"):
                    s = srv
                    break
            if server and s != server:
                continue
            by_server.setdefault(s, []).append({
                "name": name, "description": t.description or ""})
        return json.dumps({"total_tools": sum(len(v) for v in by_server.values()),
                           "servers": {s: {"tool_count": len(tl), "tools": tl}
                                       for s, tl in by_server.items()}}, indent=2)

    @proxy.tool()
    async def get_tool_schema(name: str) -> str:
        """Get full description and inputSchema for a specific tool."""
        raw_tools = list(await proxy._list_tools())
        for t in raw_tools:
            if t.name == name:
                return json.dumps({"name": name, "description": t.description or "",
                                   "input_schema": t.parameters}, indent=2)
        return json.dumps({"error": f"Tool '{name}' not found"})

    @proxy.tool()
    async def get_tool_count() -> str:
        """Get count of available tools by server, including any servers that failed to start."""
        raw_tools = list(await proxy._list_tools())
        by_server: Dict[str, int] = {}
        for t in raw_tools:
            s = "default"
            for srv in servers:
                if t.name.startswith(f"{srv}_"):
                    s = srv
                    break
            by_server[s] = by_server.get(s, 0) + 1
        result: Dict[str, Any] = {"total_tools": len(raw_tools), "by_server": by_server}
        if failed_servers:
            result["failed_servers"] = failed_servers
        return json.dumps(result, indent=2)

    # Add manage_servers tool
    register_manage_tool(proxy, config_path, config)

    try:
        proxy.run(show_banner=False)
    except BaseExceptionGroup as eg:
        if not _is_client_disconnect(eg):
            raise
    except (KeyboardInterrupt, SystemExit):
        pass


def register_gateway_tools(mcp: FastMCP, backend: BackendManager,
                           cached_descriptions: Optional[Dict[str, Dict[str, str]]] = None,
                           cache_model: Optional[str] = None,
                           preloaded_tools: Optional[List[Dict[str, Any]]] = None):
    """Register one server-tool per backend + native helper tools for gateway mode."""
    tools = preloaded_tools if preloaded_tools is not None else backend.wait_for_tools()

    # Group tools by server
    server_tools_map: Dict[str, List[Dict[str, Any]]] = {}
    for tool in tools:
        server = tool["_server"]
        server_tools_map.setdefault(server, []).append(tool)

    # Build instructions
    servers_with_counts = {s: len(t) for s, t in server_tools_map.items()}
    mcp.instructions = build_gateway_instructions(servers_with_counts, cache_model)

    # Register native tools
    @mcp.tool()
    def get_tool_schema(name: str) -> str:
        """Get full description and inputSchema for a specific tool."""
        for tool in backend.get_all_tools():
            if tool["name"] == name:
                return json.dumps({
                    "name": name, "server": tool["_server"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("inputSchema", {})}, indent=2)
        return json.dumps({"error": f"Tool '{name}' not found"})

    @mcp.tool()
    def get_tool_count() -> str:
        """Get count of available tools by server."""
        all_tools = backend.get_all_tools()
        by_server: Dict[str, int] = {}
        for t in all_tools:
            s = t["_server"]
            by_server[s] = by_server.get(s, 0) + 1
        return json.dumps({"total_tools": len(all_tools), "by_server": by_server}, indent=2)

    @mcp.tool()
    def list_all_tools(server: Optional[str] = None) -> str:
        """List all tool names and descriptions grouped by server. Optionally filter by server name."""
        all_tools = backend.get_all_tools()
        by_server: Dict[str, List[Dict[str, str]]] = {}
        for t in all_tools:
            s = t["_server"]
            if server and s != server:
                continue
            name = t["name"]
            if cached_descriptions and s in cached_descriptions and name in cached_descriptions[s]:
                desc = cached_descriptions[s][name]
            else:
                desc = condense_description(t.get("description", ""), max_len=80)
            by_server.setdefault(s, []).append({"name": name, "description": desc})
        return json.dumps({"total_tools": sum(len(v) for v in by_server.values()),
                           "servers": {s: {"tool_count": len(tl), "tools": tl}
                                       for s, tl in by_server.items()}}, indent=2)

    # Register one server-tool per backend server
    for server_name, srv_tools in server_tools_map.items():
        cached = cached_descriptions.get(server_name) if cached_descriptions else None
        desc = build_gateway_description(srv_tools, cached)

        def make_server_handler(sname: str, stool_list: List[Dict[str, Any]]):
            async def handler(tool: Optional[str] = None,
                              arguments: Optional[Dict[str, Any]] = None) -> str:
                if not tool:
                    # List available sub-tools for self-correction
                    info = []
                    for t in stool_list:
                        n = t["name"]
                        d = condense_description(t.get("description", ""), max_len=60)
                        req = t.get("inputSchema", {}).get("required", [])
                        if req:
                            info.append(f"  - {n}: {d} (required: {', '.join(req)})")
                        else:
                            info.append(f"  - {n}: {d}")
                    return f"Missing 'tool' argument. Available sub-tools:\n" + "\n".join(info)
                result = backend.call_tool(tool, arguments or {})
                text = enrich_result(tool, result, backend._described_tools, backend.tool_cache)
                if isinstance(result, dict) and result.get("isError"):
                    text = enrich_error_result(tool, result, backend.tool_cache)
                return text
            handler.__name__ = sname
            handler.__doc__ = desc
            return handler

        fn = make_server_handler(server_name, srv_tools)
        mcp.add_tool(Tool.from_function(fn, name=server_name, description=desc))


# ─── Build Cache ───

def compute_config_hash(config_path: Path) -> str:
    """Compute SHA-256 hash of mcp.json content."""
    content = config_path.read_bytes()
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def load_build_cache(
    config_path: Path, config: Dict[str, Any], tools: List[Dict[str, Any]]
) -> Optional[Dict[str, Dict[str, str]]]:
    """Load and validate build cache. Returns {server: {tool: desc}} or None."""
    cache_file = config_path.parent / ".toolmux_cache.json"
    if not cache_file.exists():
        return None
    try:
        cache = json.loads(cache_file.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: invalid build cache: {e}", file=sys.stderr)
        return None
    # Validate config hash
    current_hash = compute_config_hash(config_path)
    if cache.get("config_hash") != current_hash:
        return None
    # Validate tool counts per server
    actual_counts: Dict[str, int] = {}
    for tool in tools:
        s = tool["_server"]
        actual_counts[s] = actual_counts.get(s, 0) + 1
    for server_name, server_data in cache.get("servers", {}).items():
        if server_data.get("tool_count") != actual_counts.get(server_name, 0):
            return None
    # Return descriptions
    result: Dict[str, Dict[str, str]] = {}
    for server_name, server_data in cache.get("servers", {}).items():
        result[server_name] = server_data.get("descriptions", {})
    return result


def _get_cache_model(config_path: Path) -> Optional[str]:
    """Read the model field from the cache file, or None if no cache."""
    cache_file = config_path.parent / ".toolmux_cache.json"
    if not cache_file.exists():
        return None
    try:
        return json.loads(cache_file.read_text()).get("model")
    except Exception:
        return None


def _auto_generate_cache(config_path: Path, tools: List[Dict[str, Any]]) -> None:
    """Auto-generate algorithmic cache on first run or when stale. Silent, no user action needed."""
    server_tools_map: Dict[str, List[Dict[str, Any]]] = {}
    for tool in tools:
        server_tools_map.setdefault(tool["_server"], []).append(tool)
    cache_data = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_hash": compute_config_hash(config_path),
        "model": "algorithmic",
        "servers": {},
    }
    for server_name, srv_tools in server_tools_map.items():
        cache_data["servers"][server_name] = {
            "tool_count": len(srv_tools),
            "descriptions": {t["name"]: condense_description(t.get("description", ""), max_len=60)
                             for t in srv_tools},
        }
    cache_file = config_path.parent / ".toolmux_cache.json"
    try:
        cache_file.write_text(json.dumps(cache_data, indent=2))
    except OSError:
        pass  # Non-fatal — algorithmic fallback still works without cache file


def generate_build_cache(config: Dict[str, Any], config_path: Path) -> None:
    """Generate build cache by starting backends and writing a skeleton for the agent to fill."""
    servers_config = config.get("servers", {})
    backend = BackendManager(servers_config)
    backend.initialize_all_async()
    tools = backend.wait_for_tools(timeout=30)

    server_tools_map: Dict[str, List[Dict[str, Any]]] = {}
    for tool in tools:
        server_tools_map.setdefault(tool["_server"], []).append(tool)

    # Write skeleton cache with algorithmic descriptions as starting point
    cache_data: Dict[str, Any] = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_hash": compute_config_hash(config_path),
        "model": "algorithmic",
        "servers": {},
    }
    for server_name, srv_tools in server_tools_map.items():
        descriptions = {}
        for t in srv_tools:
            descriptions[t["name"]] = condense_description(t.get("description", ""), max_len=60)
        cache_data["servers"][server_name] = {
            "tool_count": len(srv_tools),
            "descriptions": descriptions,
        }

    cache_file = config_path.parent / ".toolmux_cache.json"
    cache_file.write_text(json.dumps(cache_data, indent=2))
    print(f"Build cache written to {cache_file} ({len(tools)} tools, algorithmic descriptions)")
    print(f"Use optimize_descriptions(action='generate') via an agent for LLM-quality descriptions")
    backend.shutdown()


def save_build_cache(config_path: Path, descriptions: Dict[str, Dict[str, str]],
                     tools: List[Dict[str, Any]]) -> str:
    """Save agent-generated descriptions to the build cache file."""
    server_tools_map: Dict[str, int] = {}
    for tool in tools:
        s = tool["_server"]
        server_tools_map[s] = server_tools_map.get(s, 0) + 1

    cache_data = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_hash": compute_config_hash(config_path),
        "model": "agent-generated",
        "servers": {},
    }
    for server_name, count in server_tools_map.items():
        cache_data["servers"][server_name] = {
            "tool_count": count,
            "descriptions": descriptions.get(server_name, {}),
        }

    cache_file = config_path.parent / ".toolmux_cache.json"
    cache_file.write_text(json.dumps(cache_data, indent=2))
    total = sum(len(d) for d in descriptions.values())
    return f"Cache saved to {cache_file} ({total} descriptions)"


# ─── Configuration Loading ───

def setup_first_run():
    """Set up configuration directory and example config on first run."""
    config_dir = Path.home() / "shared" / "toolmux"
    config_file = config_dir / "mcp.json"
    examples_dir = config_dir / "examples"
    if config_file.exists():
        return config_file
    print(f"ToolMux v{VERSION} - First run detected")
    config_dir.mkdir(exist_ok=True)
    print(f"✅ Created configuration directory: {config_dir}")
    examples_dir.mkdir(exist_ok=True)
    try:
        package_dir = Path(__file__).parent
        pkg_examples = package_dir / "examples"
        if pkg_examples.exists():
            for f in pkg_examples.glob("*.json"):
                shutil.copy2(f, examples_dir / f.name)
            print(f"✅ Installed example configurations: {examples_dir}")
        else:
            create_basic_examples(examples_dir)
            print(f"✅ Created basic example configurations: {examples_dir}")
        pkg_prompt = package_dir / "Prompt"
        if pkg_prompt.exists():
            shutil.copytree(pkg_prompt, config_dir / "Prompt", dirs_exist_ok=True)
            print(f"✅ Installed agent instructions: {config_dir / 'Prompt'}")
        pkg_scripts = package_dir / "scripts"
        if pkg_scripts.exists():
            shutil.copytree(pkg_scripts, config_dir / "scripts", dirs_exist_ok=True)
            print(f"✅ Installed scripts: {config_dir / 'scripts'}")
    except Exception as e:
        create_basic_examples(examples_dir)
        print(f"⚠️  Could not copy package resources: {e}")
    default_config = {"servers": {"filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", str(Path.home())],
        "description": "Local filesystem access"}}}
    with open(config_file, 'w') as f:
        json.dump(default_config, f, indent=2)
    print(f"✅ Installed default configuration: {config_file}")
    print("\n📝 Edit ~/toolmux/mcp.json to add your MCP servers")
    print("📚 See ~/toolmux/examples/ for configuration templates")
    print(f"🚀 Run 'toolmux' again to start with your configured servers\n")
    return config_file


def create_basic_examples(examples_dir: Path):
    """Create basic example configurations."""
    examples = {
        "filesystem.json": {"servers": {"filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
            "description": "Local filesystem access"}}},
        "brave-search.json": {"servers": {"brave-search": {
            "command": "uvx", "args": ["mcp-server-brave-search"],
            "env": {"BRAVE_API_KEY": "your-brave-api-key-here"},
            "description": "Web search using Brave Search API"}}},
        "mixed-servers.json": {"servers": {
            "filesystem": {"command": "npx",
                           "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
                           "description": "Local filesystem access via stdio"},
            "remote-api": {"transport": "http", "base_url": "https://api.example.com/mcp",
                           "headers": {"Authorization": "Bearer your-token-here"},
                           "timeout": 30, "description": "Remote HTTP MCP server"}}},
    }
    for filename, cfg in examples.items():
        with open(examples_dir / filename, 'w') as f:
            json.dump(cfg, f, indent=2)


def find_config_file(config_path: Optional[str] = None) -> Path:
    """Find configuration file using discovery order."""
    if config_path:
        p = Path(config_path)
        if not p.exists():
            print(f"Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        return p
    for p in [Path.cwd() / "mcp.json",
              Path.home() / "shared" / "toolmux" / "mcp.json",
              Path.home() / "toolmux" / "mcp.json"]:
        if p.exists():
            return p
    return setup_first_run()


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load full configuration from mcp.json (including mode and servers)."""
    config_file = find_config_file(config_path)
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        config["_config_path"] = str(config_file)
        return config
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in config file: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading config file: {e}", file=sys.stderr)
        sys.exit(1)


# ─── Bundle Resolution ───

def resolve_bundle(server_name: str) -> Optional[Dict[str, Any]]:
    """Resolve server config from installed MCP bundle/config files.

    Checks multiple sources in priority order to find the correct launch
    config for a server. Supports mcp-registry bundles and standard
    MCP config files (Claude Desktop, Cursor, XDG mcp.json).

    Returns a dict with 'command' and 'args' keys, or None if not found.
    """
    home = Path.home()

    # 1. mcp-registry bundles (genericBundle format)
    for bundle_dir in [
        home / ".config" / "smithy-mcp" / "bundles",  # mcp-registry install
        home / ".aim" / "bundles",                      # user bundles
    ]:
        result = _read_generic_bundle(bundle_dir / f"{server_name}.json")
        if result:
            return result

    # 2. Standard MCP config files (mcpServers format)
    #    Used by Claude Desktop, Cursor, VS Code, fastmcp install, etc.
    for config_file in [
        home / ".config" / "mcp" / "config.json",                                    # XDG standard
        home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",  # macOS Claude
        home / ".config" / "Claude" / "claude_desktop_config.json",                   # Linux Claude
        home / ".cursor" / "mcp.json",                                                # Cursor
    ]:
        result = _read_mcp_config_server(config_file, server_name)
        if result:
            return result

    return None


def _read_generic_bundle(path: Path) -> Optional[Dict[str, Any]]:
    """Read an mcp-registry genericBundle JSON file."""
    if not path.exists():
        return None
    try:
        bundle = json.loads(path.read_text())
        run_config = bundle.get("genericBundle", {}).get("run", {})
        executable = run_config.get("executable")
        if executable:
            return {"command": executable, "args": run_config.get("args", []),
                    "source": str(path)}
    except Exception:
        pass
    return None


def _read_mcp_config_server(path: Path, server_name: str) -> Optional[Dict[str, Any]]:
    """Read a server entry from a standard mcpServers config file."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        servers = data.get("mcpServers", {})
        entry = servers.get(server_name)
        if not entry:
            return None
        # stdio server
        if "command" in entry:
            return {"command": entry["command"], "args": entry.get("args", []),
                    "source": str(path)}
        # SSE/HTTP server
        if "url" in entry:
            return {"command": "uvx", "args": ["fastmcp", "run", entry["url"]],
                    "source": str(path)}
    except Exception:
        pass
    return None


# ─── Server Management ───

def _handle_manage(args, config: Dict[str, Any], config_path: Path,
                   servers: Dict[str, Any]):
    """Handle --manage operations: list, add, remove, validate, test."""
    action = args.manage

    if action == "list":
        if not servers:
            print("No servers configured.")
            print(f"Config: {config_path}")
            print(f"Add one: toolmux --manage add --server-name NAME --server-command CMD")
            return
        print(f"Configured servers ({config_path}):\n")
        for name, cfg in servers.items():
            transport = cfg.get("transport", "stdio")
            cmd = cfg.get("command", cfg.get("base_url", "?"))
            desc = cfg.get("description", "")
            print(f"  {name}")
            print(f"    transport: {transport}, command: {cmd}")
            if desc:
                print(f"    description: {desc}")
        print(f"\n{len(servers)} server(s) configured")

    elif action == "add":
        name = args.server_name
        cmd = args.server_command
        if not name:
            print("Usage: toolmux --manage add --server-name NAME --server-command CMD "
                  "[--server-args ARG1 ARG2] [--server-description DESC]", file=sys.stderr)
            sys.exit(1)
        if name in servers:
            print(f"Server '{name}' already exists. Remove it first or use a different name.",
                  file=sys.stderr)
            sys.exit(1)
        # If no command provided, try to resolve from bundle
        if not cmd:
            bundle = resolve_bundle(name)
            if bundle:
                cmd = bundle["command"]
                if not args.server_args:
                    args.server_args = bundle["args"]
                print(f"   Resolved from bundle: {bundle['source']}")
            else:
                print("Usage: toolmux --manage add --server-name NAME --server-command CMD "
                      "[--server-args ARG1 ARG2] [--server-description DESC]", file=sys.stderr)
                print(f"   (No bundle found for '{name}' — command is required)", file=sys.stderr)
                sys.exit(1)
        # Validate command exists
        if not shutil.which(cmd):
            # Try bundle fallback if user provided a command that doesn't exist
            bundle = resolve_bundle(name)
            if bundle and shutil.which(bundle["command"]):
                print(f"⚠️  Command '{cmd}' not found, but bundle has '{bundle['command']}'")
                print(f"   Using bundle config from: {bundle['source']}")
                cmd = bundle["command"]
                if not args.server_args:
                    args.server_args = bundle["args"]
            else:
                print(f"⚠️  Warning: command '{cmd}' not found in PATH")
        entry: Dict[str, Any] = {"command": cmd, "args": args.server_args, "timeout": 120000}
        if args.server_description:
            entry["description"] = args.server_description
        config.setdefault("servers", {})[name] = entry
        _save_config(config, config_path)
        print(f"✅ Added server '{name}' → {cmd} {' '.join(args.server_args)}")
        print(f"   Config: {config_path}")
        print(f"   Test it: toolmux --manage test --server-name {name}")

    elif action == "remove":
        name = args.server_name
        if not name:
            print("Usage: toolmux --manage remove --server-name NAME", file=sys.stderr)
            sys.exit(1)
        if name not in servers:
            print(f"Server '{name}' not found. Available: {', '.join(servers.keys())}",
                  file=sys.stderr)
            sys.exit(1)
        del config["servers"][name]
        _save_config(config, config_path)
        print(f"✅ Removed server '{name}'")

    elif action == "validate":
        print(f"Validating config: {config_path}\n")
        errors = 0
        fixable = []
        for name, cfg in servers.items():
            transport = cfg.get("transport", "stdio")
            if transport == "http":
                url = cfg.get("base_url")
                if not url:
                    print(f"  ❌ {name}: missing base_url for HTTP transport")
                    errors += 1
                else:
                    print(f"  ✅ {name}: HTTP → {url}")
            else:
                cmd = cfg.get("command")
                if not cmd:
                    print(f"  ❌ {name}: missing command")
                    errors += 1
                elif not shutil.which(cmd):
                    # Check if a bundle has the correct config
                    bundle = resolve_bundle(name)
                    if bundle and shutil.which(bundle["command"]):
                        print(f"  ⚠️  {name}: command '{cmd}' not found, "
                              f"but bundle has '{bundle['command']}' — fixable")
                        fixable.append((name, bundle))
                    else:
                        print(f"  ⚠️  {name}: command '{cmd}' not found in PATH")
                else:
                    print(f"  ✅ {name}: {cmd} (found)")
        if fixable:
            print(f"\n{len(fixable)} server(s) can be auto-fixed from bundles:")
            for name, bundle in fixable:
                print(f"  {name}: {bundle['command']} {' '.join(bundle['args'])}")
            print(f"\nRun with --manage fix to apply bundle configs (not yet implemented)")
        print(f"\n{len(servers)} server(s), {errors} error(s)")
        if errors:
            sys.exit(1)

    elif action == "test":
        name = args.server_name
        targets = {name: servers[name]} if name and name in servers else servers
        if name and name not in servers:
            print(f"Server '{name}' not found.", file=sys.stderr)
            sys.exit(1)
        print(f"Testing {len(targets)} server(s)...\n")
        bm = BackendManager(targets)
        bm.initialize_all_async()
        tools = bm.wait_for_tools(timeout=15)
        by_server: Dict[str, int] = {}
        for t in tools:
            s = t["_server"]
            by_server[s] = by_server.get(s, 0) + 1
        for sname in targets:
            count = by_server.get(sname, 0)
            if count > 0:
                print(f"  ✅ {sname}: {count} tools discovered")
            else:
                # Diagnose why it failed
                cfg = targets[sname]
                cmd = cfg.get("command", "")
                if cfg.get("transport") == "http":
                    print(f"  ❌ {sname}: no tools (HTTP endpoint may be unreachable)")
                elif not shutil.which(cmd):
                    bundle = resolve_bundle(sname)
                    if bundle and shutil.which(bundle["command"]):
                        print(f"  ❌ {sname}: command '{cmd}' not found — "
                              f"bundle suggests '{bundle['command']}' "
                              f"{' '.join(bundle['args'])}")
                    else:
                        print(f"  ❌ {sname}: command '{cmd}' not found in PATH")
                else:
                    print(f"  ❌ {sname}: server started but returned 0 tools "
                          f"(may need specific args — check --help)")
        print(f"\nTotal: {len(tools)} tools from {len(by_server)} server(s)")
        bm.shutdown()


def _save_config(config: Dict[str, Any], config_path: Path):
    """Save config back to mcp.json, preserving non-server fields."""
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


# ─── CLI Entry Point ───

def main():
    parser = argparse.ArgumentParser(
        description="ToolMux - MCP server aggregation with FastMCP foundation",
        epilog="For more information, visit: https://github.com/subnetangel/ToolMux")
    parser.add_argument("--config", help="Path to MCP configuration file")
    parser.add_argument("--version", action="version", version=f"ToolMux {VERSION}")
    parser.add_argument("--mode", choices=["proxy", "meta", "gateway"],
                        help="Operating mode (default: gateway)")
    parser.add_argument("--list-servers", action="store_true",
                        help="List configured servers and exit")
    parser.add_argument("--build-cache", action="store_true",
                        help="Generate LLM build cache for descriptions and exit")
    parser.add_argument("--manage", nargs="?", const="list",
                        choices=["list", "add", "remove", "validate", "test"],
                        help="Manage servers: list, add, remove, validate, or test")
    parser.add_argument("--server-name", help="Server name for --manage add/remove")
    parser.add_argument("--server-command", help="Server command for --manage add")
    parser.add_argument("--server-args", nargs="*", default=[], help="Server args for --manage add")
    parser.add_argument("--server-description", help="Server description for --manage add")
    args = parser.parse_args()

    config = load_config(args.config)
    config_path = Path(config.pop("_config_path"))
    servers = config.get("servers", {})

    if args.list_servers:
        print("Configured MCP servers:")
        for name, cfg in servers.items():
            transport = cfg.get("transport", "stdio")
            if transport == "http":
                endpoint = cfg.get("base_url", "unknown")
            else:
                endpoint = f"{cfg.get('command', 'unknown')} {' '.join(cfg.get('args', []))}"
            print(f"  {name}: {transport} - {endpoint}")
        return

    if args.manage:
        _handle_manage(args, config, config_path, servers)
        return

    if not servers:
        print("No servers configured. Edit your mcp.json file.", file=sys.stderr)
        sys.exit(1)

    if args.build_cache:
        generate_build_cache(config, config_path)
        return

    # Mode precedence: CLI > config > default (gateway)
    mode = args.mode or config.get("mode", "gateway")

    # Proxy mode uses fastmcp's native create_proxy() for true transparent proxying
    if mode == "proxy":
        run_proxy_native(servers, config, config_path)
        return

    backend = BackendManager(servers)

    # Determine instructions for FastMCP constructor
    cache_model = _get_cache_model(config_path)
    if mode == "meta":
        instructions = INSTRUCTIONS_META_TEMPLATE.format(optimization_hint=_optimization_hint(cache_model))
    elif mode == "proxy":
        instructions = INSTRUCTIONS_PROXY_TEMPLATE.format(optimization_hint=_optimization_hint(cache_model))
    else:
        instructions = ""  # Gateway instructions set dynamically during registration

    mcp = FastMCP(name="ToolMux", instructions=instructions, version=VERSION)

    # Try to load tools from build cache first (instant, no backend needed).
    # This allows mcp.run() to start immediately and respond to initialize.
    cached_descriptions = None
    tools = []
    cache_file = config_path.parent / ".toolmux_cache.json"
    if cache_file.exists():
        try:
            cache_data = json.loads(cache_file.read_text())
            current_hash = compute_config_hash(config_path)
            if cache_data.get("config_hash") == current_hash:
                # Build synthetic tool list from cache for registration
                for server_name, server_data in cache_data.get("servers", {}).items():
                    for tool_name, desc in server_data.get("descriptions", {}).items():
                        tools.append({
                            "name": tool_name,
                            "_server": server_name,
                            "_transport": "stdio",
                            "description": desc,
                            "inputSchema": {"type": "object", "properties": {}},
                        })
                cached_descriptions = {}
                for server_name, server_data in cache_data.get("servers", {}).items():
                    cached_descriptions[server_name] = server_data.get("descriptions", {})
                cache_model = cache_data.get("model")
        except Exception:
            pass  # Fall through to live init

    if not tools:
        # No cache — register server names as placeholders immediately so
        # mcp.run() starts without delay. Backends init in background.
        # First tool CALL will wait for the backend, not the init handshake.
        for server_name in servers:
            tools.append({
                "name": server_name, "_server": server_name,
                "_transport": "stdio",
                "description": servers[server_name].get("description", "MCP server (loading)"),
                "inputSchema": {"type": "object", "properties": {}},
            })
        cached_descriptions = {s: {} for s in servers}
        backend.initialize_all_async()
        # Auto-generate cache after backends finish (non-blocking)
        def _deferred_cache_gen():
            backend._init_complete.wait(timeout=60)
            backend.persist_fixes(config, config_path)
            real_tools = backend.get_all_tools()
            if real_tools:
                try:
                    _auto_generate_cache(config_path, real_tools)
                except Exception:
                    pass
        threading.Thread(target=_deferred_cache_gen, daemon=True).start()
    else:
        # Cache loaded — start backends in background for actual tool calls
        backend.initialize_all_async()

    # Stash tools in config for build_cache tool access
    config["_backend_tools"] = tools

    # Register mode-specific tools
    if mode == "meta":
        register_meta_tools(mcp, backend, cached_descriptions)
    elif mode == "proxy":
        register_proxy_tools(mcp, backend, cached_descriptions, preloaded_tools=tools)
    else:
        register_gateway_tools(mcp, backend, cached_descriptions, cache_model, preloaded_tools=tools)

    # Register manage_servers in all modes
    register_manage_tool(mcp, config_path, config)

    try:
        mcp.run(show_banner=False)
    except BaseExceptionGroup as eg:
        if not _is_client_disconnect(eg):
            raise
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        backend.shutdown()


if __name__ == "__main__":
    main()
