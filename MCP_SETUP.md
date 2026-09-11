# MCP Server Setup Guide

Two transport options: **stdio** for local/single-user use, **HTTP/SSE** for team access over a network.

```bash
make mcp-stdio-run                                  # stdio, local only
python3 mcp_server_http.py                          # HTTP/SSE on localhost:8000
make mcp-http-run                                   # network-accessible, custom port (0.0.0.0:9000)
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

**Server machine:** binding to `0.0.0.0` exposes `run_cpu_profile` to anyone
on the network who can reach the port. Since it builds and runs arbitrary
repo code, set `MCP_API_KEY` first:
```bash
export MCP_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
python3 mcp_server_http.py --host 0.0.0.0 --port 8000
# Share: http://<server-ip>:8000/sse  (and the API key, out of band)
```

**Team members:** add the shared URL to their agent config with an
`X-API-Key: <key>` header. For Claude Code, pass it via `-H` and register at
`local` (not `project`) scope, so the key doesn't end up in the shared,
git-tracked `.mcp.json`:
```bash
claude mcp add --transport sse pprof-analyzer http://<server-ip>:8000/sse \
  -H "X-API-Key: <key>" -s local
```

**Why paths break remotely:** every tool takes `repo_path`/`profile_path` as
strings and opens them directly. Over HTTP those are just text — the server
opens *its own* disk at that path, not yours, and fails (or reads the wrong
file if a coincidentally-valid path exists there). To stop agents from
calling a tool that can never work remotely, the HTTP transport (unlike
stdio) hides `analyze_pprof_profile` entirely, and hides `run_cpu_profile`
unless `MCP_ENABLE_CPU_PROFILE` is set — see `configure_http_only_tools()` in
`mcp_server_http.py`.

- `integrate_pprof_endpoint` and `generate_load_test` don't read repo
  content — they only check that `repo_path` exists and has a `go.mod`, then
  return a generic prompt with `repo_path` embedded as a label for your own
  agent to inspect locally. Set `PPROF_VERIFY_LOCAL_PATHS=false` on the server
  to skip that check (it can never pass for a remote caller), and these two
  tools work as-is.
- `analyze_pprof_profile` needs real content (the converted profile + which Go
  files exist), so a bare path can't work remotely. Use
  `build_pprof_analysis_prompt` instead: run `pprof-to-md --format detailed
  <profile> -o result.md` and `git ls-files -- '*.go'` **on your own machine**,
  then pass the output as `analyzer_result`/`file_list`. Only that derived
  text crosses the network — the raw profile and your repo's source never
  leave your machine.
- `run_cpu_profile` builds and executes the target repo's code on whatever
  host runs it — that's inherent to what it does, not something to work
  around. It's disabled by default (even with `MCP_API_KEY` set), since
  profiling normally happens locally anyway. Set `MCP_ENABLE_CPU_PROFILE=1`
  only if you want the server itself to build+run repos (single-tenant/trusted
  use).

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

**Custom port:** the image's `HEALTHCHECK` probes `$MCP_HTTP_PORT` (default `8000`).
If you override `--port`, set `-e MCP_HTTP_PORT=<port>` too, or the container
reports `unhealthy` even while the server works fine:
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

**Systemd** (`ExecStart=/usr/bin/python3 /path/to/mcp_server_http.py --host 0.0.0.0 --port 8000`,
`Restart=always`) works the same as any long-running Python service.

**Registry push:** tag and `docker push` as usual (Docker Hub, ACR, ECR, etc.) —
no project-specific steps beyond the standard `docker tag <image> <registry>/<name>:<tag>`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Port already in use | `lsof -i :8000`, or run with `--port 9000` |
| Connection refused from another machine | Bind with `--host 0.0.0.0` |
| Container `unhealthy` despite working server | Custom `--port` needs matching `-e MCP_HTTP_PORT=<port>` |
| Import errors | `make setup-env` |
| Container exits immediately | `docker logs <container-id>`, or `docker run -it pprof-analyzer-mcp /bin/bash` to debug |

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
