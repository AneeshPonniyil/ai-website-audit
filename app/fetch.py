import asyncio
import ipaddress
import re
import socket
from urllib.parse import urljoin

import aiohttp
from aiohttp.abc import AbstractResolver
from yarl import URL

MAX_BYTES = 1_000_000
REDIRECTS = {301, 302, 303, 307, 308}


class FetchError(ValueError):
    pass


def public_ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return address.is_global and not address.is_multicast and not address.is_reserved


def validate_url(value):
    if len(value) > 2048 or re.search(r"[\x00-\x20\x7f\\]", value):
        raise FetchError("Enter a valid HTTP or HTTPS URL.")
    try:
        url = URL(value).with_fragment(None)
        host = url.raw_host or ""
        if (url.scheme not in {"http", "https"} or url.raw_user is not None
                or url.raw_password is not None or not url.is_default_port()
                or not re.fullmatch(r"[a-zA-Z0-9.-]+", host)):
            raise ValueError()
    except (ValueError, UnicodeError) as exc:
        raise FetchError("Use an HTTP or HTTPS URL on its default port without credentials.") from exc
    if re.fullmatch(r"[0-9.]+", host) and not public_ipv4(host):
        raise FetchError("Only public IPv4 websites are supported.")
    try:
        # inet_aton also recognizes abbreviated and legacy numeric IPv4 forms.
        socket.inet_aton(host)
    except OSError:
        if "." not in host.rstrip(".") or host.rstrip(".").lower().endswith(".localhost"):
            raise FetchError("Only public IPv4 websites are supported.")
    else:
        if not public_ipv4(host):
            raise FetchError("Only public IPv4 websites are supported.")
    return url


class PublicResolver(AbstractResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=socket.AF_INET, type=socket.SOCK_STREAM
        )
        if not addresses or any(not public_ipv4(item[4][0]) for item in addresses):
            raise FetchError("The website must resolve only to public IPv4 addresses.")
        return [
            {"hostname": host, "host": item[4][0], "port": port,
             "family": socket.AF_INET, "proto": socket.IPPROTO_TCP,
             "flags": socket.AI_NUMERICHOST}
            for item in addresses
        ]

    async def close(self):
        pass


async def fetch_page(value):
    """Fetch an HTML page. Returns (final_url, html, X-Robots-Tag header)."""
    result = await _fetch(value, max_bytes=MAX_BYTES, html_only=True)
    return result["url"], result["text"], result["robots_header"]


async def fetch_text(value):
    """Best-effort fetch of a small site file such as robots.txt.

    Returns (status, text, content_type); status is None when the file could not be retrieved.
    Uses the same public-address, redirect and size protections as fetch_page.
    """
    try:
        result = await _fetch(value, max_bytes=TEXT_MAX_BYTES, html_only=False)
    except FetchError:
        return None, "", ""
    return result["status"], result["text"], result["content_type"]


TEXT_MAX_BYTES = 500_000


async def _fetch(value, *, max_bytes, html_only):
    url = validate_url(value)
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), family=socket.AF_INET)
    try:
        async with asyncio.timeout(15), aiohttp.ClientSession(
            connector=connector, trust_env=False, cookie_jar=aiohttp.DummyCookieJar(),
            auto_decompress=False, headers={"Accept-Encoding": "identity",
                                            "User-Agent": "WebsiteAuditAssistant/1.0"}
        ) as client:
            for _ in range(5):
                async with client.get(url, allow_redirects=False) as response:
                    if response.status in REDIRECTS:
                        location = response.headers.get("Location")
                        if not location:
                            raise FetchError("The site returned a redirect without a destination.")
                        url = validate_url(urljoin(str(url), location))
                        continue
                    result = {"url": str(url), "status": response.status, "text": "",
                              "content_type": response.content_type,
                              "robots_header": response.headers.get("X-Robots-Tag", "")}
                    if response.status != 200:
                        if html_only:
                            raise FetchError(f"The site returned HTTP {response.status}.")
                        return result
                    if html_only and response.content_type not in {"text/html", "application/xhtml+xml"}:
                        raise FetchError("The URL must return an HTML page.")
                    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise FetchError("The site returned unsupported compressed content.")
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            if html_only:
                                raise FetchError("The HTML page exceeds the 1 MB limit.")
                            del body[max_bytes:]  # like crawlers, ignore content past the cap
                            break
                    try:
                        result["text"] = body.decode(response.charset or "utf-8", errors="replace")
                    except LookupError:
                        result["text"] = body.decode("utf-8", errors="replace")
                    return result
    except aiohttp.ClientConnectorCertificateError as exc:
        raise FetchError("Could not verify the website's TLS certificate.") from exc
    except (aiohttp.ClientError, OSError, TimeoutError) as exc:
        raise FetchError("Could not retrieve the public website within the fetch limits.") from exc
    raise FetchError("The site exceeded the redirect limit.")


