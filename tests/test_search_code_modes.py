"""Tests for search and code operating modes (v2.3.0)."""
import json
import pytest
from conftest import start_toolmux, init_toolmux, send_jsonrpc
from toolmux.main import VERSION


class TestSearchMode:
    """Search mode E2E tests using BM25SearchTransform."""

    def test_initialize_search_mode(self, test_config):
        """Search mode starts and returns instructions mentioning search_tools."""
        proc = start_toolmux(mode="search", config_path=test_config(mode="search"))
        try:
            resp = init_toolmux(proc)
            assert resp is not None
            assert "search" in resp["result"]["instructions"].lower()
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_tools_list_has_synthetic_tools(self, test_config):
        """tools/list should contain search_tools and call_tool — not backend tools.

        Note: BM25SearchTransform replaces the tool list with only its synthetic tools.
        Helper tools (list_all_tools, get_tool_count, manage_servers) are still callable
        but are hidden from tools/list by the transform.
        """
        proc = start_toolmux(mode="search", config_path=test_config(mode="search"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/list", req_id=2)
            names = {t["name"] for t in resp["result"]["tools"]}
            # BM25SearchTransform synthetic tools are the only ones visible in list
            assert "search_tools" in names
            assert "call_tool" in names
            # Backend tools should NOT be directly visible
            assert "echo_tool" not in names
            assert "reverse_tool" not in names
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_search_returns_results(self, test_config):
        """search_tools should find echo tools by query."""
        proc = start_toolmux(mode="search", config_path=test_config(mode="search"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call", {
                "name": "search_tools",
                "arguments": {"query": "echo"}
            }, req_id=3)
            result_text = resp["result"]["content"][0]["text"]
            assert "echo_tool" in result_text
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_call_tool_executes_backend(self, test_config):
        """call_tool should route to backend and return result."""
        proc = start_toolmux(mode="search", config_path=test_config(mode="search"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call", {
                "name": "call_tool",
                "arguments": {"name": "echo_tool", "arguments": {"message": "hello"}}
            }, req_id=3)
            result_text = resp["result"]["content"][0]["text"]
            assert "hello" in result_text
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_list_all_tools_returns_full_catalog(self, test_config):
        """list_all_tools helper should return all backend tools with descriptions."""
        proc = start_toolmux(mode="search", config_path=test_config(mode="search"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call", {
                "name": "list_all_tools",
                "arguments": {}
            }, req_id=3)
            result_text = resp["result"]["content"][0]["text"]
            data = json.loads(result_text)
            assert data["total_tools"] >= 3  # echo_tool, reverse_tool, count_tool
        finally:
            proc.terminate(); proc.wait(timeout=5)


class TestCodeMode:
    """Code mode E2E tests using CodeMode transform."""

    def test_initialize_code_mode(self, test_config):
        """Code mode starts and returns instructions mentioning execute."""
        proc = start_toolmux(mode="code", config_path=test_config(mode="code"))
        try:
            resp = init_toolmux(proc)
            assert resp is not None
            assert "execute" in resp["result"]["instructions"].lower()
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_tools_list_has_synthetic_tools(self, test_config):
        """tools/list should contain search, get_schema, execute — not backend tools.

        Note: CodeMode transform replaces the tool list with only its synthetic tools.
        Helper tools (list_all_tools, get_tool_count, manage_servers) are still callable
        but are hidden from tools/list by the transform.
        """
        proc = start_toolmux(mode="code", config_path=test_config(mode="code"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/list", req_id=2)
            names = {t["name"] for t in resp["result"]["tools"]}
            # CodeMode synthetic tools are the only ones visible in list
            assert "search" in names
            assert "get_schema" in names
            assert "execute" in names
            # Backend tools should NOT be directly visible
            assert "echo_tool" not in names
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_search_returns_results(self, test_config):
        """search should find tools by query."""
        proc = start_toolmux(mode="code", config_path=test_config(mode="code"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call", {
                "name": "search",
                "arguments": {"query": "echo"}
            }, req_id=3)
            result_text = resp["result"]["content"][0]["text"]
            assert "echo_tool" in result_text
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_execute_runs_code(self, test_config):
        """execute should run Python code with call_tool() and return result."""
        proc = start_toolmux(mode="code", config_path=test_config(mode="code"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call", {
                "name": "execute",
                "arguments": {"code": 'result = await call_tool("echo_tool", {"message": "hello from code"})\nreturn result'}
            }, req_id=3)
            result_text = resp["result"]["content"][0]["text"]
            assert "hello from code" in result_text
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_list_all_tools_returns_full_catalog(self, test_config):
        """list_all_tools helper should return all backend tools."""
        proc = start_toolmux(mode="code", config_path=test_config(mode="code"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call", {
                "name": "list_all_tools",
                "arguments": {}
            }, req_id=3)
            result_text = resp["result"]["content"][0]["text"]
            data = json.loads(result_text)
            assert data["total_tools"] >= 3
        finally:
            proc.terminate(); proc.wait(timeout=5)


class TestVersionSync:
    """Verify version consistency for v2.3.1."""

    def test_version_is_2_3_1(self):
        assert VERSION == "2.3.1"
