#!/usr/bin/env python3
"""
Simple End-to-End Test for ToolMux PyPI Installation
Tests core functionality without complex environment isolation
"""

import json
import subprocess
import sys
import time
from pathlib import Path

def run_command(cmd, input_data=None, timeout=30):
    """Run command and return result"""
    try:
        result = subprocess.run(
            cmd, 
            shell=True, 
            capture_output=True, 
            text=True, 
            input=input_data,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)

def test_installation():
    """Test PyPI installation"""
    print("🔍 Testing PyPI installation...")
    code, stdout, stderr = run_command("uvx toolmux --version")
    if code == 0 and "ToolMux 1.1.1" in stdout:
        print("✅ PyPI installation working")
        return True
    else:
        print(f"❌ Installation failed: {stderr}")
        return False

def test_help_command():
    """Test help command"""
    print("🔍 Testing help command...")
    code, stdout, stderr = run_command("uvx toolmux --help")
    if code == 0 and "ToolMux - Efficient MCP server aggregation" in stdout:
        print("✅ Help command working")
        return True
    else:
        print(f"❌ Help command failed: {stderr}")
        return False

def test_list_servers():
    """Test list servers command"""
    print("🔍 Testing list servers...")
    code, stdout, stderr = run_command("uvx toolmux --list-servers")
    if code == 0:
        print("✅ List servers working")
        print(f"   Output: {stdout.strip()}")
        return True
    else:
        print(f"❌ List servers failed: {stderr}")
        return False

def test_mcp_initialize():
    """Test MCP initialize protocol"""
    print("🔍 Testing MCP initialize protocol...")
    
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0.0"}
        }
    }
    
    code, stdout, stderr = run_command(
        "uvx toolmux",
        input_data=json.dumps(init_request) + "\n"
    )
    
    if code == 0:
        try:
            response = json.loads(stdout.strip())
            if (response.get("jsonrpc") == "2.0" and 
                "result" in response and 
                response["result"].get("serverInfo", {}).get("name") == "ToolMux"):
                print("✅ MCP initialize protocol working")
                return True
            else:
                print(f"❌ Invalid MCP response: {response}")
                return False
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse MCP response: {e}")
            return False
    else:
        print(f"❌ MCP protocol failed: {stderr}")
        return False

def test_tools_list():
    """Test tools/list method"""
    print("🔍 Testing tools/list method...")
    
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0.0"}
        }
    }
    
    tools_request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list"
    }
    
    input_data = json.dumps(init_request) + "\n" + json.dumps(tools_request) + "\n"
    
    code, stdout, stderr = run_command("uvx toolmux", input_data=input_data)
    
    if code == 0:
        lines = stdout.strip().split('\n')
        if len(lines) >= 2:
            try:
                tools_response = json.loads(lines[1])
                if ("result" in tools_response and 
                    "tools" in tools_response["result"]):
                    tools = tools_response["result"]["tools"]
                    expected_tools = ["catalog_tools", "get_tool_schema", "invoke", "get_tool_count"]
                    found_tools = [tool["name"] for tool in tools]
                    
                    if all(tool in found_tools for tool in expected_tools):
                        print("✅ All meta-tools available")
                        print(f"   Found tools: {found_tools}")
                        return True
                    else:
                        print(f"❌ Missing tools. Expected: {expected_tools}, Found: {found_tools}")
                        return False
                else:
                    print(f"❌ Invalid tools response: {tools_response}")
                    return False
            except json.JSONDecodeError as e:
                print(f"❌ Failed to parse tools response: {e}")
                return False
        else:
            print("❌ Insufficient response lines")
            return False
    else:
        print(f"❌ Tools list failed: {stderr}")
        return False

def test_catalog_tools():
    """Test catalog_tools meta-tool"""
    print("🔍 Testing catalog_tools meta-tool...")
    
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0.0"}
        }
    }
    
    catalog_request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "catalog_tools",
            "arguments": {}
        }
    }
    
    input_data = json.dumps(init_request) + "\n" + json.dumps(catalog_request) + "\n"
    
    code, stdout, stderr = run_command("uvx toolmux", input_data=input_data)
    
    if code == 0:
        lines = stdout.strip().split('\n')
        if len(lines) >= 2:
            try:
                catalog_response = json.loads(lines[1])
                if ("result" in catalog_response and 
                    "content" in catalog_response["result"]):
                    content = catalog_response["result"]["content"][0]["text"]
                    catalog_data = json.loads(content)
                    
                    if isinstance(catalog_data, list):
                        print("✅ catalog_tools meta-tool working")
                        print(f"   Found {len(catalog_data)} tools from backend servers")
                        return True
                    else:
                        print("❌ catalog_tools returned invalid data")
                        return False
                else:
                    print(f"❌ Invalid catalog response: {catalog_response}")
                    return False
            except json.JSONDecodeError as e:
                print(f"❌ Failed to parse catalog response: {e}")
                return False
        else:
            print("❌ Insufficient response lines for catalog")
            return False
    else:
        print(f"❌ catalog_tools failed: {stderr}")
        return False

def main():
    """Run all tests"""
    print("🚀 ToolMux End-to-End Testing (Simple)")
    print("=" * 50)
    
    tests = [
        test_installation,
        test_help_command,
        test_list_servers,
        test_mcp_initialize,
        test_tools_list,
        test_catalog_tools,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
            print()  # Add spacing between tests
            time.sleep(0.5)  # Brief pause
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
            print()
    
    print("=" * 50)
    print(f"📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED! ToolMux is working perfectly!")
        return True
    else:
        print("❌ Some tests failed.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)