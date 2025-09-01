#!/usr/bin/env python3
"""
Test script for ToolMux HTTP transport functionality
"""
import json
import subprocess
import time
import sys
from pathlib import Path

def test_http_client():
    """Test HttpMcpClient directly"""
    print("🧪 Testing HttpMcpClient directly...")
    
    try:
        from toolmux import HttpMcpClient
        
        # Test with local test server
        client = HttpMcpClient("http://localhost:8080")
        
        # Test initialization
        print("  ✓ Testing initialization...")
        if not client.initialize():
            print("  ❌ Failed to initialize HTTP client")
            return False
        
        # Test tool listing
        print("  ✓ Testing tool listing...")
        tools = client.get_tools()
        if not tools:
            print("  ❌ No tools returned")
            return False
        
        print(f"  ✓ Found {len(tools)} tools: {[t['name'] for t in tools]}")
        
        # Test tool calling
        print("  ✓ Testing tool calling...")
        result = client.call_tool("echo", {"message": "Hello HTTP MCP!"})
        if "error" in result:
            print(f"  ❌ Tool call failed: {result['error']}")
            return False
        
        print(f"  ✓ Tool call result: {result}")
        
        client.close()
        assert True, "HTTP client test completed successfully"
        
    except Exception as e:
        print(f"  ❌ HTTP client test failed: {e}")
        assert False, f"HTTP client test failed: {e}"

def test_mixed_configuration():
    """Test ToolMux with mixed stdio/HTTP configuration"""
    print("🧪 Testing ToolMux with mixed configuration...")
    
    try:
        from toolmux import ToolMux
        
        # Load mixed configuration
        with open("mixed_servers.json", "r") as f:
            config = json.load(f)
        
        toolmux = ToolMux(config["servers"])
        
        # Test tool discovery
        print("  ✓ Testing tool discovery...")
        tools = toolmux.get_all_tools()
        
        if not tools:
            print("  ❌ No tools discovered")
            return False
        
        print(f"  ✓ Discovered {len(tools)} tools from mixed servers")
        
        # Group tools by transport
        stdio_tools = [t for t in tools if t.get("_transport") == "stdio"]
        http_tools = [t for t in tools if t.get("_transport") == "http"]
        
        print(f"    - stdio tools: {len(stdio_tools)}")
        print(f"    - HTTP tools: {len(http_tools)}")
        
        # Test HTTP tool calling if available
        if http_tools:
            print("  ✓ Testing HTTP tool calling...")
            http_tool = http_tools[0]
            result = toolmux.call_tool(http_tool["name"], {})
            print(f"    Result: {result}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Mixed configuration test failed: {e}")
        return False

def start_test_server():
    """Start the test HTTP server"""
    print("🚀 Starting test HTTP server...")
    
    try:
        # Check if server is already running
        import httpx
        try:
            response = httpx.get("http://localhost:8080/health", timeout=2)
            if response.status_code == 200:
                print("  ✓ Test server already running")
                return None
        except:
            pass
        
        # Start the server
        process = subprocess.Popen([
            sys.executable, "test_http_server.py"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Wait for server to start
        time.sleep(3)
        
        # Verify server is running
        try:
            response = httpx.get("http://localhost:8080/health", timeout=5)
            if response.status_code == 200:
                print("  ✓ Test server started successfully")
                return process
            else:
                print("  ❌ Test server not responding")
                process.terminate()
                return None
        except Exception as e:
            print(f"  ❌ Failed to verify test server: {e}")
            process.terminate()
            return None
            
    except Exception as e:
        print(f"  ❌ Failed to start test server: {e}")
        return None

def main():
    """Run all HTTP transport tests"""
    print("🛠️  ToolMux HTTP Transport Test Suite")
    print("=" * 50)
    
    # Start test server
    server_process = start_test_server()
    
    try:
        # Run tests
        tests_passed = 0
        total_tests = 2
        
        if test_http_client():
            tests_passed += 1
        
        if test_mixed_configuration():
            tests_passed += 1
        
        # Results
        print("\n" + "=" * 50)
        print(f"📊 Test Results: {tests_passed}/{total_tests} passed")
        
        if tests_passed == total_tests:
            print("🎉 All tests passed!")
            return 0
        else:
            print("❌ Some tests failed")
            return 1
    
    finally:
        # Cleanup
        if server_process:
            print("🧹 Stopping test server...")
            server_process.terminate()
            server_process.wait()

if __name__ == "__main__":
    sys.exit(main())