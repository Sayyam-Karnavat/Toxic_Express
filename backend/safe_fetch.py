"""SSRF-safe HTTP GET for user-supplied URLs (link previews, remote avatars).

The guard runs at connect time inside the HTTP client, after DNS resolution, so DNS rebinding and
redirects to internal addresses are blocked too. Only public unicast IPs on ports 80/443 are
reachable, responses are size-capped and redirects are re-validated hop by hop.
"""

import ipaddress
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import anyio
import httpcore
from httpcore._backends.anyio import AnyIOBackend

MAX_REDIRECTS = 3
USER_AGENT = b"Toxic-Express-LinkPreview/1.0 (+https://toxic-express.app)"


class BlockedURLError(Exception):
    pass


def is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


class _GuardedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self._inner = AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore backend interface
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = [str(info[4][0]) for info in infos]
        if not addresses or not all(is_public_ip(a) for a in addresses):
            raise BlockedURLError(f"{host} resolves to a non-public address")
        # Connect to the vetted IP; TLS still verifies the certificate for the original host.
        return await self._inner.connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, *args: Any, **kwargs: Any) -> httpcore.AsyncNetworkStream:
        raise BlockedURLError("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def validate_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BlockedURLError("only http(s) URLs are allowed")
    if parts.username or parts.password:
        raise BlockedURLError("credentials in URLs are not allowed")
    if parts.port not in (None, 80, 443):
        raise BlockedURLError("only ports 80 and 443 are allowed")
    host = parts.hostname
    try:
        if not is_public_ip(host):
            raise BlockedURLError("non-public IP address")
    except ValueError:
        pass  # a hostname; checked after DNS resolution
    return url


@dataclass
class FetchResult:
    url: str
    status: int
    content_type: str
    body: bytes


async def safe_get(
    url: str,
    *,
    max_bytes: int,
    timeout: float = 6.0,  # noqa: ASYNC109 - enforced via anyio.fail_after below
    accept: str = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
) -> FetchResult:
    async with httpcore.AsyncConnectionPool(
        network_backend=_GuardedBackend(), max_connections=2, retries=0, http2=False
    ) as pool:
        with anyio.fail_after(timeout * 2):
            for _ in range(MAX_REDIRECTS + 1):
                validate_url(url)
                headers = [
                    (b"User-Agent", USER_AGENT),
                    (b"Accept", accept.encode()),
                    (b"Accept-Encoding", b"identity"),
                ]
                extensions = {
                    "timeout": {
                        "connect": timeout,
                        "read": timeout,
                        "write": timeout,
                        "pool": timeout,
                    }
                }
                async with pool.stream("GET", url, headers=headers, extensions=extensions) as resp:
                    response_headers = {
                        k.decode().lower(): v.decode("latin-1") for k, v in resp.headers
                    }
                    if resp.status in (301, 302, 303, 307, 308) and "location" in response_headers:
                        url = urljoin(url, response_headers["location"])
                        continue
                    body = bytearray()
                    async for chunk in resp.aiter_stream():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            break
                    return FetchResult(
                        url=url,
                        status=resp.status,
                        content_type=response_headers.get("content-type", "").split(";")[0].strip(),
                        body=bytes(body[:max_bytes]),
                    )
    raise BlockedURLError("too many redirects")
