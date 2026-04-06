"""Tests for list_all_tools gateway tool."""
import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.conftest import (
    start_toolmux, init_toolmux, send_jsonrpc, tool_dict,
)
from toolmux.main import condense_description


# ─── Unit Tests (test the logic directly, no FastMCP registration) ───


def _list_all_tools_logic(tools, cached_descriptions=None, server_filter=None):
    """Replicate the exact logic from list_all_tools in main.py."""
    by_server: Dict[str, List[Dict[str, str]]] = {}
    for t in tools:
        s = t["_server"]
        if server_filter and s != server_filter:
            continue
        name = t["name"]
        if cached_descriptions and s in cached_descriptions and name in cached_descriptions[s]:
            desc = cached_descriptions[s][name]
        else:
            desc = condense_description(t.get("description", ""), max_len=80)
        by_server.setdefault(s, []).append({"name": name, "description": desc})
    return {"total_tools": sum(len(v) for v in by_server.values()),
            "servers": {s: {"tool_count": len(tl), "tools": tl}
                        for s, tl in by_server.items()}}


class TestListAllToolsUnit:
    """Unit tests for list_all_tools logic."""

    def test_basic_listing(self):
        tools = [
            tool_dict("tool_a", "server1", "Desc A"),
            tool_dict("tool_b", "server1", "Desc B"),
            tool_dict("tool_c", "server2", "Desc C"),
        ]
        result = _list_all_tools_logic(tools)
        assert result["total_tools"] == 3
        assert "server1" in result["servers"]
        assert "server2" in result["servers"]
        assert result["servers"]["server1"]["tool_count"] == 2
        assert result["servers"]["server2"]["tool_count"] == 1
        names_s1 = {t["name"] for t in result["servers"]["server1"]["tools"]}
        assert names_s1 == {"tool_a", "tool_b"}

    def test_server_filter(self):
        tools = [
            tool_dict("tool_a", "server1", "Desc A"),
            tool_dict("tool_b", "server2", "Desc B"),
            tool_dict("tool_c", "server2", "Desc C"),
        ]
        result = _list_all_tools_logic(tools, server_filter="server2")
        assert result["total_tools"] == 2
        assert "server1" not in result["servers"]
        assert result["servers"]["server2"]["tool_count"] == 2

    def test_server_filter_no_match(self):
        tools = [tool_dict("tool_a", "server1", "Desc A")]
        result = _list_all_tools_logic(tools, server_filter="nonexistent")
        assert result["total_tools"] == 0
        assert result["servers"] == {}

    def test_cached_descriptions_used(self):
        tools = [tool_dict("tool_a", "server1", "Raw verbose description")]
        cached = {"server1": {"tool_a": "Cached short desc"}}
        result = _list_all_tools_logic(tools, cached_descriptions=cached)
        assert result["servers"]["server1"]["tools"][0]["description"] == "Cached short desc"

    def test_uncached_descriptions_condensed(self):
        long_desc = "This is a very long description that should be condensed. " * 5
        tools = [tool_dict("tool_a", "server1", long_desc)]
        result = _list_all_tools_logic(tools)
        assert len(result["servers"]["server1"]["tools"][0]["description"]) <= 80

    def test_empty_backend(self):
        result = _list_all_tools_logic([])
        assert result["total_tools"] == 0
        assert result["servers"] == {}

    def test_many_servers(self):
        tools = [tool_dict(f"tool_{i}", f"server_{i}", f"Desc {i}")
                 for i in range(20)]
        result = _list_all_tools_logic(tools)
        assert result["total_tools"] == 20
        assert len(result["servers"]) == 20

    def test_output_structure(self):
        tools = [tool_dict("my_tool", "my_server", "My description")]
        result = _list_all_tools_logic(tools)
        assert "total_tools" in result
        assert "servers" in result
        srv = result["servers"]["my_server"]
        assert "tool_count" in srv
        assert "tools" in srv
        t = srv["tools"][0]
        assert set(t.keys()) == {"name", "description"}
        assert t["name"] == "my_tool"

    def test_partial_cache(self):
        tools = [
            tool_dict("cached_tool", "server1", "Raw desc 1"),
            tool_dict("uncached_tool", "server1", "Raw desc 2"),
        ]
        cached = {"server1": {"cached_tool": "From cache"}}
        result = _list_all_tools_logic(tools, cached_descriptions=cached)
        tool_map = {t["name"]: t["description"]
                    for t in result["servers"]["server1"]["tools"]}
        assert tool_map["cached_tool"] == "From cache"
        assert tool_map["uncached_tool"] != "From cache"

    def test_json_serializable(self):
        tools = [tool_dict("t1", "s1", "D1"), tool_dict("t2", "s2", "D2")]
        result = _list_all_tools_logic(tools)
        serialized = json.dumps(result, indent=2)
        roundtrip = json.loads(serialized)
        assert roundtrip == result

    def test_empty_description_handled(self):
        tools = [tool_dict("t1", "s1", "")]
        result = _list_all_tools_logic(tools)
        assert result["servers"]["s1"]["tools"][0]["description"] == ""

    def test_tools_ordered_by_insertion(self):
        tools = [
            tool_dict("zebra", "s1", "Z"),
            tool_dict("alpha", "s1", "A"),
            tool_dict("middle", "s1", "M"),
        ]
        result = _list_all_tools_logic(tools)
        names = [t["name"] for t in result["servers"]["s1"]["tools"]]
        assert names == ["zebra", "alpha", "middle"]

    def test_cache_for_wrong_server_ignored(self):
        tools = [tool_dict("t1", "server1", "Raw desc")]
        cached = {"server2": {"t1": "Wrong server cache"}}
        result = _list_all_tools_logic(tools, cached_descriptions=cached)
        assert result["servers"]["server1"]["tools"][0]["description"] != "Wrong server cache"


