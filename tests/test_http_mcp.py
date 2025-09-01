#!/usr/bin/env python3
"""
Unit tests for ToolMux HTTP MCP transport
"""
import pytest
import json
import subprocess
import time
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from toolmux import ToolMux, HttpMcpClient

class TestHttpMcpClient:
    """Test HttpMcpClient functionality"""
    
    def test_client_initialization(self):
        """Test HTTP client initialization"""
        client = HttpMcpClient("http://localhost:8080")
        assert client.base_url == "http://localhost:8080"
        assert client.timeout == 30
        assert client.headers == {}
        client.close()
    
    def test_client_with_headers(self):
        """Test HTTP client with custom headers"""
        headers = {"Authorization": "Bearer test-token"}
        client = HttpMcpClient(
            "http://localhost:8080", 
            headers=headers,
            timeout=15
        )
        assert client.headers == headers
        assert client.timeout == 15
        client.close()
    
    def test_client_context_manager(self):
        """Test HTTP client as context manager"""
        with HttpMcpClient("http://localhost:8080") as client:
            assert client.base_url == "http://localhost:8080"
        # Client should be closed after context

class TestToolMuxHttpIntegration:
    """Test ToolMux with HTTP transport"""
    
    @pytest.fixture
    def mixed_config(self):
        """Mixed stdio/HTTP configuration for testing"""
        return {
            "test-http": {
                "transport": "http",
                "base_url": "http://localhost:8080",
                "timeout": 10
            },
            "test-stdio": {
                "command": "echo",
                "args": ["test"]
            }
        }
    
    def test_server_detection(self, mixed_config):
        """Test transport detection in start_server"""
        toolmux = ToolMux(mixed_config)
        
        # Test HTTP server creation
        http_server = toolmux.start_server("test-http")
        assert isinstance(http_server, HttpMcpClient)
        
        # Test stdio server creation  
        stdio_server = toolmux.start_server("test-stdio")
        assert not isinstance(stdio_server, HttpMcpClient)
        
        # Cleanup
        if http_server:
            http_server.close()
        if stdio_server:
            try:
                stdio_server.terminate()
            except:
                pass
    
    def test_mixed_tool_discovery(self, mixed_config):
        """Test tool discovery with mixed transports"""
        toolmux = ToolMux(mixed_config)
        
        # This will attempt to connect to servers
        # In a real test environment, we'd mock the HTTP responses
        tools = toolmux.get_all_tools()
        
        # Should return list even if servers are not available
        assert isinstance(tools, list)
        
        # Cleanup
        for server in toolmux.server_processes.values():
            try:
                if isinstance(server, HttpMcpClient):
                    server.close()
                else:
                    server.terminate()
            except:
                pass

class TestConfigurationValidation:
    """Test configuration validation and error handling"""
    
    def test_invalid_http_config(self):
        """Test handling of invalid HTTP configuration"""
        config = {
            "invalid-http": {
                "transport": "http"
                # Missing base_url
            }
        }
        
        toolmux = ToolMux(config)
        server = toolmux.start_server("invalid-http")
        
        # Should return None for invalid config
        assert server is None
    
    def test_mixed_config_validation(self):
        """Test mixed configuration validation"""
        config = {
            "valid-stdio": {
                "command": "echo",
                "args": ["test"]
            },
            "valid-http": {
                "transport": "http",
                "base_url": "http://localhost:8080"
            },
            "invalid-stdio": {
                "command": "nonexistent-command"
            }
        }
        
        toolmux = ToolMux(config)
        
        # Valid configs should work
        assert toolmux.servers["valid-stdio"]["command"] == "echo"
        assert toolmux.servers["valid-http"]["transport"] == "http"
        
        # Invalid configs should be handled gracefully
        invalid_server = toolmux.start_server("invalid-stdio")
        # Should return None or handle gracefully

def test_error_handling():
    """Test error handling in HTTP transport"""
    client = HttpMcpClient("http://nonexistent-server:9999", timeout=1)
    
    # Should handle connection errors gracefully
    response = client.call_rpc("test/method")
    assert "error" in response
    assert response["error"]["code"] == -32603
    
    client.close()

def test_json_rpc_format():
    """Test JSON-RPC request/response format"""
    client = HttpMcpClient("http://localhost:8080")
    
    # Test RPC call format
    # This would normally be mocked in a real test
    response = client.call_rpc("initialize", {"test": "param"}, request_id=123)
    
    # Should return proper JSON-RPC format
    assert "jsonrpc" in response
    assert response.get("id") == 123
    
    client.close()

if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])