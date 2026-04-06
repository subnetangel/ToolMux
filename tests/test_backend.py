"""BackendManager and HttpMcpClient unit tests."""
import json
import pytest
from toolmux.main import BackendManager, HttpMcpClient, VERSION


class TestBackendManager:

    def test_init_empty(self):
        bm = BackendManager({})
        bm.initialize_all_async()
        tools = bm.wait_for_tools(timeout=2)
        assert tools == []
        bm.shutdown()

    def test_init_with_echo_server(self, test_config):
        config_path = test_config()
        config = json.loads(config_path.read_text())
        bm = BackendManager(config["servers"])
        bm.initialize_all_async()
        tools = bm.wait_for_tools(timeout=10)
        assert len(tools) == 3
        names = {t["name"] for t in tools}
        assert names == {"echo_tool", "reverse_tool", "count_tool"}
        assert all(t["_server"] == "echo" for t in tools)
        bm.shutdown()

    def test_call_tool_routes_correctly(self, test_config):
        config_path = test_config()
        config = json.loads(config_path.read_text())
        bm = BackendManager(config["servers"])
        bm.initialize_all_async()
        bm.wait_for_tools(timeout=10)
        result = bm.call_tool("echo_tool", {"message": "hello"})
        assert "hello" in str(result)
        bm.shutdown()

    def test_call_tool_not_found(self, test_config):
        config_path = test_config()
        config = json.loads(config_path.read_text())
        bm = BackendManager(config["servers"])
        bm.initialize_all_async()
        bm.wait_for_tools(timeout=10)
        result = bm.call_tool("nonexistent", {})
        assert result.get("isError") is True
        bm.shutdown()

    def test_described_tools_tracking(self):
        bm = BackendManager({})
        assert len(bm._described_tools) == 0
        bm._described_tools.add("test")
        assert "test" in bm._described_tools

    def test_failed_server_continues(self, tmp_path):
        config = {"bad": {"command": "/nonexistent/binary", "args": []}}
        bm = BackendManager(config)
        bm.initialize_all_async()
        tools = bm.wait_for_tools(timeout=5)
        assert tools == []
        bm.shutdown()


class TestHttpMcpClient:

    def test_client_initialization(self):
        client = HttpMcpClient(base_url="http://localhost:9999")
        assert client.base_url == "http://localhost:9999"
        assert client.timeout == 30
        assert client._initialized is False
        client.close()

    def test_client_with_headers(self):
        client = HttpMcpClient(
            base_url="http://localhost:9999",
            headers={"Authorization": "Bearer test"})
        assert client.headers == {"Authorization": "Bearer test"}
        client.close()

    def test_context_manager(self):
        with HttpMcpClient(base_url="http://localhost:9999") as client:
            assert client.base_url == "http://localhost:9999"

    def test_version_in_initialize(self):
        """HttpMcpClient should use VERSION constant."""
        client = HttpMcpClient(base_url="http://localhost:9999")
        # Can't actually connect, but verify the version is accessible
        assert VERSION == "2.2.1"  # Keep in sync with pyproject.toml
        client.close()

    def test_connection_error_handled(self):
        client = HttpMcpClient(base_url="http://localhost:1", timeout=1)
        result = client.call_rpc("test")
        assert "error" in result
        client.close()
