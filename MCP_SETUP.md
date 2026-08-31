# MCP Server Setup Guide

This guide shows how to set up and register the **pprof-analyzer MCP Server** with different AI agents.

## Prerequisites

```bash
# Install dependencies
pip install -e .
```

---

## Architecture Note

The MCP server has three layers:
1. **`mcp_tools/main.py`** — Core MCP server implementation
2. **`mcp_server.py`** — Thin wrapper that delegates to `mcp_tools/main.py` for stdio transport
3. **`mcp_server_http.py`** — Adds HTTP/SSE transport for team collaboration

When using either Option A or B below, you're using the same core server with different transports.

---

## Quick Start

### Option A: Stdio Transport (Single User)
Best for: Local development, single agent

```bash
python3 mcp_server.py
```

This runs the server with stdio transport (stdin/stdout IPC). Ideal for local development.

Register with Claude Code:
```bash
claude mcp add --transport stdio pprof-analyzer --scope project -- \
  python3 $(pwd)/mcp_server.py
```

---

### Option B: HTTP/SSE Transport (Multiple Users) ⭐ Recommended
Best for: Multiple users, team collaboration, production

```bash
# Start HTTP server
python3 mcp_server_http.py              # http://localhost:8000
python3 mcp_server_http.py --port 9000  # Custom port
python3 mcp_server_http.py --host 0.0.0.0  # Listen on all interfaces
```

This runs the server with HTTP/SSE transport, allowing multiple concurrent clients to connect via a network endpoint.

Access:
- **MCP Endpoint:** `http://localhost:8000/sse`
- **Health Check:** `http://localhost:8000/health`
- **API Docs:** `http://localhost:8000/docs`

---

## Agent-Specific Registration

### 1. Claude Desktop

Edit `~/.claude_desktop/claude_desktop_config.json`:

**Option A (Stdio):**
```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "command": "python3",
      "args": ["/absolute/path/to/pprof-analyzer/mcp_server.py"]
    }
  }
}
```

**Option B (HTTP/SSE):**
```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

Restart Claude Desktop to load changes.

---

### 2. Claude Code

**Option A (Stdio):**
```bash
claude mcp add --transport stdio pprof-analyzer --scope project -- \
  python3 $(pwd)/mcp_server.py
```

**Option B (HTTP/SSE):**
Configure `.claude/claude.json` or use Claude Code CLI:
```bash
# HTTP endpoint support coming in next Claude Code release
# For now, use stdio transport above
```

---

### 3. Cline (VSCode Extension)

Create `.cline_mcp_settings.json` in your project root:

**Option A (Stdio):**
```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "command": "python3",
      "args": ["/absolute/path/to/pprof-analyzer/mcp_server.py"]
    }
  }
}
```

**Option B (HTTP/SSE):**
```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

Cline will auto-detect and load this file.

---

### 4. Cursor

Edit `~/.cursor/settings/claude_desktop_config.json`:

**Option A (Stdio):**
```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "command": "python3",
      "args": ["/absolute/path/to/pprof-analyzer/mcp_server.py"]
    }
  }
}
```

**Option B (HTTP/SSE):**
```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

Restart Cursor.

---

## Team Setup (HTTP/SSE Recommended)

For multiple team members to share a single MCP server:

### Server Machine (1 person)
```bash
# Start HTTP server accessible to team
python3 mcp_server_http.py --host 0.0.0.0 --port 8000

# Share the URL with your team
# http://<server-ip>:8000/sse
```

### Team Members (all agents)
Use the shared URL in their agent config:

```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "url": "http://<server-ip>:8000/sse"
    }
  }
}
```

Benefits:
- Single server instance for team
- Reduced resource usage
- Shared context and cache
- Easy to maintain and update

---

## Verification

### Check Server Health
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "pprof-analyzer-mcp",
  "protocol": "MCP v2.1.1"
}
```

### Check Available Tools
```bash
curl http://localhost:8000/
```

Expected response shows all available tools:
- `analyze_pprof_profile`
- `integrate_pprof_endpoint`
- `generate_load_test`
- `run_cpu_profile`

### View API Documentation
Open in browser: `http://localhost:8000/docs`

---

## Troubleshooting

### Port Already in Use
```bash
# Use a different port
python3 mcp_server_http.py --port 9000

# Or find what's using the port
lsof -i :8000
```

### Connection Refused
```bash
# If connecting from another machine, use 0.0.0.0
python3 mcp_server_http.py --host 0.0.0.0 --port 8000

# Make sure firewall allows the port
```

### Import Errors
```bash
# Reinstall in editable mode
pip install -e .
```

### SSL/HTTPS for Remote Access
For production, use a reverse proxy (nginx, Caddy):

```bash
# Install Caddy
# Create Caddyfile:
# pprof-analyzer.example.com {
#   reverse_proxy localhost:8000
# }

caddy run
```

---

## Comparison: Stdio vs HTTP/SSE

| Feature | Stdio | HTTP/SSE |
|---------|-------|----------|
| **Setup** | Simple | Requires HTTP server |
| **Users** | Single | Multiple concurrent |
| **Network** | Local only | Local + remote |
| **Firewall** | N/A | Requires open port |
| **Team** | Each needs own instance | Single shared instance |
| **Resources** | Minimal | One process per user |
| **Latency** | Lowest | Slightly higher |

---

## Production Deployment

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install -e .

EXPOSE 8000

CMD ["python3", "mcp_server_http.py", "--host", "0.0.0.0"]
```

Build and run:
```bash
docker build -t pprof-analyzer-mcp .
docker run -p 8000:8000 pprof-analyzer-mcp
```

### Systemd Service

Create `/etc/systemd/system/pprof-analyzer-mcp.service`:
```ini
[Unit]
Description=pprof-analyzer MCP Server
After=network.target

[Service]
Type=simple
User=mcp
WorkingDirectory=/home/mcp/pprof-analyzer
ExecStart=/usr/bin/python3 /home/mcp/pprof-analyzer/mcp_server_http.py --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Start service:
```bash
sudo systemctl enable pprof-analyzer-mcp
sudo systemctl start pprof-analyzer-mcp
sudo systemctl status pprof-analyzer-mcp
```

---

## Next Steps

1. Start the server (stdio or HTTP)
2. Register with your AI agent
3. Test by analyzing a pprof profile
4. Share the setup with your team (for HTTP)

For help: Check the [README.md](README.md) or [AGENTS.md](AGENTS.md)
