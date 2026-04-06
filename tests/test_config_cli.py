"""Configuration loading, CLI flags, version sync, and build cache tests."""
import json
import hashlib
import subprocess
import sys
import pytest
from pathlib import Path

from toolmux.main import (
    VERSION, load_build_cache, compute_config_hash,
)

TOOLMUX_DIR = Path(__file__).parent.parent


class TestVersionSync:
    """All version strings must be consistent across the codebase."""

    def test_version_constant_is_semver(self):
        parts = VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_init_version_matches_constant(self):
        import toolmux
        assert toolmux.__version__ == VERSION

    def test_pyproject_version_matches_constant(self):
        import tomllib
        pyproject = TOOLMUX_DIR / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["version"] == VERSION

    def test_cli_version_output_matches_constant(self):
        result = subprocess.run(
            [sys.executable, "-m", "toolmux", "--version"],
            capture_output=True, text=True, cwd=str(TOOLMUX_DIR))
        assert f"ToolMux {VERSION}" in result.stdout


class TestCLI:

    def test_list_servers(self, test_config):
        config = test_config()
        result = subprocess.run(
            [sys.executable, "-m", "toolmux", "--list-servers", "--config", str(config)],
            capture_output=True, text=True, cwd=str(TOOLMUX_DIR))
        assert "echo" in result.stdout
        assert "stdio" in result.stdout

    def test_mode_precedence_cli_over_config(self, test_config):
        """CLI --mode flag overrides config file mode field."""
        from conftest import start_toolmux, init_toolmux
        config = test_config(mode="proxy")  # config says proxy
        proc = start_toolmux(mode="meta", config_path=config)  # CLI says meta
        try:
            resp = init_toolmux(proc)
            assert "catalog_tools" in resp["result"]["instructions"]
        finally:
            proc.terminate(); proc.wait(timeout=5)

    def test_default_mode_is_gateway(self, test_config):
        from conftest import start_toolmux, init_toolmux
        import os
        config = test_config()  # no mode field
        env = {**os.environ, "PYTHONPATH": str(TOOLMUX_DIR),
               "FASTMCP_SHOW_SERVER_BANNER": "false"}
        proc = subprocess.Popen(
            [sys.executable, "-m", "toolmux", "--config", str(config)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(TOOLMUX_DIR), env=env)
        import time; time.sleep(2)
        try:
            from conftest import send_jsonrpc
            resp = send_jsonrpc(proc, "initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"}})
            assert "gateway" in resp["result"]["instructions"].lower()
        finally:
            proc.terminate(); proc.wait(timeout=5)


class TestModuleExports:

    def test_exports_v2_classes(self):
        import toolmux
        assert hasattr(toolmux, "BackendManager")
        assert hasattr(toolmux, "HttpMcpClient")
        assert hasattr(toolmux, "main")

    def test_no_old_toolmux_class(self):
        import toolmux
        assert not hasattr(toolmux, "ToolMux")


class TestBuildCache:
    """Properties 15-16: build cache validation."""

    def _write_cache(self, tmp_path, config_content, cache_data):
        config_path = tmp_path / "mcp.json"
        config_path.write_text(config_content)
        cache_path = tmp_path / ".toolmux_cache.json"
        cache_path.write_text(json.dumps(cache_data))
        return config_path

    def test_valid_cache_loads(self, tmp_path):
        content = '{"servers": {"fs": {}}}'
        h = f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"
        path = self._write_cache(tmp_path, content, {
            "version": "1.0", "generated_at": "2025-01-01T00:00:00Z",
            "config_hash": h, "model": "test",
            "servers": {"fs": {"tool_count": 1, "descriptions": {"read": "Read files"}}}})
        result = load_build_cache(path, {}, [{"name": "read", "_server": "fs"}])
        assert result is not None
        assert result["fs"]["read"] == "Read files"

    def test_stale_hash_returns_none(self, tmp_path):
        path = self._write_cache(tmp_path, '{"servers": {}}', {
            "version": "1.0", "config_hash": "sha256:wrong", "model": "test", "servers": {}})
        assert load_build_cache(path, {}, []) is None

    def test_mismatched_tool_count_returns_none(self, tmp_path):
        content = '{"servers": {"fs": {}}}'
        h = f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"
        path = self._write_cache(tmp_path, content, {
            "version": "1.0", "config_hash": h, "model": "test",
            "servers": {"fs": {"tool_count": 99, "descriptions": {}}}})
        assert load_build_cache(path, {}, [{"name": "r", "_server": "fs"}]) is None

    def test_missing_file_returns_none(self, tmp_path):
        p = tmp_path / "mcp.json"
        p.write_text("{}")
        assert load_build_cache(p, {}, []) is None

    def test_invalid_json_returns_none(self, tmp_path):
        p = tmp_path / "mcp.json"
        p.write_text("{}")
        (tmp_path / ".toolmux_cache.json").write_text("not json")
        assert load_build_cache(p, {}, []) is None

    def test_config_hash_deterministic(self, tmp_path):
        p = tmp_path / "test.json"
        p.write_text('{"hello": "world"}')
        h1 = compute_config_hash(p)
        h2 = compute_config_hash(p)
        assert h1 == h2
        assert h1.startswith("sha256:")
