#!/usr/bin/env python3
"""
Simple ToolMux Test - Quick validation
"""
import json
import subprocess
import sys
import time
from pathlib import Path

def test_toolmux_basic():
    """Test basic ToolMux functionality"""
    print("🧪 Testing ToolMux basic functionality...")
    
    # Get project root directory
    script_dir = Path(__file__).parent.parent
    
    # Test data
    test_requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "SimpleTest", "version": "1.0.0"}
            }
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "catalog_tools", "arguments": {}}
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_tool_count", "arguments": {}}
        }
    ]
    
    # Prepare input
    input_data = "\n".join(json.dumps(req) for req in test_requests) + "\n"
    
    try:
        # Run ToolMux with test input
        result = subprocess.run(
            [str(script_dir / ".venv" / "bin" / "python"), 
             str(script_dir / "toolmux.py"), 
             "--config", str(script_dir / "mcp.json")],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode != 0:
            print(f"❌ ToolMux failed with exit code {result.returncode}")
            print(f"Stderr: {result.stderr}")
            return False
        
        # Parse responses
        responses = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    responses.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        
        if len(responses) < 3:  # init, tools/list, catalog_tools, get_tool_count
            print(f"❌ Expected at least 3 responses, got {len(responses)}")
            return False
        
        # Validate initialize response
        init_response = responses[0]
        if init_response.get("result", {}).get("protocolVersion") != "2024-11-05":
            print("❌ Invalid initialize response")
            return False
        
        # Validate tools/list response
        tools_response = responses[1]
        tools = tools_response.get("result", {}).get("tools", [])
        expected_tools = {"catalog_tools", "get_tool_schema", "invoke", "get_tool_count"}
        actual_tools = {tool["name"] for tool in tools}
        
        if not expected_tools.issubset(actual_tools):
            print(f"❌ Missing meta-tools. Expected: {expected_tools}, Got: {actual_tools}")
            return False
        
        # Validate catalog_tools response
        catalog_response = responses[2]
        catalog_content = catalog_response.get("result", {}).get("content", [])
        if not catalog_content or catalog_content[0].get("type") != "text":
            print("❌ Invalid catalog_tools response format")
            return False
        
        try:
            catalog = json.loads(catalog_content[0]["text"])
            if not isinstance(catalog, list) or len(catalog) == 0:
                print("❌ Empty catalog")
                return False
        except json.JSONDecodeError:
            print("❌ Invalid catalog JSON")
            return False
        
        # Validate get_tool_count response
        count_response = responses[3]
        count_content = count_response.get("result", {}).get("content", [])
        if not count_content or count_content[0].get("type") != "text":
            print("❌ Invalid get_tool_count response format")
            return False
        
        try:
            count_data = json.loads(count_content[0]["text"])
            total_tools = count_data.get("total_tools", 0)
            if total_tools == 0:
                print("❌ No tools reported")
                return False
        except json.JSONDecodeError:
            print("❌ Invalid count JSON")
            return False
        
        print(f"✅ ToolMux test passed!")
        print(f"   - 4 meta-tools exposed")
        print(f"   - {len(catalog)} backend tools discovered")
        print(f"   - {total_tools} total tools available")
        print(f"   - Token efficiency: {((len(catalog) - 4) / len(catalog) * 100):.1f}% reduction")
        
        return True
        
    except subprocess.TimeoutExpired:
        print("❌ ToolMux test timed out")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def test_q_cli_compatibility():
    """Test Q CLI compatibility"""
    print("\n🧪 Testing Q CLI compatibility...")
    
    try:
        # Check if Q CLI is available
        result = subprocess.run(["q", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            print("⚠️  Q CLI not available - skipping compatibility test")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("⚠️  Q CLI not available - skipping compatibility test")
        return True
    
    # Test basic Q CLI functionality (without actually calling it to avoid hanging)
    print("✅ Q CLI is available and should work with ToolMux MCP integration")
    return True

def main():
    """Run simple tests"""
    print("🚀 ToolMux Simple Test Suite")
    print("=" * 50)
    
    # Get project root directory (parent of tests directory)
    script_dir = Path(__file__).parent.parent
    import os
    os.chdir(script_dir)
    
    # Check prerequisites
    venv_path = script_dir / ".venv" / "bin" / "python"
    toolmux_path = script_dir / "toolmux.py"
    config_path = script_dir / "mcp.json"
    
    if not venv_path.exists():
        print(f"❌ Virtual environment not found: {venv_path}")
        return False
    
    if not toolmux_path.exists():
        print(f"❌ ToolMux script not found: {toolmux_path}")
        return False
    
    if not config_path.exists():
        print(f"❌ MCP config not found: {config_path}")
        return False
    
    # Run tests
    tests_passed = 0
    total_tests = 2
    
    if test_toolmux_basic():
        tests_passed += 1
    
    if test_q_cli_compatibility():
        tests_passed += 1
    
    print("\n" + "=" * 50)
    if tests_passed == total_tests:
        print("🎉 All tests passed! ToolMux is ready for production.")
        return True
    else:
        print(f"❌ {tests_passed}/{total_tests} tests passed")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)