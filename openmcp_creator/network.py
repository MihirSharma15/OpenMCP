"""Bounded public HTTP reads with address pinning and per-hop redirect checks."""

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from .models import origin


class PublicHTTP:
    def __init__(self, *, allow_loopback=False, transport=None, resolver=None):
        self.allow_loopback = allow_loopback
        self.resolver = resolver
        self.client = httpx.AsyncClient(transport=transport, timeout=25, trust_env=False)

    async def close(self):
        await self.client.aclose()

    async def address(self, url):
        origin(url)
        parsed = urlsplit(url)
        if parsed.port not in {None, 80, 443} and not self.allow_loopback:
            raise ValueError("Only standard public HTTP ports are allowed")
        if self.resolver:
            addresses = await self.resolver(parsed.hostname)
        else:
            records = await asyncio.get_running_loop().getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            addresses = {r[4][0] for r in records}
        if not addresses:
            raise ValueError("No public address")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global and not (self.allow_loopback and ip.is_loopback):
                raise ValueError("Private, local and metadata addresses are prohibited")
        if parsed.scheme != "https" and not (
            self.allow_loopback and all(ipaddress.ip_address(a).is_loopback for a in addresses)
        ):
            raise ValueError("Public sources must use HTTPS")
        return sorted(addresses)[0]

    async def request(
        self,
        url,
        *,
        method="GET",
        headers=None,
        content=None,
        allowed_origin=None,
        follow_redirects=True,
    ):
        for _ in range(6):
            if allowed_origin is not None and origin(url) != allowed_origin:
                raise ValueError("Authenticated requests cannot redirect to another origin")
            ip = await self.address(url)
            target = httpx.URL(url)
            # httpx keys its cookie jar by the pinned IP. Never reuse that jar
            # across source hostnames; the browser supplies its own scoped cookies.
            request_headers = {"User-Agent": "OpenMCP-Creator/0.1", "Cookie": "", **(headers or {})}
            request_headers["Host"] = target.netloc.decode()
            # The connection goes to the validated IP, while TLS verifies the original host.
            async with self.client.stream(
                method,
                target.copy_with(host=ip),
                headers=request_headers,
                content=content,
                extensions={"sni_hostname": target.host.encode()},
            ) as response:
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 1_000_000:
                        raise ValueError("Source response exceeds 1 MB")
                    chunks.append(chunk)
                result = httpx.Response(
                    response.status_code,
                    headers=[
                        (k, v)
                        for k, v in response.headers.multi_items()
                        if k.lower()
                        not in {"content-encoding", "content-length", "transfer-encoding"}
                    ],
                    content=b"".join(chunks),
                    request=httpx.Request(method, url),
                )
            if result.is_redirect and follow_redirects:
                if method != "GET":
                    raise ValueError(
                        "A mutating browser request cannot follow a redirect automatically"
                    )
                url = urljoin(url, result.headers["location"])
                continue
            return result
        raise ValueError("Too many redirects")
