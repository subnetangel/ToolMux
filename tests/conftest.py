"""Shared fixtures for ToolMux v2.0 test suite."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

import pytest

TOOLMUX_DIR = Path(__file__).parent.parent


# ─── Echo MCP Server Script ───

ECHO_SERVER_SCRIPT = '''\
import sys, json
while True:
    line = sys.stdin.readline()
    if not line: break
    req = json.loads(line)
    m = req.get("method", "")
    rid = req.get("id")
    if m == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "echo", "version": "1.0"}}}))
    elif m == "notifications/initialized":
        pass
    elif m == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"tools": [
            {"name": "echo_tool", "description": "Echo back the input arguments. This is a test tool for validation purposes.",
             "inputSchema": {"type": "object", "properties": {
                 "message": {"type": "string", "description": "Message to echo back"}},
                 "required": ["message"]}},
            {"name": "reverse_tool", "description": "Reverse a string. Only works within allowed directories. Use this tool when you need to reverse text.",
             "inputSchema": {"type": "object", "properties": {
                 "text": {"type": "string", "description": "Text to reverse"},
                 "uppercase": {"type": "boolean", "description": "Convert to uppercase", "default": False}},
                 "required": ["text"]}},
            {"name": "count_tool", "description": "Count items in a list.",
             "inputSchema": {"type": "object", "properties": {
                 "items": {"type": "array", "items": {"type": "string"}, "description": "Items to count"}},
                 "required": ["items"]}}
        ]}}))
    elif m == "tools/call":
        args = req.get("params", {}).get("arguments", {})
        name = req.get("params", {}).get("name", "")
        if name == "reverse_tool":
            text = args.get("text", "")
            if args.get("uppercase"):
                text = text.upper()
            result_text = text[::-1]
        elif name == "count_tool":
            result_text = str(len(args.get("items", [])))
        else:
            result_text = json.dumps(args)
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": result_text}]}}))
    sys.stdout.flush()
'''


@pytest.fixture
def echo_server_path(tmp_path):
    """Create an echo MCP server script and return its path."""
    script = tmp_path / "echo_server.py"
    script.write_text(ECHO_SERVER_SCRIPT)
    return str(script)


@pytest.fixture
def test_config(tmp_path, echo_server_path):
    """Create a test mcp.json config pointing to the echo server."""
    def _make(mode=None, extra_servers=None):
        config = {"servers": {
            "echo": {"command": sys.executable, "args": [echo_server_path]}
        }}
        if extra_servers:
            config["servers"].update(extra_servers)
        if mode:
            config["mode"] = mode
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps(config))
        return path
    return _make


@pytest.fixture
def dual_server_config(tmp_path):
    """Create config with two echo servers (for collision testing)."""
    s1 = tmp_path / "echo1.py"
    s2 = tmp_path / "echo2.py"
    s1.write_text(ECHO_SERVER_SCRIPT)
    # Second server with overlapping tool name
    s2.write_text(ECHO_SERVER_SCRIPT.replace('"echo"', '"echo2"'))
    config = {"servers": {
        "server_a": {"command": sys.executable, "args": [str(s1)]},
        "server_b": {"command": sys.executable, "args": [str(s2)]},
    }}
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps(config))
    return path


def send_jsonrpc(proc, method, params=None, req_id=1):
    """Send JSON-RPC via newline-delimited JSON (FastMCP stdio)."""
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params:
        payload["params"] = params
    proc.stdin.write((json.dumps(payload) + "\n").encode())
    proc.stdin.flush()
    if req_id is None:
        return None
    line = proc.stdout.readline()
    return json.loads(line.decode()) if line else None


def start_toolmux(mode=None, config_path=None):
    """Start ToolMux as a subprocess."""
    cmd = [sys.executable, "-m", "toolmux"]
    if mode:
        cmd += ["--mode", mode]
    if config_path:
        cmd += ["--config", str(config_path)]
    env = {**os.environ, "PYTHONPATH": str(TOOLMUX_DIR),
           "FASTMCP_SHOW_SERVER_BANNER": "false"}
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, cwd=str(TOOLMUX_DIR), env=env)
    time.sleep(2)
    return proc


def init_toolmux(proc):
    """Send initialize + initialized notification."""
    resp = send_jsonrpc(proc, "initialize", {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"}})
    send_jsonrpc(proc, "notifications/initialized", req_id=None)
    time.sleep(0.5)
    return resp


def tool_dict(name="test_tool", server="test_server", desc="A test tool.",
              schema=None):
    """Build a tool dict for unit testing."""
    return {
        "name": name,
        "description": desc,
        "inputSchema": schema or {
            "type": "object",
            "properties": {"x": {"type": "string", "description": "A param"}},
            "required": ["x"]},
        "_server": server,
        "_transport": "stdio",
    }
