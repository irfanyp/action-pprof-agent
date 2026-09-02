"""Regression tests for the HTTP/SSE transport wrapper in mcp_server_http.py."""

from __future__ import annotations

import anyio
import pytest
from starlette.testclient import TestClient

import mcp_server_http


@pytest.fixture
def mounted_app():
    """Build the same app main() builds: FastAPI app + mounted MCP SSE sub-app."""
    app = mcp_server_http.app
    if not any(getattr(route, "path", None) == "/sse" for route in app.routes):
        app.mount("/", mcp_server_http.server.sse_app(host="127.0.0.1"))
    return app


async def _drive_sse_request(app, extra_headers: list[tuple[bytes, bytes]] | None = None) -> list[dict]:
    """Send a raw GET /sse ASGI request, let it emit the initial event, then
    simulate the client disconnecting, and capture every message the app
    sends.

    The crash this guards against (AssertionError: Unexpected message:
    http.response.start) only fires during connection teardown: the SSE
    handler streams the `endpoint` event via raw `send`, and only once the
    client disconnects does the mounted MCP SSE sub-app's disconnect
    handling emit a second, empty `http.response.start` — which
    BaseHTTPMiddleware's body_stream() rejects because it already forwarded
    the first one. So the request must run to a real disconnect, not just
    be cancelled from outside, to reproduce it.

    Host header matches the sse_app's allowed_hosts (host="127.0.0.1") so
    the MCP SDK's DNS-rebinding check doesn't reject the request before it
    reaches ApiKeyMiddleware.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/sse",
        "raw_path": b"/sse",
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1:8000"), *(extra_headers or [])],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }
    messages: list[dict] = []
    call_count = 0

    async def receive():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        # Give the writer task a chance to emit the endpoint event before
        # the simulated client disconnect races it.
        await anyio.sleep(0.2)
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    with anyio.fail_after(5):
        await app(scope, receive, send)

    return messages


@pytest.mark.asyncio
async def test_sse_endpoint_streams_without_asgi_crash(mounted_app):
    """GET /sse must stream the initial `endpoint` event without the server
    raising AssertionError: Unexpected message: http.response.start.

    That crash happens if ApiKeyMiddleware is a starlette.BaseHTTPMiddleware
    subclass, since BaseHTTPMiddleware buffers/rewraps the response and is
    incompatible with the mounted SSE sub-app's raw streaming.
    """
    messages = await _drive_sse_request(mounted_app)

    assert messages, "app never sent a response"
    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 200
    body = b"".join(m["body"] for m in messages if m["type"] == "http.response.body")
    assert b"event: endpoint" in body


@pytest.mark.asyncio
async def test_sse_rejects_missing_api_key(mounted_app, monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret")
    messages = await _drive_sse_request(mounted_app)
    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 403


@pytest.mark.asyncio
async def test_sse_accepts_matching_api_key(mounted_app, monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret")
    messages = await _drive_sse_request(mounted_app, extra_headers=[(b"x-api-key", b"secret")])
    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 200
    body = b"".join(m["body"] for m in messages if m["type"] == "http.response.body")
    assert b"event: endpoint" in body


def test_health_check_exempt_from_api_key(mounted_app, monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret")
    with TestClient(mounted_app) as client:
        response = client.get("/health")
    assert response.status_code == 200
