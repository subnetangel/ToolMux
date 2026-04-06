"""
Tests for bundle-aware server configuration.

Validates that ToolMux can resolve server configs from mcp-registry bundle
files when commands are missing or incorrect.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "toolmux"))
from main import resolve_bundle


def _write_bundle(directory, name, bundle_data):
    path = directory / f"{name}.json"
    path.write_text(json.dumps(bundle_data))
    return path


def _make_bundle(executable, args=None):
    return {"genericBundle": {"run": {"executable": executable, "args": args or []}}}


def _make_mcp_config(servers_dict):
    """Create a standard mcpServers config file content."""
    return {"mcpServers": servers_dict}


class TestResolveBundle:
    """Test bundle resolution from mcp-registry config files."""

    def _setup_home(self, tmp_path):
        """Create a fake home with all expected directories."""
        fake_home = tmp_path / "home"
        (fake_home / ".config" / "smithy-mcp" / "bundles").mkdir(parents=True)
        (fake_home / ".aim" / "bundles").mkdir(parents=True)
        (fake_home / ".config" / "mcp").mkdir(parents=True)
        (fake_home / ".config" / "Claude").mkdir(parents=True)
        (fake_home / ".cursor").mkdir(parents=True)
        return fake_home

    def _resolve(self, name, fake_home):
        with patch("pathlib.Path.home", return_value=fake_home):
            return resolve_bundle(name)

    def test_resolves_local_binary_bundle(self, tmp_path):
        home = self._setup_home(tmp_path)
        _write_bundle(home / ".config" / "smithy-mcp" / "bundles", "my-mcp",
                      _make_bundle("my-mcp-server", ["--mode", "stdio"]))
        result = self._resolve("my-mcp", home)
        assert result is not None
        assert result["command"] == "my-mcp-server"
        assert result["args"] == ["--mode", "stdio"]

    def test_resolves_remote_uvx_bundle(self, tmp_path):
        home = self._setup_home(tmp_path)
        _write_bundle(home / ".config" / "smithy-mcp" / "bundles", "aws-knowledge-mcp-server-mcp",
                      _make_bundle("uvx", ["fastmcp", "run", "https://knowledge-mcp.global.api.aws"]))
        result = self._resolve("aws-knowledge-mcp-server-mcp", home)
        assert result is not None
        assert result["command"] == "uvx"
        assert result["args"] == ["fastmcp", "run", "https://knowledge-mcp.global.api.aws"]

    def test_resolves_toolmux_bundle(self, tmp_path):
        home = self._setup_home(tmp_path)
        _write_bundle(home / ".config" / "smithy-mcp" / "bundles", "toolmux-mcp",
                      _make_bundle("toolmux", ["--mode", "gateway"]))
        result = self._resolve("toolmux-mcp", home)
        assert result is not None
        assert result["command"] == "toolmux"

    def test_returns_none_when_no_bundle(self, tmp_path):
        home = self._setup_home(tmp_path)
        result = self._resolve("nonexistent-mcp", home)
        assert result is None

    def test_returns_none_for_malformed_bundle(self, tmp_path):
        home = self._setup_home(tmp_path)
        (home / ".config" / "smithy-mcp" / "bundles" / "bad-mcp.json").write_text("not json")
        result = self._resolve("bad-mcp", home)
        assert result is None

    def test_returns_none_when_no_executable(self, tmp_path):
        home = self._setup_home(tmp_path)
        _write_bundle(home / ".config" / "smithy-mcp" / "bundles", "no-exec",
                      {"genericBundle": {"run": {"args": ["--foo"]}}})
        result = self._resolve("no-exec", home)
        assert result is None

    def test_falls_back_to_aim_bundles(self, tmp_path):
        home = self._setup_home(tmp_path)
        _write_bundle(home / ".aim" / "bundles", "aim-only-mcp",
                      _make_bundle("aim-mcp-server"))
        result = self._resolve("aim-only-mcp", home)
        assert result is not None
        assert result["command"] == "aim-mcp-server"

    def test_prefers_smithy_over_aim(self, tmp_path):
        home = self._setup_home(tmp_path)
        _write_bundle(home / ".config" / "smithy-mcp" / "bundles", "dual-mcp",
                      _make_bundle("smithy-cmd"))
        _write_bundle(home / ".aim" / "bundles", "dual-mcp",
                      _make_bundle("aim-cmd"))
        result = self._resolve("dual-mcp", home)
        assert result["command"] == "smithy-cmd"

    def test_includes_source_path(self, tmp_path):
        home = self._setup_home(tmp_path)
        _write_bundle(home / ".config" / "smithy-mcp" / "bundles", "test-mcp",
                      _make_bundle("test-cmd"))
        result = self._resolve("test-mcp", home)
        assert "source" in result
        assert "test-mcp.json" in result["source"]

    def test_empty_args_defaults_to_list(self, tmp_path):
        home = self._setup_home(tmp_path)
        _write_bundle(home / ".config" / "smithy-mcp" / "bundles", "no-args",
                      {"genericBundle": {"run": {"executable": "cmd"}}})
        result = self._resolve("no-args", home)
        assert result["args"] == []

    # --- Open source config formats ---

    def test_resolves_from_claude_desktop_config(self, tmp_path):
        """Claude Desktop mcpServers format on Linux."""
        home = self._setup_home(tmp_path)
        config = _make_mcp_config({"my-server": {"command": "my-server", "args": ["--stdio"]}})
        (home / ".config" / "Claude" / "claude_desktop_config.json").write_text(json.dumps(config))
        result = self._resolve("my-server", home)
        assert result is not None
        assert result["command"] == "my-server"
        assert result["args"] == ["--stdio"]

    def test_resolves_from_cursor_config(self, tmp_path):
        """Cursor mcp.json format."""
        home = self._setup_home(tmp_path)
        config = _make_mcp_config({"cursor-mcp": {"command": "npx", "args": ["-y", "some-mcp"]}})
        (home / ".cursor" / "mcp.json").write_text(json.dumps(config))
        result = self._resolve("cursor-mcp", home)
        assert result is not None
        assert result["command"] == "npx"
        assert result["args"] == ["-y", "some-mcp"]

    def test_resolves_from_xdg_mcp_config(self, tmp_path):
        """XDG standard ~/.config/mcp/config.json."""
        home = self._setup_home(tmp_path)
        config = _make_mcp_config({"xdg-mcp": {"command": "xdg-server"}})
        (home / ".config" / "mcp" / "config.json").write_text(json.dumps(config))
        result = self._resolve("xdg-mcp", home)
        assert result is not None
        assert result["command"] == "xdg-server"

    def test_resolves_sse_url_from_mcp_config(self, tmp_path):
        """SSE/HTTP server in mcpServers format gets wrapped with uvx fastmcp run."""
        home = self._setup_home(tmp_path)
        config = _make_mcp_config({"remote-mcp": {"url": "https://example.com/mcp/sse"}})
        (home / ".config" / "mcp" / "config.json").write_text(json.dumps(config))
        result = self._resolve("remote-mcp", home)
        assert result is not None
        assert result["command"] == "uvx"
        assert result["args"] == ["fastmcp", "run", "https://example.com/mcp/sse"]

    def test_bundle_takes_priority_over_mcp_config(self, tmp_path):
        """mcp-registry bundle should win over Claude Desktop config."""
        home = self._setup_home(tmp_path)
        _write_bundle(home / ".config" / "smithy-mcp" / "bundles", "priority-mcp",
                      _make_bundle("bundle-cmd"))
        config = _make_mcp_config({"priority-mcp": {"command": "claude-cmd"}})
        (home / ".config" / "Claude" / "claude_desktop_config.json").write_text(json.dumps(config))
        result = self._resolve("priority-mcp", home)
        assert result["command"] == "bundle-cmd"


class TestBundleFallbackBehavior:
    """Test that ToolMux auto-heals using bundle configs at runtime."""

    def _setup_home(self, tmp_path):
        fake_home = tmp_path / "home"
        (fake_home / ".config" / "smithy-mcp" / "bundles").mkdir(parents=True)
        (fake_home / ".aim" / "bundles").mkdir(parents=True)
        (fake_home / ".config" / "mcp").mkdir(parents=True)
        (fake_home / ".config" / "Claude").mkdir(parents=True)
        (fake_home / ".cursor").mkdir(parents=True)
        return fake_home

    def test_start_server_falls_back_to_bundle(self, tmp_path):
        """When configured command doesn't exist, use bundle's command."""
        from main import BackendManager

        home = self._setup_home(tmp_path)
        _write_bundle(home / ".config" / "smithy-mcp" / "bundles", "broken-mcp",
                      _make_bundle("real-cmd", ["--flag"]))

        config = {"broken-mcp": {"command": "nonexistent-cmd", "args": []}}
        bm = BackendManager(config)

        with patch("pathlib.Path.home", return_value=home), \
             patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: "/usr/bin/real-cmd" if cmd == "real-cmd" else None
            with patch("subprocess.Popen") as mock_popen:
                mock_popen.return_value = MagicMock()
                result = bm.start_server("broken-mcp")

            assert result is not None
            call_args = mock_popen.call_args[0][0]
            assert call_args[0] == "real-cmd"
            assert "--flag" in call_args

    def test_start_server_falls_back_to_claude_config(self, tmp_path):
        """When no bundle exists, fall back to Claude Desktop config."""
        from main import BackendManager

        home = self._setup_home(tmp_path)
        config_data = _make_mcp_config({"claude-mcp": {"command": "claude-server", "args": ["--port", "3000"]}})
        (home / ".config" / "Claude" / "claude_desktop_config.json").write_text(json.dumps(config_data))

        config = {"claude-mcp": {"command": "wrong-cmd", "args": []}}
        bm = BackendManager(config)

        with patch("pathlib.Path.home", return_value=home), \
             patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: f"/usr/bin/{cmd}" if cmd == "claude-server" else None
            with patch("subprocess.Popen") as mock_popen:
                mock_popen.return_value = MagicMock()
                result = bm.start_server("claude-mcp")

            assert result is not None
            call_args = mock_popen.call_args[0][0]
            assert call_args[0] == "claude-server"

    def test_no_bundle_no_fallback(self, tmp_path):
        """When no bundle exists, don't retry — just fail."""
        from main import BackendManager

        home = self._setup_home(tmp_path)
        config = {"missing-mcp": {"command": "nonexistent", "args": []}}
        bm = BackendManager(config)

        with patch("pathlib.Path.home", return_value=home), \
             patch("shutil.which", return_value=None):
            result = bm.start_server("missing-mcp")
            assert result is None


