#!/usr/bin/env python3
"""
MCP Server with HTTP/SSE transport for multiple concurrent clients.

This server allows multiple AI agents (Claude Desktop, Cline, Cursor, etc.)
to connect to a single pprof-analyzer MCP instance over HTTP.

The tool definitions are shared with mcp/main.py to avoid duplication.

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
import logging
import sys
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from uvicorn import Config, Server

from mcp_tools.main import server  # Import shared server with all tools defined

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


@app.get("/sse")
async def sse_endpoint():
    """MCP SSE transport endpoint for connecting agents.

    This endpoint implements the MCP stdio-compatible protocol over HTTP using
    Server-Sent Events (SSE). Multiple clients can connect simultaneously.

    Agents (Claude Desktop, Cline, Cursor, etc.) connect here to access MCP tools.
    """
    logger.info("New MCP client connected via SSE")

    async def event_stream():
        """Stream MCP messages as SSE events."""
        try:
            # Run server with SSE transport (synchronous call in async context)
            server.run("sse")
        except Exception as e:
            logger.error(f"SSE transport error: {e}", exc_info=True)
            yield f"event: error\ndata: {str(e)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
        default=8000,
        help="Port to listen on (default: 8000)",
    )
    args = parser.parse_args()

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
