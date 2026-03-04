"""MCP server exposing all storebot tools.

Usage:
    storebot-mcp                              # stdio transport (default)
    storebot-mcp --transport streamable-http   # HTTP transport on port 8080
    storebot-mcp --transport streamable-http --port 9000
"""

import argparse
import asyncio
import hmac
import json
import logging
import sys

from mcp import types
from mcp.server.lowlevel import Server

from storebot.config import Settings, get_settings
from storebot.db import init_db
from storebot.tools.definitions import TOOLS
from storebot.tools.dispatch import create_services, execute_tool

logger = logging.getLogger(__name__)

# Agent-internal tools not applicable to MCP clients.
_MCP_EXCLUDED_TOOLS = {"request_tools"}


def _build_tools() -> list[types.Tool]:
    """Convert definitions.py TOOLS to MCP Tool objects."""
    mcp_tools = []
    for tool_def in TOOLS:
        if tool_def["name"] in _MCP_EXCLUDED_TOOLS:
            continue
        schema = dict(tool_def["input_schema"])
        mcp_tools.append(
            types.Tool(
                name=tool_def["name"],
                description=tool_def["description"],
                inputSchema=schema,
            )
        )
    return mcp_tools


def _create_server(services: dict[str, object]) -> Server:
    """Create and configure the MCP server with tool handlers."""
    server = Server("storebot")
    tools = _build_tools()

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return tools

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None) -> types.CallToolResult:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, execute_tool, services, name, arguments or {})
        text = json.dumps(result, default=str)
        is_error = "error" in result
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            isError=is_error,
        )

    return server


def _make_auth_app(inner_app, api_key: str):
    """Wrap an ASGI app with Bearer token authentication."""

    async def _auth_app(scope, receive, send):
        if scope["type"] != "http":
            await inner_app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()
        expected = f"Bearer {api_key}"

        if not hmac.compare_digest(auth, expected):
            logger.warning("MCP HTTP request rejected — invalid or missing API key")
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [[b"content-type", b"application/json"]],
                }
            )
            await send({"type": "http.response.body", "body": b'{"error":"Unauthorized"}'})
            return

        await inner_app(scope, receive, send)

    return _auth_app


def main():
    """Entry point for storebot-mcp CLI."""
    parser = argparse.ArgumentParser(description="Storebot MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport type (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for HTTP transport (default: 8080)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    engine = init_db()
    services = create_services(settings, engine)

    server = _create_server(services)

    if args.transport == "stdio":
        from mcp.server.stdio import stdio_server

        async def _run_stdio():
            async with stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )

        asyncio.run(_run_stdio())
    else:
        _run_http(args, settings, server)


def _run_http(args, settings: Settings, server: Server) -> None:
    """Start the MCP server with streamable-HTTP transport."""
    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    is_localhost = args.host == "127.0.0.1"
    api_key = settings.mcp_api_key

    if not is_localhost and not api_key:
        logger.error(
            "MCP_API_KEY is required when binding to non-localhost (%s). "
            "Set MCP_API_KEY in .env or use --host 127.0.0.1.",
            args.host,
        )
        sys.exit(1)

    if not is_localhost and api_key:
        logger.info("MCP HTTP server bound to %s with API key authentication", args.host)
    elif not is_localhost:
        logger.warning(
            "MCP HTTP server bound to %s — no authentication is enforced. "
            "All storebot tools are accessible to any client that can reach this port.",
            args.host,
        )

    session_manager = StreamableHTTPSessionManager(app=server, stateless=True)

    async def asgi_app(scope, receive, send):
        await session_manager.handle_request(scope, receive, send)

    app = asgi_app
    if api_key:
        app = _make_auth_app(asgi_app, api_key)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
