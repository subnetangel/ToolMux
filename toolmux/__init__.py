"""
ToolMux - Efficient MCP server aggregation with HTTP/SSE support
Reduces schema token overhead by 98% while maintaining full functionality
"""

from .main import main, ToolMux, HttpMcpClient

__version__ = "1.2.1"
__all__ = ["main", "ToolMux", "HttpMcpClient"]