"""Refuse private/local/metadata URLs before any outbound fetch.

Used by article and X scrapers so `forge add` cannot be pointed at
loopback, RFC1918, link-local, or cloud metadata endpoints (SSRF).
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

# Hostnames that always mean "this machine" or cloud metadata.
_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
}

# Literal IPv4/IPv6 forms that should never be fetched.
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_IPV4_DOTTED = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


class UnsafeURLError(ValueError):
    """Raised when a URL targets a private, local, or metadata address."""


def _host_is_blocked_ip(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in network for network in _BLOCKED_NETWORKS)


def _normalize_host(host: str) -> str:
    host = (host or "").strip().lower().rstrip(".")
    # URLs may include [ipv6] brackets.
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    # Strip zone id (fe80::1%eth0).
    if "%" in host:
        host = host.split("%", 1)[0]
    return host


def is_safe_fetch_url(url: str) -> bool:
    """Return True when the URL is http(s) to a non-private host."""
    try:
        assert_safe_fetch_url(url)
        return True
    except UnsafeURLError:
        return False


def assert_safe_fetch_url(url: str) -> str:
    """Validate *url* for outbound scraping. Returns the stripped URL or raises."""
    raw = (url or "").strip()
    if not raw:
        raise UnsafeURLError("URL is empty")

    parts = urlsplit(raw)
    scheme = (parts.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise UnsafeURLError(f"Only http/https URLs are allowed (got {scheme or 'none'})")

    host = _normalize_host(parts.hostname or "")
    if not host:
        raise UnsafeURLError("URL has no hostname")

    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise UnsafeURLError(f"Refusing local/metadata host: {host}")

    # Block decimal/octal-ish dotted quads and bare IPs in private ranges.
    if _host_is_blocked_ip(host):
        raise UnsafeURLError(f"Refusing private/link-local IP: {host}")

    # Also catch 127.1 style shorthand that ip_address may accept after normalize.
    if _IPV4_DOTTED.match(host) and _host_is_blocked_ip(host):
        raise UnsafeURLError(f"Refusing private/link-local IP: {host}")

    return raw
