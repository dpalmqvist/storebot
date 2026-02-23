"""Tests for MCP server."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from storebot.mcp_server import _MCP_EXCLUDED_TOOLS, _build_tools, _create_server, main
from storebot.tools.definitions import TOOLS


class TestBuildTools:
    def test_returns_correct_count(self):
        tools = _build_tools()
        assert len(tools) == len(TOOLS) - len(_MCP_EXCLUDED_TOOLS)

    def test_tool_has_name(self):
        tools = _build_tools()
        names = {t.name for t in tools}
        assert "search_tradera" in names
        assert "create_draft_listing" in names
        assert "business_summary" in names

    def test_tool_has_description(self):
        tools = _build_tools()
        for t in tools:
            assert t.description, f"Tool {t.name} has no description"

    def test_tool_has_input_schema(self):
        tools = _build_tools()
        for t in tools:
            assert t.inputSchema is not None, f"Tool {t.name} has no inputSchema"
            assert t.inputSchema.get("type") == "object", (
                f"Tool {t.name} schema type is not object"
            )

    def test_excludes_agent_internal_tools(self):
        """Agent-internal tools like request_tools should not appear in MCP tool list."""
        tools = _build_tools()
        names = {t.name for t in tools}
        for excluded in _MCP_EXCLUDED_TOOLS:
            assert excluded not in names, f"{excluded} should be excluded from MCP tools"


class TestCreateServer:
    def test_creates_server(self):
        services = {"tradera": MagicMock()}
        server = _create_server(services)
        assert server is not None

    def test_list_tools_handler(self):
        services = {"tradera": MagicMock()}
        server = _create_server(services)

        from mcp import types

        async def _run():
            result = await server.request_handlers[types.ListToolsRequest](
                types.ListToolsRequest(method="tools/list")
            )
            return result

        result = asyncio.run(_run())
        assert len(result.root.tools) == len(TOOLS) - len(_MCP_EXCLUDED_TOOLS)

    def test_call_tool_dispatches(self):
        mock_tradera = MagicMock()
        mock_tradera.search.return_value = {"items": []}
        services = {"tradera": mock_tradera}
        server = _create_server(services)

        from mcp import types

        async def _run():
            result = await server.request_handlers[types.CallToolRequest](
                types.CallToolRequest(
                    method="tools/call",
                    params=types.CallToolRequestParams(
                        name="search_tradera",
                        arguments={"query": "test"},
                    ),
                )
            )
            return result

        result = asyncio.run(_run())
        assert len(result.root.content) == 1
        assert result.root.content[0].type == "text"
        parsed = json.loads(result.root.content[0].text)
        assert parsed == {"items": []}

    def test_call_unknown_tool(self):
        services = {}
        server = _create_server(services)

        from mcp import types

        async def _run():
            result = await server.request_handlers[types.CallToolRequest](
                types.CallToolRequest(
                    method="tools/call",
                    params=types.CallToolRequestParams(
                        name="nonexistent",
                        arguments={},
                    ),
                )
            )
            return result

        result = asyncio.run(_run())
        assert result.root.isError is True


class TestMain:
    def test_main_stdio(self):
        """main() with stdio transport runs the stdio event loop."""
        mock_server = MagicMock()
        mock_server.create_initialization_options.return_value = MagicMock()
        mock_server.run = AsyncMock()

        mock_stdio_ctx = MagicMock()
        mock_stdio_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_stdio_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("storebot.mcp_server.get_settings", return_value=MagicMock()),
            patch("storebot.mcp_server.init_db", return_value=MagicMock()),
            patch("storebot.mcp_server.create_services", return_value={}),
            patch("storebot.mcp_server._create_server", return_value=mock_server),
            patch("sys.argv", ["storebot-mcp", "--transport", "stdio"]),
            patch("mcp.server.stdio.stdio_server", return_value=mock_stdio_ctx),
        ):
            main()

        mock_server.run.assert_awaited_once()

    def test_main_http(self):
        """main() with streamable-http transport calls uvicorn.run."""
        mock_server = MagicMock()
        mock_session_manager = MagicMock()
        mock_session_manager.handle_request = AsyncMock()

        with (
            patch("storebot.mcp_server.get_settings", return_value=MagicMock()),
            patch("storebot.mcp_server.init_db", return_value=MagicMock()),
            patch("storebot.mcp_server.create_services", return_value={}),
            patch("storebot.mcp_server._create_server", return_value=mock_server),
            patch(
                "sys.argv", ["storebot-mcp", "--transport", "streamable-http", "--port", "9000"]
            ),
            patch("uvicorn.run") as mock_uvicorn,
            patch(
                "mcp.server.streamable_http_manager.StreamableHTTPSessionManager",
                return_value=mock_session_manager,
            ),
        ):
            main()
            mock_uvicorn.assert_called_once()
            call_kwargs = mock_uvicorn.call_args[1]
            assert call_kwargs.get("port") == 9000
            assert call_kwargs.get("host") == "127.0.0.1"

    def test_main_http_custom_host(self):
        """main() with --host passes host to uvicorn."""
        mock_server = MagicMock()
        mock_session_manager = MagicMock()
        mock_session_manager.handle_request = AsyncMock()

        with (
            patch("storebot.mcp_server.get_settings", return_value=MagicMock()),
            patch("storebot.mcp_server.init_db", return_value=MagicMock()),
            patch("storebot.mcp_server.create_services", return_value={}),
            patch("storebot.mcp_server._create_server", return_value=mock_server),
            patch(
                "sys.argv",
                [
                    "storebot-mcp",
                    "--transport",
                    "streamable-http",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "9000",
                ],
            ),
            patch("uvicorn.run") as mock_uvicorn,
            patch(
                "mcp.server.streamable_http_manager.StreamableHTTPSessionManager",
                return_value=mock_session_manager,
            ),
        ):
            main()
            call_kwargs = mock_uvicorn.call_args[1]
            assert call_kwargs.get("host") == "0.0.0.0"

    def test_main_http_missing_uvicorn(self):
        """main() with HTTP transport raises SystemExit when uvicorn is not installed."""
        import builtins

        real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "uvicorn":
                raise ImportError("No module named 'uvicorn'")
            return real_import(name, *args, **kwargs)

        with (
            patch("storebot.mcp_server.get_settings", return_value=MagicMock()),
            patch("storebot.mcp_server.init_db", return_value=MagicMock()),
            patch("storebot.mcp_server.create_services", return_value={}),
            patch("storebot.mcp_server._create_server", return_value=MagicMock()),
            patch("sys.argv", ["storebot-mcp", "--transport", "streamable-http"]),
            patch("builtins.__import__", side_effect=_mock_import),
            pytest.raises(SystemExit, match="uvicorn"),
        ):
            main()
