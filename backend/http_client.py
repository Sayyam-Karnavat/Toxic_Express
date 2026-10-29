"""Shared httpx client for outbound calls to trusted APIs (Google, OpenAI, Resend).

Never use this client for user-supplied URLs; those go through safe_fetch.py (SSRF guard).
"""

import httpx

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            headers={"User-Agent": "Toxic-Express/1.0"},
            follow_redirects=False,
        )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
