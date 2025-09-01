"""
ToolMux - Efficient MCP server aggregation with HTTP/SSE support
Reduces token usage by 98.65% while maintaining full functionality
"""

from .main import main, ToolMux, HttpMcpClient

__version__ = "1.1.3"
__all__ = ["main", "ToolMux", "HttpMcpClient"]