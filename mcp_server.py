#!/usr/bin/env python3
"""
MCP Server entry point for pprof-analyzer (Stdio transport).

Runs the Model Context Protocol server that exposes pprof analysis tools
to Claude Desktop, Cline, Cursor, and other MCP-compatible agents.

Usage:
    python3 mcp_server.py

Registration (Claude Code):
    claude mcp add --transport stdio pprof-analyzer --scope project -- \\
      python3 $(pwd)/mcp_server.py

Registration (Claude Desktop):
    Edit ~/.claude_desktop/claude_desktop_config.json and add:
    {
      "mcpServers": {
        "pprof-analyzer": {
          "command": "python3",
          "args": ["/path/to/pprof-analyzer/mcp_server.py"]
        }
      }
    }

For HTTP/SSE transport (multiple users), use mcp_server_http.py instead.
"""
import asyncio
from mcp_tools.main import main

if __name__ == "__main__":
    asyncio.run(main())
