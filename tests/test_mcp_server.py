"""Tests for MCP server."""

import asyncio
import json
from unittest.mock import MagicMock

from storebot.mcp_server import _build_tools, _create_server
from storebot.tools.definitions import TOOLS


class TestBuildTools:
    def test_returns_correct_count(self):
        tools = _build_tools()
        assert len(tools) == len(TOOLS)

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
            assert (
                t.inputSchema.get("type") == "object"
            ), f"Tool {t.name} schema type is not object"

    def test_strips_internal_fields(self):
        """Internal fields (category, strict) should not leak into MCP schema."""
        tools = _build_tools()
        for t in tools:
            assert "category" not in (t.inputSchema or {}), f"Tool {t.name} has category in schema"


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
        assert len(result.root.tools) == len(TOOLS)

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
