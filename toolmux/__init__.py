"""
ToolMux - MCP server aggregation with FastMCP foundation
Three operating modes: meta, proxy, gateway (default)
"""

from .main import main, BackendManager, HttpMcpClient, VERSION

__version__ = VERSION
__all__ = ["main", "BackendManager", "HttpMcpClient"]