class TestPersistFixes:
    """Test that bundle fixes get written back to mcp.json."""

    def test_persist_fixes_writes_to_config(self, tmp_path):
        from main import BackendManager, _save_config

        config_path = tmp_path / "mcp.json"
        config = {
            "mode": "gateway",
            "servers": {
                "broken-mcp": {"command": "wrong-cmd", "args": [], "timeout": 120000}
            }
        }
        config_path.write_text(json.dumps(config))

        bm = BackendManager(config["servers"])
        bm._bundle_fixes["broken-mcp"] = {
            "command": "correct-cmd", "args": ["--flag"], "timeout": 120000
        }

        bm.persist_fixes(config, config_path)

        saved = json.loads(config_path.read_text())
        assert saved["servers"]["broken-mcp"]["command"] == "correct-cmd"
        assert saved["servers"]["broken-mcp"]["args"] == ["--flag"]

    def test_persist_fixes_noop_when_no_fixes(self, tmp_path):
        from main import BackendManager

        config_path = tmp_path / "mcp.json"
        original = {"mode": "gateway", "servers": {"ok-mcp": {"command": "ok", "args": []}}}
        config_path.write_text(json.dumps(original))

        bm = BackendManager(original["servers"])
        # No fixes recorded
        bm.persist_fixes(original, config_path)

        saved = json.loads(config_path.read_text())
        assert saved == original  # unchanged
