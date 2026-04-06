"""MCP protocol compliance and end-to-end integration tests."""
import json
import subprocess
import sys
import pytest
from conftest import start_toolmux, init_toolmux, send_jsonrpc
from toolmux.main import VERSION


class TestMCPProtocol:
    """MCP protocol compliance via subprocess."""

    def test_initialize_meta_mode(self, test_config):
        proc = start_toolmux(mode="meta", config_path=test_config(mode="meta"))
        try:
            resp = init_toolmux(proc)
            assert resp is not None
            r = resp["result"]
            assert r["serverInfo"]["name"] == "ToolMux"
            assert r["serverInfo"]["version"] == VERSION
            assert "instructions" in r
            assert "catalog_tools" in r["instructions"]
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_initialize_gateway_mode(self, test_config):
        proc = start_toolmux(mode="gateway", config_path=test_config(mode="gateway"))
        try:
            resp = init_toolmux(proc)
            assert "gateway" in resp["result"]["instructions"].lower()
            assert "echo" in resp["result"]["instructions"]
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_initialize_proxy_mode(self, test_config):
        proc = start_toolmux(mode="proxy", config_path=test_config(mode="proxy"))
        try:
            resp = init_toolmux(proc)
            assert "list_all_tools" in resp["result"]["instructions"]
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_tools_list_meta_has_expected_tools(self, test_config):
        proc = start_toolmux(mode="meta", config_path=test_config(mode="meta"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/list", req_id=2)
            names = {t["name"] for t in resp["result"]["tools"]}
            assert {"catalog_tools", "get_tool_schema", "invoke", "get_tool_count"} <= names
            assert "manage_servers" in names
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_tools_list_gateway_has_server_and_native_tools(self, test_config):
        proc = start_toolmux(mode="gateway", config_path=test_config(mode="gateway"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/list", req_id=2)
            names = {t["name"] for t in resp["result"]["tools"]}
            assert "echo" in names
            assert "get_tool_schema" in names
            assert "get_tool_count" in names
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_tools_list_proxy_has_real_tool_names(self, test_config):
        proc = start_toolmux(mode="proxy", config_path=test_config(mode="proxy"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/list", req_id=2)
            names = {t["name"] for t in resp["result"]["tools"]}
            # Native proxy: backend tools + helper tools
            assert "echo_tool" in names
            assert "list_all_tools" in names
            assert "get_tool_schema" in names
            assert "get_tool_count" in names
            assert "manage_servers" in names
        finally:
            proc.terminate(); proc.wait(timeout=5)


class TestMetaModeE2E:
    """End-to-end meta mode: catalog → schema → invoke."""

    def test_full_workflow(self, test_config):
        proc = start_toolmux(mode="meta", config_path=test_config(mode="meta"))
        try:
            init_toolmux(proc)

            # catalog_tools
            resp = send_jsonrpc(proc, "tools/call",
                {"name": "catalog_tools", "arguments": {}}, req_id=3)
            catalog = json.loads(resp["result"]["content"][0]["text"])
            assert len(catalog) == 3
            assert {t["name"] for t in catalog} == {"echo_tool", "reverse_tool", "count_tool"}
            assert all("description" in t and "parameters" in t for t in catalog)

            # get_tool_schema
            resp = send_jsonrpc(proc, "tools/call",
                {"name": "get_tool_schema", "arguments": {"name": "echo_tool"}}, req_id=4)
            schema = json.loads(resp["result"]["content"][0]["text"])
            assert schema["name"] == "echo_tool"
            assert "message" in schema["input_schema"]["properties"]

            # invoke with progressive disclosure
            resp = send_jsonrpc(proc, "tools/call",
                {"name": "invoke", "arguments": {"name": "echo_tool", "args": {"message": "hi"}}}, req_id=5)
            text = resp["result"]["content"][0]["text"]
            assert "hi" in text
            assert "[Tool: echo_tool]" in text
            assert "[Description:" in text

            # invoke same tool again — no enrichment
            resp = send_jsonrpc(proc, "tools/call",
                {"name": "invoke", "arguments": {"name": "echo_tool", "args": {"message": "again"}}}, req_id=6)
            text = resp["result"]["content"][0]["text"]
            assert "again" in text
            assert "[Tool:" not in text

            # get_tool_count
            resp = send_jsonrpc(proc, "tools/call",
                {"name": "get_tool_count", "arguments": {}}, req_id=7)
            counts = json.loads(resp["result"]["content"][0]["text"])
            assert counts["total_tools"] == 3
            assert counts["by_server"]["echo"] == 3
        finally:
            proc.terminate(); proc.wait(timeout=5)


class TestGatewayModeE2E:
    """End-to-end gateway mode: server-tool routing + native tools."""

    def test_server_tool_routing_with_enrichment(self, test_config):
        proc = start_toolmux(mode="gateway", config_path=test_config(mode="gateway"))
        try:
            init_toolmux(proc)

            # Call via server-tool pattern
            resp = send_jsonrpc(proc, "tools/call", {
                "name": "echo",
                "arguments": {"tool": "echo_tool", "arguments": {"message": "test"}}}, req_id=3)
            text = resp["result"]["content"][0]["text"]
            assert "test" in text
            assert "[Tool: echo_tool]" in text  # progressive disclosure

        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_missing_tool_arg_error(self, test_config):
        proc = start_toolmux(mode="gateway", config_path=test_config(mode="gateway"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call",
                {"name": "echo", "arguments": {}}, req_id=3)
            text = resp["result"]["content"][0]["text"]
            assert "Missing 'tool' argument" in text or "sub-tool" in text.lower()
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_native_tool_direct_call(self, test_config):
        proc = start_toolmux(mode="gateway", config_path=test_config(mode="gateway"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call",
                {"name": "get_tool_count", "arguments": {}}, req_id=3)
            data = json.loads(resp["result"]["content"][0]["text"])
            assert data["total_tools"] == 3
        finally:
            proc.terminate(); proc.wait(timeout=5)


class TestProxyModeE2E:
    """End-to-end proxy mode: direct tool calls."""

    def test_tools_exposed_directly(self, test_config):
        proc = start_toolmux(mode="proxy", config_path=test_config(mode="proxy"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/list", req_id=2)
            names = {t["name"] for t in resp["result"]["tools"]}
            # Native proxy: single server = no prefix, tools exposed directly
            assert "echo_tool" in names
        finally:
            proc.terminate(); proc.wait(timeout=5)
