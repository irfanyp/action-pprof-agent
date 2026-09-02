# MCP Server Setup Guide

Two transport options for the pprof-analyzer MCP server:

---

## Quick Start

### Option A: Stdio (Local Development)
Single user, simplest setup.

```bash
python3 mcp_server.py
```

### Option B: HTTP/SSE (Team Collaboration) ⭐ Recommended
Multiple concurrent users, network accessible.

```bash
python3 mcp_server_http.py                        # localhost:8000
python3 mcp_server_http.py --host 0.0.0.0         # all interfaces
python3 mcp_server_http.py --port 9000             # custom port
```

**Endpoints:**
- MCP: `http://localhost:8000/sse`
- Health: `http://localhost:8000/health`
- Docs: `http://localhost:8000/docs`

---

## Agent Registration

### Claude Code
```bash
claude mcp add --transport stdio pprof-analyzer --scope project -- \
  python3 $(pwd)/mcp_server.py
```

### Claude Desktop
Edit `~/.claude_desktop/claude_desktop_config.json`:

**Stdio:**
```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "command": "python3",
      "args": ["/absolute/path/to/mcp_server.py"]
    }
  }
}
```

**HTTP/SSE:**
```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

### Cline (VSCode)
Create `.cline_mcp_settings.json` in project root:

**Stdio:**
```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "command": "python3",
      "args": ["/absolute/path/to/mcp_server.py"]
    }
  }
}
```

**HTTP/SSE:**
```json
{
  "mcpServers": {
    "pprof-analyzer": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

### Cursor
Edit `~/.cursor/settings/claude_desktop_config.json` (same as Claude Desktop above).

---

## Team Collaboration (HTTP/SSE)

**Server machine:**
```bash
python3 mcp_server_http.py --host 0.0.0.0 --port 8000
# Share: http://<server-ip>:8000/sse
```

**Team members:** Use shared URL in their agent config (see above).

---

## Verification

```bash
# Health check
curl http://localhost:8000/health

# Root endpoint (shows available tools)
curl http://localhost:8000/

# API docs
curl http://localhost:8000/docs
```

---

## Docker Deployment

### Build
```bash
docker build -t pprof-analyzer-mcp .
```

### Run — Local Development
```bash
docker run -p 8000:8000 pprof-analyzer-mcp
```

### Run — Hosted VM (Host Networking) ⭐
```bash
docker run -d \
  --network host \
  --name mcp-server \
  pprof-analyzer-mcp --port 8000
```

This binds directly to VM port `8000` with no NAT overhead.

### Docker Compose
```yaml
version: '3.8'
services:
  mcp-server:
    build: .
    ports:
      - "8000:8000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

Run: `docker-compose up -d`

### Push to Registry
```bash
# Docker Hub
docker tag pprof-analyzer-mcp <username>/pprof-analyzer-mcp:0.1.0
docker push <username>/pprof-analyzer-mcp:0.1.0

# Azure ACR
docker tag pprof-analyzer-mcp myregistry.azurecr.io/pprof-analyzer-mcp:0.1.0
docker push myregistry.azurecr.io/pprof-analyzer-mcp:0.1.0

# AWS ECR
docker tag pprof-analyzer-mcp 123456789.dkr.ecr.us-east-1.amazonaws.com/pprof-analyzer-mcp:0.1.0
docker push 123456789.dkr.ecr.us-east-1.amazonaws.com/pprof-analyzer-mcp:0.1.0
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

Enable and start:
```bash
sudo systemctl enable pprof-analyzer-mcp
sudo systemctl start pprof-analyzer-mcp
```

---

## Troubleshooting

**Port already in use:**
```bash
lsof -i :8000        # Find what's using it
# Or use different port:
python3 mcp_server_http.py --port 9000
```

**Connection refused (from another machine):**
```bash
# Use 0.0.0.0 to listen on all interfaces
python3 mcp_server_http.py --host 0.0.0.0 --port 8000
```

**Import errors:**
```bash
pip install -e .
```

**Docker: Container exits immediately:**
```bash
docker logs <container-id>
docker run -it pprof-analyzer-mcp /bin/bash  # Debug shell
```

---

## Reference

| Feature | Stdio | HTTP/SSE |
|---------|-------|----------|
| Setup | Simple | Moderate |
| Users | Single | Multiple concurrent |
| Network | Local only | Local + remote |
| Best for | Development | Teams, production |

**Docker reference:**
- Default port: `8000`
- Health: `GET /health`
- MCP SSE: `GET /sse`
- Docs: `GET /docs`
- Base image: `python:3.10-slim`
- Non-root user: `mcp` (UID 1000)

---

For architectural details, see [AGENTS.md](AGENTS.md).
