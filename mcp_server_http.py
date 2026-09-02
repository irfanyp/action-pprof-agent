#!/usr/bin/env python3
"""
MCP Server with HTTP/SSE transport for multiple concurrent clients.

This server allows multiple AI agents (Claude Desktop, Cline, Cursor, etc.)
to connect to a single pprof-analyzer MCP instance over HTTP.

The tool definitions are shared with mcp_tools/main.py to avoid duplication.

Usage:
    python3 mcp_server_http.py              # Runs on http://localhost:8000
    python3 mcp_server_http.py --port 9000  # Custom port
    python3 mcp_server_http.py --host 0.0.0.0 --port 8000  # Listen on all interfaces

Health check:
    curl http://localhost:8000/health

MCP SSE connection:
    Configure agent to connect to: http://localhost:8000/sse

API Documentation:
    http://localhost:8000/docs

Multiple clients can connect simultaneously to share the same server instance.
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import logging
import os
import sys
from fastapi import FastAPI
from starlette.responses import JSONResponse
from uvicorn import Config, Server

from mcp_tools.main import server  # Import shared server with all tools defined

API_KEY_NAME = "X-API-Key"
API_KEY_HEADER = API_KEY_NAME.lower().encode("ascii")
API_KEY_EXEMPT_PATHS = {"/health"}


class ApiKeyMiddleware:
    """Require a matching X-API-Key header when MCP_API_KEY is set.

    The mounted MCP tools (notably run_cpu_profile) build, run, and shell out
    on the host, so this server must not be left reachable by any client that
    can hit the port. When MCP_API_KEY is unset, auth is skipped (e.g. local
    development), which is why deployments should always set it.

    This is a plain ASGI middleware rather than a starlette.BaseHTTPMiddleware
    subclass: BaseHTTPMiddleware buffers/rewraps the downstream response,
    which breaks the mounted MCP SSE sub-app's streaming responses (the
    stream would crash with "Unexpected message: http.response.start" right
    after the first event). A pure ASGI middleware passes scope/receive/send
    straight through, so streaming is unaffected.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        expected = os.environ.get("MCP_API_KEY")
        if expected and scope["path"] not in API_KEY_EXEMPT_PATHS:
            provided = dict(scope["headers"]).get(API_KEY_HEADER, b"")
            if not hmac.compare_digest(provided, expected.encode("utf-8", "ignore")):
                response = JSONResponse({"detail": "Invalid or missing API key"}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="pprof-analyzer MCP Server",
    description="LLM-powered Go pprof profile analyzer via Model Context Protocol",
    version="0.1.0",
)
app.add_middleware(ApiKeyMiddleware)


@app.get("/")
async def root():
    """Root endpoint with server information."""
    return {
        "name": "pprof-analyzer",
        "version": "0.1.0",
        "description": "LLM-powered Go pprof profile analyzer",
        "protocol": "Model Context Protocol (MCP)",
        "transport": "HTTP + Server-Sent Events (SSE)",
        "endpoints": {
            "sse": "GET /sse (MCP tool connection)",
            "health": "GET /health (health check)",
            "docs": "GET /docs (API documentation)",
        },
        "tools": [
            "analyze_pprof_profile",
            "integrate_pprof_endpoint",
            "generate_load_test",
            "run_cpu_profile",
        ],
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "pprof-analyzer-mcp",
        "protocol": "MCP v2.1.1",
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="pprof-analyzer MCP Server with HTTP/SSE transport",
        epilog="""
Examples:
  python3 mcp_server_http.py                    # localhost:8000
  python3 mcp_server_http.py --port 9000        # localhost:9000
  python3 mcp_server_http.py --host 0.0.0.0     # all interfaces
  python3 mcp_server_http.py --host 0.0.0.0 --port 8000
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1, use 0.0.0.0 for all interfaces)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_HTTP_PORT", 8000)),
        help="Port to listen on (default: 8000)",
    )
    args = parser.parse_args()

    if not os.environ.get("MCP_API_KEY"):
        logger.warning(
            "MCP_API_KEY is not set — /sse is unauthenticated. Anyone who can reach "
            "this port can invoke run_cpu_profile, which builds and runs arbitrary "
            "repo code on this host. Set MCP_API_KEY before binding to a non-local host."
        )

    # Mount the MCP SDK's native SSE transport as a sub-app. It defines its own
    # /sse and /messages/ routes; ApiKeyMiddleware on the outer app covers them too.
    app.mount("/", server.sse_app(host=args.host))

    logger.info("=" * 60)
    logger.info("pprof-analyzer MCP Server Configuration")
    logger.info("=" * 60)
    logger.info(f"Host: {args.host}")
    logger.info(f"Port: {args.port}")
    logger.info(f"URL: http://{args.host}:{args.port}")
    logger.info(f"MCP SSE: http://{args.host}:{args.port}/sse")
    logger.info(f"API Docs: http://{args.host}:{args.port}/docs")
    logger.info(f"Health: http://{args.host}:{args.port}/health")
    logger.info("=" * 60)
    logger.info("Waiting for MCP client connections...")
    logger.info("=" * 60)

    config = Config(
        app=app,
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=True,
    )
    server_instance = Server(config)

    try:
        asyncio.run(server_instance.serve())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
