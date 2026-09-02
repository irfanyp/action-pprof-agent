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

**Server machine:** binding to `0.0.0.0` makes `run_cpu_profile` reachable by
anyone on the network who can hit the port — it builds and runs arbitrary
repo code, so set `MCP_API_KEY` before doing this:
```bash
export MCP_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
python3 mcp_server_http.py --host 0.0.0.0 --port 8000
# Share: http://<server-ip>:8000/sse  (and the API key, out of band)
```

**Team members:** use the shared URL in their agent config, with an
`X-API-Key: <key>` header. For Claude Code, add it with `-H` and register at
`local` (not `project`) scope so the key doesn't land in the shared,
git-tracked `.mcp.json`:
```bash
claude mcp add --transport sse pprof-analyzer http://<server-ip>:8000/sse \
  -H "X-API-Key: <key>" -s local
```

**What actually works once the server and your repo/profile are on different
machines:** every tool takes `repo_path`/`profile_path` as strings and opens
them directly — over HTTP those are just text sent from your machine, so the
server tries to open *your* local paths on *its own* disk and fails (or, if a
coincidentally-valid path exists on the server, reads the wrong thing).

- `integrate_pprof_endpoint` and `generate_load_test` don't actually read any
  repo content — they only sanity-check that `repo_path` exists and has a
  `go.mod`, then return a generic prompt with `repo_path` embedded as a label
  for your own agent to inspect locally. Set `PPROF_VERIFY_LOCAL_PATHS=false`
  on the server to skip that check (it can never pass for a remote caller
  anyway), and these two tools work as-is.
- `analyze_pprof_profile` does need real content (the converted profile +
  which Go files exist), so it can't be called with a bare path remotely. Use
  `build_pprof_analysis_prompt` instead: run `pprof-to-md --format detailed
  <profile> -o result.md` and `git ls-files -- '*.go'` **on your own machine**,
  then pass their output as `analyzer_result`/`file_list`. Nothing but that
  derived text ever crosses the network — the raw profile and your repo's
  source never leave your machine.
- `run_cpu_profile` builds and executes the target repo's code on whatever
  host runs it, which can't be redesigned around — it's disabled by default
  (even with `MCP_API_KEY` set) since profiling normally happens locally
  anyway. Set `MCP_ENABLE_CPU_PROFILE=1` on the server only if you specifically
  want the cloud host itself to build+run repos (single-tenant/trusted use).

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

**Using a custom port:** the image's `HEALTHCHECK` reads the `MCP_HTTP_PORT`
env var (default `8000`) to know which port to probe. If you override the
port via `--port`, set `-e MCP_HTTP_PORT=<port>` too, or the healthcheck will
probe the wrong port and the container will show as `unhealthy` even though
the server is working fine:
```bash
docker run -d \
  --network host \
  --name mcp-server \
  -e MCP_HTTP_PORT=8991 \
  pprof-analyzer-mcp --port 8991
```

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

**Container shows `unhealthy` despite the server working:**
```bash
# The HEALTHCHECK probes $MCP_HTTP_PORT (default 8000). If you passed a
# custom --port without also setting MCP_HTTP_PORT, it's probing the wrong
# port. Recreate the container with matching values, e.g.:
docker run -d --network host --name mcp-server \
  -e MCP_HTTP_PORT=8991 pprof-analyzer-mcp --port 8991
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
- `MCP_HTTP_PORT` env var: must match `--port` or the `HEALTHCHECK` probes the wrong port
- Health: `GET /health`
- MCP SSE: `GET /sse`
- Docs: `GET /docs`
- Base image: `python:3.10-slim`
- Non-root user: `mcp` (UID 1000)

---

For architectural details, see [AGENTS.md](AGENTS.md).
