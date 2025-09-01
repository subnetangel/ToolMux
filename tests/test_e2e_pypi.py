#!/usr/bin/env python3
"""
End-to-End Testing for ToolMux PyPI Installation
Tests the complete user journey from PyPI installation to MCP protocol usage
"""

import json
import subprocess
import tempfile
import os
import sys
import time
from pathlib import Path
import shutil

class ToolMuxE2ETest:
    def __init__(self):
        self.test_dir = None
        self.original_home = os.environ.get('HOME')
        self.test_results = []
        
    def log(self, message, success=True):
        """Log test results"""
        status = "✅" if success else "❌"
        print(f"{status} {message}")
        self.test_results.append((message, success))
        
    def setup_test_environment(self):
        """Create isolated test environment"""
        self.test_dir = tempfile.mkdtemp(prefix="toolmux_e2e_")
        self.log(f"Created test environment: {self.test_dir}")
        
        # Create fake home directory for config isolation
        self.fake_home = Path(self.test_dir) / "home"
        self.fake_home.mkdir()
        os.environ['HOME'] = str(self.fake_home)
        
    def cleanup_test_environment(self):
        """Clean up test environment"""
        if self.original_home:
            os.environ['HOME'] = self.original_home
        if self.test_dir and Path(self.test_dir).exists():
            shutil.rmtree(self.test_dir)
            self.log(f"Cleaned up test environment: {self.test_dir}")
            
    def run_command(self, cmd, cwd=None, input_data=None, timeout=30):
        """Run command and return result"""
        try:
            result = subprocess.run(
                cmd, 
                shell=True, 
                capture_output=True, 
                text=True, 
                cwd=cwd,
                input=input_data,
                timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"
        except Exception as e:
            return -1, "", str(e)
    
    def test_pypi_installation(self):
        """Test 1: PyPI Installation"""
        self.log("Testing PyPI installation with uvx...")
        
        # Test uvx installation
        code, stdout, stderr = self.run_command("uvx toolmux --version")
        if code == 0 and "ToolMux 1.1.1" in stdout:
            self.log("PyPI installation successful")
            return True
        else:
            self.log(f"PyPI installation failed: {stderr}", False)
            return False
    
    def test_first_run_setup(self):
        """Test 2: First-run configuration setup"""
        self.log("Testing first-run configuration setup...")
        
        # Clean up any existing config first
        real_home = Path.home()
        config_dir = real_home / "toolmux"
        if config_dir.exists():
            shutil.rmtree(config_dir)
        
        # Run toolmux for first time
        code, stdout, stderr = self.run_command("uvx toolmux --list-servers")
        
        if code == 0:
            # Check if config directory was created in real home
            config_file = config_dir / "mcp.json"
            examples_dir = config_dir / "examples"
            
            if config_dir.exists() and config_file.exists() and examples_dir.exists():
                self.log("First-run setup created configuration successfully")
                
                # Verify config content
                try:
                    with open(config_file) as f:
                        config = json.load(f)
                    if "servers" in config and "filesystem" in config["servers"]:
                        self.log("Default configuration is valid")
                        return True
                    else:
                        self.log("Default configuration is invalid", False)
                        return False
                except Exception as e:
                    self.log(f"Failed to parse config: {e}", False)
                    return False
            else:
                self.log("First-run setup failed to create files", False)
                return False
        else:
            self.log(f"First-run setup failed: {stderr}", False)
            return False
    
    def test_cli_commands(self):
        """Test 3: CLI command functionality"""
        self.log("Testing CLI commands...")
        
        # Test --version
        code, stdout, stderr = self.run_command("uvx toolmux --version")
        if code != 0 or "ToolMux 1.1.1" not in stdout:
            self.log("--version command failed", False)
            return False
        
        # Test --help
        code, stdout, stderr = self.run_command("uvx toolmux --help")
        if code != 0 or "ToolMux - Efficient MCP server aggregation" not in stdout:
            self.log("--help command failed", False)
            return False
        
        # Test --list-servers
        code, stdout, stderr = self.run_command("uvx toolmux --list-servers")
        if code != 0 or "filesystem" not in stdout:
            self.log("--list-servers command failed", False)
            return False
        
        self.log("All CLI commands working correctly")
        return True
    
    def test_mcp_protocol(self):
        """Test 4: MCP protocol functionality"""
        self.log("Testing MCP protocol...")
        
        # Test initialize request
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
        
        code, stdout, stderr = self.run_command(
            "uvx toolmux",
            input_data=json.dumps(init_request) + "\n"
        )
        
        if code == 0:
            try:
                response = json.loads(stdout.strip())
                if (response.get("jsonrpc") == "2.0" and 
                    "result" in response and 
                    response["result"].get("serverInfo", {}).get("name") == "ToolMux"):
                    self.log("MCP initialize protocol working")
                    return True
                else:
                    self.log(f"Invalid MCP response: {response}", False)
                    return False
            except json.JSONDecodeError as e:
                self.log(f"Failed to parse MCP response: {e}", False)
                return False
        else:
            self.log(f"MCP protocol test failed: {stderr}", False)
            return False
    
    def test_tools_list(self):
        """Test 5: Tools list functionality"""
        self.log("Testing tools/list method...")
        
        # Send initialize first
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
        
        code, stdout, stderr = self.run_command(
            "uvx toolmux",
            input_data=input_data
        )
        
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
                            self.log("All meta-tools available")
                            return True
                        else:
                            self.log(f"Missing tools. Expected: {expected_tools}, Found: {found_tools}", False)
                            return False
                    else:
                        self.log(f"Invalid tools response: {tools_response}", False)
                        return False
                except json.JSONDecodeError as e:
                    self.log(f"Failed to parse tools response: {e}", False)
                    return False
            else:
                self.log("Insufficient response lines", False)
                return False
        else:
            self.log(f"Tools list test failed: {stderr}", False)
            return False
    
    def test_catalog_tools_meta_tool(self):
        """Test 6: catalog_tools meta-tool"""
        self.log("Testing catalog_tools meta-tool...")
        
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
        
        code, stdout, stderr = self.run_command(
            "uvx toolmux",
            input_data=input_data
        )
        
        if code == 0:
            lines = stdout.strip().split('\n')
            if len(lines) >= 2:
                try:
                    catalog_response = json.loads(lines[1])
                    if ("result" in catalog_response and 
                        "content" in catalog_response["result"]):
                        content = catalog_response["result"]["content"][0]["text"]
                        catalog_data = json.loads(content)
                        
                        if isinstance(catalog_data, list) and len(catalog_data) > 0:
                            self.log("catalog_tools meta-tool working")
                            return True
                        else:
                            self.log("catalog_tools returned empty results", False)
                            return False
                    else:
                        self.log(f"Invalid catalog response: {catalog_response}", False)
                        return False
                except json.JSONDecodeError as e:
                    self.log(f"Failed to parse catalog response: {e}", False)
                    return False
            else:
                self.log("Insufficient response lines for catalog", False)
                return False
        else:
            self.log(f"catalog_tools test failed: {stderr}", False)
            return False
    
    def test_custom_config(self):
        """Test 7: Custom configuration"""
        self.log("Testing custom configuration...")
        
        # Create custom config
        custom_config = {
            "servers": {
                "test-server": {
                    "command": "echo",
                    "args": ["test"],
                    "description": "Test server for E2E testing"
                }
            }
        }
        
        config_file = Path(self.test_dir) / "custom_mcp.json"
        with open(config_file, 'w') as f:
            json.dump(custom_config, f, indent=2)
        
        # Test with custom config
        code, stdout, stderr = self.run_command(f"uvx toolmux --config {config_file} --list-servers")
        
        if code == 0 and "test-server" in stdout:
            self.log("Custom configuration working")
            return True
        else:
            self.log(f"Custom configuration failed: {stderr}", False)
            return False
    
    def run_all_tests(self):
        """Run all end-to-end tests"""
        print("🚀 Starting ToolMux End-to-End Testing from PyPI")
        print("=" * 60)
        
        try:
            self.setup_test_environment()
            
            tests = [
                self.test_pypi_installation,
                self.test_first_run_setup,
                self.test_cli_commands,
                self.test_mcp_protocol,
                self.test_tools_list,
                self.test_catalog_tools_meta_tool,
                self.test_custom_config,
            ]
            
            passed = 0
            total = len(tests)
            
            for test in tests:
                try:
                    if test():
                        passed += 1
                    time.sleep(1)  # Brief pause between tests
                except Exception as e:
                    self.log(f"Test {test.__name__} crashed: {e}", False)
            
            print("\n" + "=" * 60)
            print(f"📊 Test Results: {passed}/{total} tests passed")
            
            if passed == total:
                print("🎉 ALL TESTS PASSED! ToolMux is working perfectly from PyPI!")
                return True
            else:
                print("❌ Some tests failed. See details above.")
                return False
                
        finally:
            self.cleanup_test_environment()

if __name__ == "__main__":
    tester = ToolMuxE2ETest()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)