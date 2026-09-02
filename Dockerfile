# Minimal MCP Server HTTP container
FROM python:3.10-slim

WORKDIR /app

# Create non-root user for security
RUN useradd -m -u 1000 mcp

# Install git and other dependencies
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY mcp_tools/requirements.txt .
COPY skill/pprof_analyzer/requirements.txt ./pprof_analyzer_requirements.txt
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    -r requirements.txt \
    -r pprof_analyzer_requirements.txt

# Copy application code
COPY prompts/ ./prompts/
COPY mcp_tools/ ./mcp_tools/
COPY skill/ ./skill/
COPY action/ ./action/
COPY mcp_server_http.py .

# Switch to non-root user
USER mcp

# Expose port (default 8000)
EXPOSE 8000
ENV MCP_HTTP_PORT=8000

# Health check (reads MCP_HTTP_PORT so it stays correct if the port is
# overridden). If you override the port, set -e MCP_HTTP_PORT=<port> too
# instead of (or in addition to) passing --port, so the healthcheck agrees
# with the port the server actually bound.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"MCP_HTTP_PORT\", 8000)}/health')"

# Run server (default to localhost; use MCP_API_KEY + --host 0.0.0.0 for network access)
ENTRYPOINT ["python", "mcp_server_http.py"]
CMD ["--host", "127.0.0.1", "--port", "8000"]
