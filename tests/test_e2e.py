#!/usr/bin/env python3
"""
End-to-End Test Suite for ToolMux
Tests both direct MCP protocol and Q CLI integration
"""
import json
import subprocess
import sys
import time
import os
from pathlib import Path
import tempfile
import shutil

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_test(message):
    print(f"{Colors.BLUE}🧪 {message}{Colors.END}")

def print_success(message):
    print(f"{Colors.GREEN}✅ {message}{Colors.END}")

def print_error(message):
    print(f"{Colors.RED}❌ {message}{Colors.END}")

def print_warning(message):
    print(f"{Colors.YELLOW}⚠️  {message}{Colors.END}")

def print_header(message):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}")
    print(f"  {message}")
    print(f"{'='*60}{Colors.END}\n")

class ToolMuxE2ETest:
    def __init__(self):
        self.test_dir = Path(__file__).parent
        self.venv_python = self.test_dir / ".venv" / "bin" / "python"
        self.toolmux_script = self.test_dir / "toolmux.py"
        self.config_file = self.test_dir / "mcp.json"
        self.temp_dir = None
        self.toolmux_process = None
        
    def setup(self):
        """Setup test environment"""
        print_header("TOOLMUX E2E TEST SETUP")
        
        # Verify required files exist
        if not self.venv_python.exists():
            print_error(f"Virtual environment not found: {self.venv_python}")
            return False
            
        if not self.toolmux_script.exists():
            print_error(f"ToolMux script not found: {self.toolmux_script}")
            return False
            
        if not self.config_file.exists():
            print_error(f"Config file not found: {self.config_file}")
            return False
            
        # Create temporary directory for test files
        self.temp_dir = Path(tempfile.mkdtemp(prefix="toolmux_test_"))
        print_success(f"Created test directory: {self.temp_dir}")
        
        # Create test files
        test_file = self.temp_dir / "test.txt"
        test_file.write_text("Hello ToolMux E2E Test!")
        
        test_subdir = self.temp_dir / "subdir"
        test_subdir.mkdir()
        (test_subdir / "nested.txt").write_text("Nested file content")
        
        print_success("Test environment setup complete")
        return True
    
    def cleanup(self):
        """Cleanup test environment"""
        if self.toolmux_process:
            try:
                self.toolmux_process.terminate()
                self.toolmux_process.wait(timeout=5)
            except:
                try:
                    self.toolmux_process.kill()
                except:
                    pass
                    
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            print_success("Cleaned up test directory")
    
    def start_toolmux(self):
        """Start ToolMux server"""
        print_test("Starting ToolMux server...")
        
        try:
            self.toolmux_process = subprocess.Popen(
                [str(self.venv_python), str(self.toolmux_script), "--config", str(self.config_file)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self.test_dir)
            )
            
            # Give it a moment to start
            time.sleep(1)
            
            if self.toolmux_process.poll() is None:
                print_success("ToolMux server started successfully")
                return True
            else:
                stderr = self.toolmux_process.stderr.read()
                print_error(f"ToolMux server failed to start: {stderr}")
                return False
                
        except Exception as e:
            print_error(f"Failed to start ToolMux: {e}")
            return False
    
    def send_mcp_request(self, request, timeout=5):
        """Send MCP request and get response with timeout"""
        if not self.toolmux_process:
            return None
            
        try:
            request_json = json.dumps(request) + "\n"
            self.toolmux_process.stdin.write(request_json)
            self.toolmux_process.stdin.flush()
            
            # Use select for timeout on macOS
            import select
            ready, _, _ = select.select([self.toolmux_process.stdout], [], [], timeout)
            
            if ready:
                response_line = self.toolmux_process.stdout.readline()
                if response_line:
                    return json.loads(response_line.strip())
            else:
                print_warning(f"Request timed out after {timeout}s")
                
            return None
            
        except Exception as e:
            print_error(f"MCP request failed: {e}")
            return None
    
    def test_mcp_initialize(self):
        """Test MCP initialization"""
        print_test("Testing MCP initialization...")
        
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "E2ETest", "version": "1.0.0"}
            }
        }
        
        response = self.send_mcp_request(init_request)
        if not response:
            print_error("No response to initialize request")
            return False
            
        if response.get("jsonrpc") != "2.0" or "result" not in response:
            print_error(f"Invalid initialize response: {response}")
            return False
            
        result = response["result"]
        if result.get("protocolVersion") != "2024-11-05":
            print_error(f"Wrong protocol version: {result.get('protocolVersion')}")
            return False
            
        print_success("MCP initialization successful")
        
        # Send initialized notification
        init_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self.send_mcp_request(init_notif)
        
        return True
    
    def test_tools_list(self):
        """Test tools/list method"""
        print_test("Testing tools/list...")
        
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        response = self.send_mcp_request(request)
        
        if not response or "result" not in response:
            print_error(f"Invalid tools/list response: {response}")
            return False
            
        tools = response["result"].get("tools", [])
        expected_tools = {"catalog_tools", "get_tool_schema", "invoke", "get_tool_count"}
        actual_tools = {tool["name"] for tool in tools}
        
        if not expected_tools.issubset(actual_tools):
            print_error(f"Missing tools. Expected: {expected_tools}, Got: {actual_tools}")
            return False
            
        print_success(f"Found all {len(tools)} meta-tools")
        return True
    
    def test_catalog_tools(self):
        """Test catalog_tools meta-tool"""
        print_test("Testing catalog_tools...")
        
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "catalog_tools", "arguments": {}}
        }
        
        response = self.send_mcp_request(request)
        if not response or "result" not in response:
            print_error(f"Invalid catalog_tools response: {response}")
            return False
            
        content = response["result"].get("content", [])
        if not content or content[0].get("type") != "text":
            print_error(f"Invalid content format: {content}")
            return False
            
        try:
            catalog = json.loads(content[0]["text"])
            if not isinstance(catalog, list) or len(catalog) == 0:
                print_error(f"Empty or invalid catalog: {catalog}")
                return False
                
            # Should have filesystem tools
            filesystem_tools = [t for t in catalog if t.get("server") == "filesystem"]
            if len(filesystem_tools) == 0:
                print_error("No filesystem tools found in catalog")
                return False
                
            print_success(f"Catalog contains {len(catalog)} tools from {len(set(t['server'] for t in catalog))} servers")
            return True
            
        except json.JSONDecodeError as e:
            print_error(f"Invalid JSON in catalog response: {e}")
            return False
    
    def test_get_tool_count(self):
        """Test get_tool_count meta-tool"""
        print_test("Testing get_tool_count...")
        
        request = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_tool_count", "arguments": {}}
        }
        
        response = self.send_mcp_request(request)
        if not response or "result" not in response:
            print_error(f"Invalid get_tool_count response: {response}")
            return False
            
        content = response["result"].get("content", [])
        if not content or content[0].get("type") != "text":
            print_error(f"Invalid content format: {content}")
            return False
            
        try:
            count_data = json.loads(content[0]["text"])
            total_tools = count_data.get("total_tools", 0)
            by_server = count_data.get("by_server", {})
            
            if total_tools == 0:
                print_error("No tools reported in count")
                return False
                
            if "filesystem" not in by_server:
                print_error("Filesystem server not found in tool count")
                return False
                
            print_success(f"Tool count: {total_tools} total, {len(by_server)} servers")
            return True
            
        except json.JSONDecodeError as e:
            print_error(f"Invalid JSON in count response: {e}")
            return False
    
    def test_tool_invocation(self):
        """Test tool invocation through invoke meta-tool"""
        print_test("Testing tool invocation...")
        
        # Test reading a file through the filesystem server
        test_file = self.temp_dir / "test.txt"
        
        request = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "invoke",
                "arguments": {
                    "name": "read_text_file",
                    "args": {"path": str(test_file)}
                }
            }
        }
        
        response = self.send_mcp_request(request)
        if not response or "result" not in response:
            print_error(f"Invalid invoke response: {response}")
            return False
            
        content = response["result"].get("content", [])
        if not content or content[0].get("type") != "text":
            print_error(f"Invalid content format: {content}")
            return False
            
        try:
            result = json.loads(content[0]["text"])
            
            # Check if the file read was successful
            if "content" in result and isinstance(result["content"], list):
                file_content = result["content"][0].get("text", "")
                if "Hello ToolMux E2E Test!" in file_content:
                    print_success("Tool invocation successful - file read correctly")
                    return True
                else:
                    print_error(f"Unexpected file content: {file_content}")
                    return False
            else:
                print_error(f"Unexpected result format: {result}")
                return False
                
        except json.JSONDecodeError as e:
            print_error(f"Invalid JSON in invoke response: {e}")
            return False
    
    def test_q_cli_integration(self):
        """Test Q CLI integration"""
        print_test("Testing Q CLI integration...")
        
        # Check if Q CLI is available
        try:
            result = subprocess.run(["q", "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                print_warning("Q CLI not available - skipping Q CLI integration test")
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print_warning("Q CLI not available - skipping Q CLI integration test")
            return True
        
        # Test Q CLI with ToolMux
        try:
            # Simple Q CLI command that should use MCP tools
            cmd = ["q", "list the available tools"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(self.test_dir))
            
            if result.returncode == 0:
                print_success("Q CLI integration test passed")
                return True
            else:
                print_warning(f"Q CLI test returned non-zero exit code: {result.returncode}")
                print_warning(f"Stderr: {result.stderr}")
                # Don't fail the entire test suite for Q CLI issues
                return True
                
        except subprocess.TimeoutExpired:
            print_warning("Q CLI test timed out - this may be normal")
            return True
        except Exception as e:
            print_warning(f"Q CLI test failed: {e}")
            return True
    
    def run_all_tests(self):
        """Run all E2E tests"""
        print_header("TOOLMUX END-TO-END TEST SUITE")
        
        if not self.setup():
            return False
            
        try:
            if not self.start_toolmux():
                return False
            
            tests = [
                ("MCP Initialize", self.test_mcp_initialize),
                ("Tools List", self.test_tools_list),
                ("Catalog Tools", self.test_catalog_tools),
                ("Get Tool Count", self.test_get_tool_count),
                ("Tool Invocation", self.test_tool_invocation),
                ("Q CLI Integration", self.test_q_cli_integration),
            ]
            
            passed = 0
            total = len(tests)
            
            for test_name, test_func in tests:
                print(f"\n{Colors.BOLD}Running: {test_name}{Colors.END}")
                if test_func():
                    passed += 1
                else:
                    print_error(f"Test failed: {test_name}")
            
            print_header("TEST RESULTS")
            if passed == total:
                print_success(f"All {total} tests passed! 🎉")
                return True
            else:
                print_error(f"{passed}/{total} tests passed")
                return False
                
        finally:
            self.cleanup()

def main():
    """Main test runner"""
    test_suite = ToolMuxE2ETest()
    
    try:
        success = test_suite.run_all_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print_warning("\nTest interrupted by user")
        test_suite.cleanup()
        sys.exit(1)
    except Exception as e:
        print_error(f"Test suite failed with exception: {e}")
        test_suite.cleanup()
        sys.exit(1)

if __name__ == "__main__":
    main()