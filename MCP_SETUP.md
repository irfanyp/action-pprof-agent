# MCP Server Setup Guide

Two transport options: **stdio** for local/single-user use, **HTTP/SSE** for team access over a network.

```bash
make mcp-stdio-run                                  # stdio, local only
python3 mcp_server_http.py                          # HTTP/SSE on localhost:8000
make mcp-http-run                                   # network-accessible (0.0.0.0:9000)
```

HTTP/SSE endpoints: MCP at `/sse`, health at `/health`, docs at `/docs`.

---

## Agent Registration

**Claude Code:**
```bash
claude mcp add --transport stdio pprof-analyzer --scope project -- \
  python3 $(pwd)/mcp_server.py
```

**Claude Desktop / Cursor** (`claude_desktop_config.json`) **and Cline** (`.cline_mcp_settings.json`):
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
For HTTP/SSE, replace `command`/`args` with `"url": "http://localhost:8000/sse"`.

---

## Team Collaboration (HTTP/SSE)

Binding to `0.0.0.0` exposes `run_cpu_profile` to anyone on the network. Set `MCP_API_KEY` first:
```bash
export MCP_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
python3 mcp_server_http.py --host 0.0.0.0 --port 8000
# Share: http://<server-ip>:8000/sse  (and the API key, out of band)
```

**Team members:** register at `local` scope (not `project`) so the key doesn't end up in git-tracked `.mcp.json`:
```bash
claude mcp add --transport sse pprof-analyzer http://<server-ip>:8000/sse \
  -H "X-API-Key: <key>" -s local
```

### Remote tool limitations

Every tool takes `repo_path`/`profile_path` as strings and opens them on the server's disk. Over HTTP, those paths belong to the caller's machine, not the server. To handle this:

- **`analyze_pprof_profile_tool`** — always hidden over HTTP (paths can't resolve remotely). Use `build_pprof_analysis_prompt_tool` instead: run `pprof-to-md` and `git ls-files -- '*.go'` locally, then pass the output as text.
- **`run_cpu_profile_tool`** — hidden unless `MCP_ENABLE_CPU_PROFILE=1` is set (it builds and runs arbitrary repo code on the server).
- **`integrate_pprof_endpoint_tool` / `generate_load_test_tool`** — work remotely (they only check `repo_path` exists, don't read content). Set `PPROF_VERIFY_LOCAL_PATHS=false` on the server to skip that check for remote callers.

---

## Verification

```bash
curl http://localhost:8000/health   # health check
curl http://localhost:8000/         # available tools
curl http://localhost:8000/docs     # API docs
```

---

## Docker Deployment

```bash
make mcp-http-docker-build
make mcp-http-docker-run                            # local dev, -p 8000:8000
make mcp-http-docker-run NETWORK=host               # hosted VM, no NAT overhead
```

**Custom port:** set `-e MCP_HTTP_PORT=<port>` to match `--port`, or the healthcheck reports `unhealthy`:
```bash
docker run -d --network host --name mcp-server \
  -e MCP_HTTP_PORT=8991 pprof-analyzer-mcp --port 8991
```

**Compose:**
```yaml
services:
  mcp-server:
    build: .
    ports: ["8000:8000"]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

**Systemd:** `ExecStart=/usr/bin/python3 /path/to/mcp_server_http.py --host 0.0.0.0 --port 8000`, `Restart=always`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Port already in use | `lsof -i :8000`, or run with `--port 9000` |
| Connection refused from another machine | Bind with `--host 0.0.0.0` |
| Container `unhealthy` despite working server | Custom `--port` needs matching `-e MCP_HTTP_PORT=<port>` |
| Import errors | `make setup-env` |
| Container exits immediately | `docker logs <container-id>`, or `docker run -it pprof-analyzer-mcp /bin/bash` |

---

## Reference

| Feature | Stdio | HTTP/SSE |
|---|---|---|
| Setup | Simple | Moderate |
| Users | Single | Multiple concurrent |
| Network | Local only | Local + remote |
| Best for | Development | Teams, production |

Docker defaults: port `8000` (override with `MCP_HTTP_PORT`), base image `python:3.12-slim`, non-root user `mcp` (UID 1000).

For architectural details, see [AGENTS.md](AGENTS.md).
