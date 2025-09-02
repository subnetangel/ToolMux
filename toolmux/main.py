#!/usr/bin/env python3
"""
ToolMux - Efficient MCP server aggregation with on-demand loading
Reduces schema token overhead by 98% while maintaining full functionality
Supports both stdio and HTTP/SSE MCP servers
"""
import json
import sys
import subprocess
import os
import argparse
import asyncio
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
import httpx
import time

class HttpMcpClient:
    """HTTP/SSE MCP client for remote MCP servers"""
    
    def __init__(self, base_url: str, headers: Optional[Dict[str, str]] = None, 
                 timeout: int = 30, sse_endpoint: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.headers = headers or {}
        self.timeout = timeout
        self.sse_endpoint = sse_endpoint or "/sse"
        self.client = httpx.Client(
            headers=self.headers, 
            timeout=httpx.Timeout(timeout, connect=timeout/2)
        )
        self._initialized = False
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        
    def close(self):
        """Clean up HTTP client resources"""
        if hasattr(self, 'client'):
            self.client.close()
    
    def call_rpc(self, method: str, params: Optional[Dict[str, Any]] = None, 
                 request_id: int = 1) -> Dict[str, Any]:
        """Make JSON-RPC call to HTTP MCP server"""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": request_id
        }
        if params:
            payload["params"] = params
            
        try:
            # Try standard MCP HTTP endpoint first
            response = self.client.post(f"{self.base_url}/mcp", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Fallback to /rpc endpoint (alternative convention)
                try:
                    response = self.client.post(f"{self.base_url}/rpc", json=payload)
                    response.raise_for_status()
                    return response.json()
                except Exception:
                    pass
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": f"HTTP {e.response.status_code}: {str(e)}",
                    "data": {"transport": "http", "url": self.base_url}
                }
            }
        except httpx.TimeoutException:
            return {
                "jsonrpc": "2.0", 
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": f"Request timeout after {self.timeout}s",
                    "data": {"transport": "http", "url": self.base_url}
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id, 
                "error": {
                    "code": -32603,
                    "message": f"Connection error: {str(e)}",
                    "data": {"transport": "http", "url": self.base_url}
                }
            }
    
    def initialize(self) -> bool:
        """Initialize the HTTP MCP connection"""
        if self._initialized:
            return True
            
        # Send initialize request
        init_response = self.call_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ToolMux", "version": "1.2.1"}
        })
        
        if "error" in init_response:
            return False
            
        # Send initialized notification
        self.call_rpc("notifications/initialized")
        self._initialized = True
        return True
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """Get available tools from HTTP MCP server"""
        if not self.initialize():
            return []
            
        response = self.call_rpc("tools/list")
        if "error" in response:
            return []
            
        result = response.get("result", {})
        return result.get("tools", [])
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on the HTTP MCP server"""
        if not self.initialize():
            return {"error": "Failed to initialize HTTP MCP connection"}
            
        response = self.call_rpc("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
        
        if "error" in response:
            return {"error": response["error"]["message"]}
            
        return response.get("result", {"error": "No result returned"})

class ToolMux:
    def __init__(self, servers_config: Dict[str, Dict[str, Any]]):
        self.servers = servers_config
        self.server_processes = {}
        self.tool_cache = None
    
    def start_server(self, server_name: str):
        if server_name in self.server_processes:
            return self.server_processes[server_name]
        
        server_config = self.servers[server_name]
        
        # Check for HTTP transport
        if server_config.get("transport") == "http":
            try:
                client = HttpMcpClient(
                    base_url=server_config["base_url"],
                    headers=server_config.get("headers"),
                    timeout=server_config.get("timeout", 30),
                    sse_endpoint=server_config.get("sse_endpoint")
                )
                self.server_processes[server_name] = client
                return client
            except Exception as e:
                print(f"Failed to create HTTP MCP client for {server_name}: {e}", file=sys.stderr)
                return None
        
        # Default to stdio transport
        env = os.environ.copy()
        env.update(server_config.get("env", {}))
        
        try:
            process = subprocess.Popen(
                [server_config["command"]] + server_config["args"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                cwd=server_config.get("cwd")
            )
            self.server_processes[server_name] = process
            return process
        except Exception as e:
            print(f"Failed to start stdio MCP server {server_name}: {e}", file=sys.stderr)
            return None
    
    def get_all_tools(self):
        if self.tool_cache is not None:
            return self.tool_cache
        
        all_tools = []
        for server_name in self.servers:
            try:
                server = self.start_server(server_name)
                if not server:
                    continue
                
                # Handle HTTP MCP client
                if isinstance(server, HttpMcpClient):
                    tools = server.get_tools()
                    for tool in tools:
                        tool["_server"] = server_name
                        tool["_transport"] = "http"
                        all_tools.append(tool)
                    continue
                
                # Handle stdio subprocess
                init_request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "ToolMux", "version": "1.2.1"}
                    }
                }
                
                server.stdin.write(json.dumps(init_request) + "\n")
                server.stdin.flush()
                server.stdout.readline()
                
                init_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                server.stdin.write(json.dumps(init_notif) + "\n")
                server.stdin.flush()
                
                tools_request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
                server.stdin.write(json.dumps(tools_request) + "\n")
                server.stdin.flush()
                
                response_line = server.stdout.readline()
                if response_line:
                    response = json.loads(response_line)
                    if "result" in response and "tools" in response["result"]:
                        for tool in response["result"]["tools"]:
                            tool["_server"] = server_name
                            tool["_transport"] = "stdio"
                            all_tools.append(tool)
            except Exception as e:
                print(f"Error getting tools from {server_name}: {e}", file=sys.stderr)
                continue
        
        self.tool_cache = all_tools
        return all_tools
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]):
        tools = self.get_all_tools()
        target_server = None
        
        for tool in tools:
            if tool["name"] == tool_name:
                target_server = tool["_server"]
                break
        
        if not target_server:
            return {"error": f"Tool '{tool_name}' not found"}
        
        try:
            server = self.server_processes.get(target_server)
            if not server:
                return {"error": f"Server '{target_server}' not available"}
            
            # Handle HTTP MCP client
            if isinstance(server, HttpMcpClient):
                return server.call_tool(tool_name, arguments)
            
            # Handle stdio subprocess
            request = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments}
            }
            
            server.stdin.write(json.dumps(request) + "\n")
            server.stdin.flush()
            
            response_line = server.stdout.readline()
            if response_line:
                response = json.loads(response_line)
                return response.get("result", {"error": "No result"})
            
        except Exception as e:
            return {"error": str(e)}
        
        return {"error": "Tool execution failed"}
    
    def handle_request(self, request):
        method = request.get("method", "")
        params = request.get("params", {})
        
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "ToolMux", "version": "1.2.1"}
                }
            }
        
        elif method in ["initialized", "notifications/initialized"]:
            return None
        
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {
                    "tools": [
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
                }
            }
        
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            
            if tool_name == "catalog_tools":
                tools = self.get_all_tools()
                catalog = []
                for tool in tools:
                    desc = tool.get("description", "")
                    catalog.append({
                        "name": tool["name"],
                        "server": tool["_server"],
                        "summary": desc[:80] + "..." if len(desc) > 80 else desc
                    })
                
                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {"content": [{"type": "text", "text": json.dumps(catalog, indent=2)}]}
                }
            
            elif tool_name == "get_tool_schema":
                target_tool = tool_args.get("name", "")
                tools = self.get_all_tools()
                
                for tool in tools:
                    if tool["name"] == target_tool:
                        result = {
                            "name": target_tool,
                            "server": tool["_server"],
                            "input_schema": tool.get("inputSchema", {})
                        }
                        
                        return {
                            "jsonrpc": "2.0",
                            "id": request.get("id"),
                            "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
                        }
                
                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {"content": [{"type": "text", "text": f"Tool '{target_tool}' not found"}]}
                }
            
            elif tool_name == "invoke":
                target_tool = tool_args.get("name", "")
                target_args = tool_args.get("args", {})
                
                result = self.call_tool(target_tool, target_args)
                
                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
                }
            
            elif tool_name == "get_tool_count":
                tools = self.get_all_tools()
                servers = {}
                for tool in tools:
                    server = tool["_server"]
                    servers[server] = servers.get(server, 0) + 1
                
                result = {
                    "total_tools": len(tools),
                    "by_server": servers
                }
                
                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
                }
        
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }
    
    def run(self):
        # Check if stdin is a terminal (interactive mode)
        if sys.stdin.isatty():
            print("ToolMux MCP Server - Waiting for JSON-RPC messages", file=sys.stderr)
            print("💡 Tip: Use 'uvx toolmux --help' for CLI commands", file=sys.stderr)
            print("📖 Send MCP protocol messages or press Ctrl+C to exit", file=sys.stderr)
        
        try:
            while True:
                line = sys.stdin.readline()
                if not line:
                    break
                
                # Skip empty lines
                line = line.strip()
                if not line:
                    continue
                
                try:
                    request = json.loads(line)
                    response = self.handle_request(request)
                    
                    if response is not None:
                        print(json.dumps(response))
                        sys.stdout.flush()
                        
                except Exception as e:
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32603, "message": str(e)}
                    }
                    print(json.dumps(error_response))
                    sys.stdout.flush()
        
        finally:
            for server in self.server_processes.values():
                try:
                    if isinstance(server, HttpMcpClient):
                        server.close()
                    else:
                        server.terminate()
                except:
                    pass

def setup_first_run():
    """Set up configuration directory and example config on first run"""
    config_dir = Path.home() / "toolmux"
    config_file = config_dir / "mcp.json"
    examples_dir = config_dir / "examples"
    
    if config_file.exists():
        return config_file
    
    # First run setup
    print("ToolMux v1.2.1 - First run detected")
    
    # Create config directory
    config_dir.mkdir(exist_ok=True)
    print(f"✅ Created configuration directory: {config_dir}")
    
    # Create examples directory
    examples_dir.mkdir(exist_ok=True)
    
    # Copy all bundled resources from package
    try:
        package_dir = Path(__file__).parent
        
        # Copy examples
        package_examples = package_dir / "examples"
        if package_examples.exists():
            for example_file in package_examples.glob("*.json"):
                shutil.copy2(example_file, examples_dir / example_file.name)
            print(f"✅ Installed example configurations: {examples_dir}")
        else:
            # Create basic examples if package examples not available
            create_basic_examples(examples_dir)
            print(f"✅ Created basic example configurations: {examples_dir}")
        
        # Copy Prompt folder
        package_prompt = package_dir / "Prompt"
        user_prompt = config_dir / "Prompt"
        if package_prompt.exists():
            shutil.copytree(package_prompt, user_prompt, dirs_exist_ok=True)
            print(f"✅ Installed agent instructions: {user_prompt}")
        
        # Copy scripts folder
        package_scripts = package_dir / "scripts"
        user_scripts = config_dir / "scripts"
        if package_scripts.exists():
            shutil.copytree(package_scripts, user_scripts, dirs_exist_ok=True)
            print(f"✅ Installed scripts: {user_scripts}")
            
    except Exception as e:
        # Create basic examples if package resources not available
        create_basic_examples(examples_dir)
        print(f"⚠️  Could not copy package resources: {e}")
        print(f"✅ Created basic example configurations: {examples_dir}")
    
    # Create default config
    default_config = {
        "servers": {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", str(Path.home())],
                "description": "Local filesystem access - read, write, and manage files"
            }
        }
    }
    
    with open(config_file, 'w') as f:
        json.dump(default_config, f, indent=2)
    
    print(f"✅ Installed default configuration: {config_file}")
    print()
    print("📝 Edit ~/toolmux/mcp.json to add your MCP servers")
    print("📚 See ~/toolmux/examples/ for configuration templates")
    print("🚀 Run 'toolmux' again to start with your configured servers")
    print()
    
    return config_file

def create_basic_examples(examples_dir: Path):
    """Create basic example configurations"""
    examples = {
        "filesystem.json": {
            "servers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
                    "description": "Local filesystem access - read, write, and manage files"
                }
            }
        },
        "brave-search.json": {
            "servers": {
                "brave-search": {
                    "command": "uvx",
                    "args": ["mcp-server-brave-search"],
                    "env": {"BRAVE_API_KEY": "your-brave-api-key-here"},
                    "description": "Web search using Brave Search API"
                }
            }
        },
        "mixed-servers.json": {
            "servers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
                    "description": "Local filesystem access via stdio"
                },
                "remote-api": {
                    "transport": "http",
                    "base_url": "https://api.example.com/mcp",
                    "headers": {"Authorization": "Bearer your-token-here"},
                    "timeout": 30,
                    "description": "Remote HTTP MCP server"
                }
            }
        }
    }
    
    for filename, config in examples.items():
        with open(examples_dir / filename, 'w') as f:
            json.dump(config, f, indent=2)

def find_config_file(config_path: str = None) -> Path:
    """Find configuration file using discovery order"""
    if config_path:
        # Explicit config path provided
        config_file = Path(config_path)
        if not config_file.exists():
            print(f"Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        return config_file
    
    # Configuration discovery order
    search_paths = [
        Path.cwd() / "mcp.json",  # Current directory (project-specific)
        Path.home() / "toolmux" / "mcp.json",  # User's main config
    ]
    
    for path in search_paths:
        if path.exists():
            return path
    
    # No config found, set up first run
    return setup_first_run()

def load_config(config_path: str = None) -> Dict[str, Dict[str, Any]]:
    """Load server configuration from mcp.json"""
    config_file = find_config_file(config_path)
    
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
            return config.get("servers", {})
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in config file: {e}", file=sys.stderr)
        print(f"Please check your configuration file: {config_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading config file: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="ToolMux - Efficient MCP server aggregation with 98.65% token reduction",
        epilog="For more information, visit: https://github.com/subnetangel/ToolMux"
    )
    parser.add_argument(
        "--config", 
        help="Path to MCP configuration file (default: auto-discover)"
    )
    parser.add_argument(
        "--version", 
        action="version", 
        version="ToolMux 1.2.1"
    )
    parser.add_argument(
        "--list-servers",
        action="store_true",
        help="List configured servers and exit"
    )
    
    args = parser.parse_args()
    
    # Handle list-servers command
    if args.list_servers:
        servers = load_config(args.config)
        print("Configured MCP servers:")
        for name, config in servers.items():
            transport = config.get("transport", "stdio")
            if transport == "http":
                endpoint = config.get("base_url", "unknown")
            else:
                endpoint = f"{config.get('command', 'unknown')} {' '.join(config.get('args', []))}"
            print(f"  {name}: {transport} - {endpoint}")
        return
    
    servers = load_config(args.config)
    if not servers:
        print("No servers configured. Edit your mcp.json file to add MCP servers.", file=sys.stderr)
        sys.exit(1)
    
    toolmux = ToolMux(servers)
    toolmux.run()

if __name__ == "__main__":
    main()
