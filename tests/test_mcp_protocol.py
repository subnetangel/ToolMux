#!/usr/bin/env python3
"""
Test script to verify ToolMux MCP protocol compliance
"""
import json
import subprocess
import sys
import time
import threading
from queue import Queue, Empty

def test_mcp_protocol():
    """Test ToolMux MCP protocol compliance"""
    print("🧪 Testing ToolMux MCP Protocol Compliance")
    print("=" * 50)
    
    # Start ToolMux server
    try:
        process = subprocess.Popen(
            [sys.executable, "toolmux.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0
        )
        
        def read_output(pipe, queue):
            """Read output from pipe and put in queue"""
            try:
                for line in iter(pipe.readline, ''):
                    if line.strip():
                        queue.put(line.strip())
            except Exception as e:
                queue.put(f"ERROR: {e}")
        
        # Start output reader thread
        output_queue = Queue()
        output_thread = threading.Thread(target=read_output, args=(process.stdout, output_queue))
        output_thread.daemon = True
        output_thread.start()
        
        def send_request(request):
            """Send JSON-RPC request to server"""
            request_str = json.dumps(request) + "\n"
            print(f"📤 Sending: {request}")
            process.stdin.write(request_str)
            process.stdin.flush()
            
            # Wait for response
            try:
                response_str = output_queue.get(timeout=5)
                response = json.loads(response_str)
                print(f"📥 Received: {response}")
                return response
            except Empty:
                print("❌ No response received (timeout)")
                return None
            except json.JSONDecodeError as e:
                print(f"❌ Invalid JSON response: {response_str}")
                return None
        
        # Test 1: Initialize
        print("\n1️⃣ Testing initialize request...")
        init_request = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TestClient", "version": "1.0.0"}
            },
            "id": 1
        }
        
        init_response = send_request(init_request)
        if init_response:
            protocol_version = init_response.get("result", {}).get("protocolVersion")
            if protocol_version == "2024-11-05":
                print("✅ Protocol version correct")
            else:
                print(f"❌ Wrong protocol version: {protocol_version}")
        
        # Test 2: Initialized notification
        print("\n2️⃣ Testing initialized notification...")
        initialized_notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        send_request(initialized_notif)
        
        # Test 3: List tools
        print("\n3️⃣ Testing tools/list...")
        list_request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 2
        }
        
        list_response = send_request(list_request)
        if list_response and "result" in list_response:
            tools = list_response["result"].get("tools", [])
            print(f"✅ Found {len(tools)} tools")
            for tool in tools:
                print(f"   - {tool.get('name')}: {tool.get('description')}")
        
        # Test 4: Call a tool
        print("\n4️⃣ Testing tool call...")
        tool_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "catalog_tools",
                "arguments": {}
            },
            "id": 3
        }
        
        tool_response = send_request(tool_request)
        if tool_response and "result" in tool_response:
            print("✅ Tool call successful")
        
        print("\n✅ MCP Protocol test completed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        if 'process' in locals():
            process.terminate()
            process.wait()

if __name__ == "__main__":
    test_mcp_protocol()