# ─── E2E Tests ───


class TestListAllToolsE2E:
    """End-to-end tests using real ToolMux subprocess in gateway mode."""

    def test_returns_all_tools(self, test_config):
        proc = start_toolmux(mode="gateway",
                             config_path=test_config(mode="gateway"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call",
                {"name": "list_all_tools", "arguments": {}}, req_id=3)
            data = json.loads(resp["result"]["content"][0]["text"])
            assert data["total_tools"] == 3
            assert "echo" in data["servers"]
            names = {t["name"] for t in data["servers"]["echo"]["tools"]}
            assert names == {"echo_tool", "reverse_tool", "count_tool"}
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_server_filter(self, test_config):
        proc = start_toolmux(mode="gateway",
                             config_path=test_config(mode="gateway"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call",
                {"name": "list_all_tools",
                 "arguments": {"server": "echo"}}, req_id=3)
            data = json.loads(resp["result"]["content"][0]["text"])
            assert data["total_tools"] == 3
            assert "echo" in data["servers"]
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_filter_nonexistent_server(self, test_config):
        proc = start_toolmux(mode="gateway",
                             config_path=test_config(mode="gateway"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call",
                {"name": "list_all_tools",
                 "arguments": {"server": "does_not_exist"}}, req_id=3)
            data = json.loads(resp["result"]["content"][0]["text"])
            assert data["total_tools"] == 0
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_all_tools_have_descriptions(self, test_config):
        proc = start_toolmux(mode="gateway",
                             config_path=test_config(mode="gateway"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call",
                {"name": "list_all_tools", "arguments": {}}, req_id=3)
            data = json.loads(resp["result"]["content"][0]["text"])
            for srv_data in data["servers"].values():
                for tool in srv_data["tools"]:
                    assert tool["description"], f"{tool['name']} has empty desc"
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_registered_in_tools_list(self, test_config):
        proc = start_toolmux(mode="gateway",
                             config_path=test_config(mode="gateway"))
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/list", req_id=2)
            names = {t["name"] for t in resp["result"]["tools"]}
            assert "list_all_tools" in names
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_dual_server(self, dual_server_config):
        proc = start_toolmux(mode="gateway", config_path=dual_server_config)
        try:
            init_toolmux(proc)
            resp = send_jsonrpc(proc, "tools/call",
                {"name": "list_all_tools", "arguments": {}}, req_id=3)
            data = json.loads(resp["result"]["content"][0]["text"])
            assert data["total_tools"] == 6
            assert len(data["servers"]) == 2
            assert "server_a" in data["servers"]
            assert "server_b" in data["servers"]
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_count_matches_list(self, test_config):
        proc = start_toolmux(mode="gateway",
                             config_path=test_config(mode="gateway"))
        try:
            init_toolmux(proc)
            resp1 = send_jsonrpc(proc, "tools/call",
                {"name": "get_tool_count", "arguments": {}}, req_id=3)
            count_data = json.loads(resp1["result"]["content"][0]["text"])
            resp2 = send_jsonrpc(proc, "tools/call",
                {"name": "list_all_tools", "arguments": {}}, req_id=4)
            list_data = json.loads(resp2["result"]["content"][0]["text"])
            assert count_data["total_tools"] == list_data["total_tools"]
            for srv, cnt in count_data["by_server"].items():
                assert list_data["servers"][srv]["tool_count"] == cnt
        finally:
            proc.terminate(); proc.wait(timeout=5)
