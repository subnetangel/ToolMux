#!/usr/bin/env python3
"""
Simple HTTP MCP Server for testing ToolMux HTTP transport
"""
import json
import asyncio
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="Test HTTP MCP Server", version="1.0.0")

# Simple in-memory tools registry
TOOLS = [
    {
        "name": "echo",
        "description": "Echo back the input message",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo"}
            },
            "required": ["message"]
        }
    },
    {
        "name": "add",
        "description": "Add two numbers",
        "inputSchema": {
            "type": "object", 
            "properties": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"}
            },
            "required": ["a", "b"]
        }
    },
    {
        "name": "get_time",
        "description": "Get current timestamp",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]

# Session state
sessions = {}

@app.post("/mcp")
async def mcp_endpoint(request: Dict[str, Any]):
    """Main MCP JSON-RPC endpoint"""
    method = request.get("method")
    params = request.get("params", {})
    request_id = request.get("id", 1)
    
    try:
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2.0",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "TestHttpMCP", "version": "1.0.0"}
                }
            }
        
        elif method == "notifications/initialized":
            # No response needed for notifications
            return JSONResponse(content={}, status_code=200)
        
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": TOOLS}
            }
        
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            if tool_name == "echo":
                message = arguments.get("message", "")
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"text": f"Echo: {message}"}]
                    }
                }
            
            elif tool_name == "add":
                a = arguments.get("a", 0)
                b = arguments.get("b", 0)
                result = a + b
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"text": f"Result: {a} + {b} = {result}"}]
                    }
                }
            
            elif tool_name == "get_time":
                import time
                timestamp = time.time()
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"text": f"Current timestamp: {timestamp}"}]
                    }
                }
            
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Tool not found: {tool_name}"
                    }
                }
        
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }
    
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "server": "TestHttpMCP"}

if __name__ == "__main__":
    print("Starting Test HTTP MCP Server on http://localhost:8080")
    print("Available tools: echo, add, get_time")
    uvicorn.run(app, host="0.0.0.0", port=8080)