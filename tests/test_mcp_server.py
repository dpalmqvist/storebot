"""Tests for MCP server."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from storebot.mcp_server import (
    _MCP_EXCLUDED_TOOLS,
    _build_tools,
    _create_server,
    _make_auth_app,
    main,
)
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
        assert "list_price_proposals" in names
        assert "approve_price_proposal" in names
        assert "reject_price_proposal" in names
        assert "end_tradera_listing" in names
        assert "update_tradera_listing_price" in names

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


class TestMakeAuthApp:
    @pytest.mark.asyncio
    async def test_valid_bearer_passes_through(self):
        inner = AsyncMock()
        app = _make_auth_app(inner, "secret-key-123")

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer secret-key-123")],
        }
        await app(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self):
        inner = AsyncMock()
        app = _make_auth_app(inner, "secret-key-123")

        scope = {"type": "http", "headers": []}
        sent = []

        async def mock_send(msg):
            sent.append(msg)

        await app(scope, AsyncMock(), mock_send)
        inner.assert_not_awaited()
        assert sent[0]["status"] == 401
        # RFC 7235: 401 must include WWW-Authenticate with realm
        headers = dict(sent[0]["headers"])
        assert headers[b"www-authenticate"] == b'Bearer realm="storebot-mcp"'
        assert b"content-length" in headers

    @pytest.mark.asyncio
    async def test_wrong_key_returns_401(self):
        inner = AsyncMock()
        app = _make_auth_app(inner, "correct-key")

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer wrong-key")],
        }
        sent = []

        async def mock_send(msg):
            sent.append(msg)

        await app(scope, AsyncMock(), mock_send)
        inner.assert_not_awaited()
        assert sent[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self):
        inner = AsyncMock()
        app = _make_auth_app(inner, "secret-key")

        scope = {"type": "websocket", "headers": []}
        await app(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()


def _mock_settings(**overrides):
    s = MagicMock()
    s.mcp_api_key = overrides.get("mcp_api_key", "")
    return s


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
            patch("storebot.mcp_server.get_settings", return_value=_mock_settings()),
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
            patch("storebot.mcp_server.get_settings", return_value=_mock_settings()),
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

    def test_main_http_custom_host_with_api_key(self):
        """main() with --host 0.0.0.0 and MCP_API_KEY succeeds."""
        mock_server = MagicMock()
        mock_session_manager = MagicMock()
        mock_session_manager.handle_request = AsyncMock()

        with (
            patch(
                "storebot.mcp_server.get_settings",
                return_value=_mock_settings(mcp_api_key="test-key"),
            ),
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

    def test_main_http_non_localhost_without_key_exits(self):
        """main() with --host 0.0.0.0 and no MCP_API_KEY exits with error."""
        mock_server = MagicMock()
        mock_session_manager = MagicMock()
        mock_session_manager.handle_request = AsyncMock()

        with (
            patch("storebot.mcp_server.get_settings", return_value=_mock_settings()),
            patch("storebot.mcp_server.init_db", return_value=MagicMock()),
            patch("storebot.mcp_server.create_services", return_value={}),
            patch("storebot.mcp_server._create_server", return_value=mock_server),
            patch(
                "sys.argv",
                ["storebot-mcp", "--transport", "streamable-http", "--host", "0.0.0.0"],
            ),
            patch("uvicorn.run"),
            patch(
                "mcp.server.streamable_http_manager.StreamableHTTPSessionManager",
                return_value=mock_session_manager,
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 1

    def test_main_http_localhost_no_key_ok(self):
        """main() on localhost without MCP_API_KEY runs fine (no auth needed)."""
        mock_server = MagicMock()
        mock_session_manager = MagicMock()
        mock_session_manager.handle_request = AsyncMock()

        with (
            patch("storebot.mcp_server.get_settings", return_value=_mock_settings()),
            patch("storebot.mcp_server.init_db", return_value=MagicMock()),
            patch("storebot.mcp_server.create_services", return_value={}),
            patch("storebot.mcp_server._create_server", return_value=mock_server),
            patch(
                "sys.argv",
                ["storebot-mcp", "--transport", "streamable-http"],
            ),
            patch("uvicorn.run") as mock_uvicorn,
            patch(
                "mcp.server.streamable_http_manager.StreamableHTTPSessionManager",
                return_value=mock_session_manager,
            ),
        ):
            main()
            mock_uvicorn.assert_called_once()

    def test_main_http_localhost_with_key_enables_auth(self):
        """main() on localhost with MCP_API_KEY wraps app with auth middleware."""
        mock_server = MagicMock()
        mock_session_manager = MagicMock()
        mock_session_manager.handle_request = AsyncMock()

        with (
            patch(
                "storebot.mcp_server.get_settings",
                return_value=_mock_settings(mcp_api_key="my-key"),
            ),
            patch("storebot.mcp_server.init_db", return_value=MagicMock()),
            patch("storebot.mcp_server.create_services", return_value={}),
            patch("storebot.mcp_server._create_server", return_value=mock_server),
            patch(
                "sys.argv",
                ["storebot-mcp", "--transport", "streamable-http"],
            ),
            patch("uvicorn.run") as mock_uvicorn,
            patch(
                "mcp.server.streamable_http_manager.StreamableHTTPSessionManager",
                return_value=mock_session_manager,
            ),
            patch("storebot.mcp_server._make_auth_app", wraps=_make_auth_app) as mock_auth,
        ):
            main()
            mock_uvicorn.assert_called_once()
            mock_auth.assert_called_once()
            assert mock_auth.call_args[1].get("api_key", mock_auth.call_args[0][1]) == "my-key"
