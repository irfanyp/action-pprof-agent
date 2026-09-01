# Minimal MCP Server HTTP container
FROM python:3.10-slim

WORKDIR /app

# Create non-root user for security
RUN useradd -m -u 1000 mcp

# Install dependencies
COPY mcp_tools/requirements.txt .
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    -r mcp_tools/requirements.txt \
    fastapi uvicorn[standard]

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

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run server (allow custom host/port via environment or args)
ENTRYPOINT ["python", "mcp_server_http.py"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
