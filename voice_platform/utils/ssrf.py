"""SSRF protection — validate URLs before making outbound requests.

Consolidated from three duplicate implementations:
  - actions/action_executor.py
  - integrations/webhook_client.py
  - integrations/mcp_client.py

Public API:
    validate_url(url: str) -> bool   — True if URL is safe to contact
    is_safe_url(url: str) -> bool    — alias for backward compat
"""

import ipaddress
import re
from urllib.parse import urlparse

_BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "169.254.169.254",           # AWS/GCP instance metadata
    "metadata.google.internal",  # GCP metadata
    "metadata.google.internal.", # GCP metadata with trailing dot
    "instance-data",             # AWS EC2 instance metadata
    "metadata",                  # Generic metadata hostname
}

_BLOCKED_PATTERNS = [
    re.compile(r"^127\.\d+\.\d+\.\d+$"),               # 127.0.0.0/8 loopback
    re.compile(r"^10\.\d+\.\d+\.\d+$"),                # 10.0.0.0/8 private
    re.compile(r"^172\.(1[6-9]|2[0-9]|3[01])\.\d+\.\d+$"),  # 172.16-31.x.x
    re.compile(r"^192\.168\.\d+\.\d+$"),               # 192.168.x.x private
    re.compile(r"^169\.254\.\d+\.\d+$"),               # Link-local
    re.compile(r"^0\.\d+\.\d+\.\d+$"),                 # 0.0.0.0/8
    re.compile(r"^fc00:"),                             # IPv6 unique local
    re.compile(r"^fe80:"),                             # IPv6 link-local
    re.compile(r"^::1$"),                              # IPv6 loopback
]


def validate_url(url: str) -> bool:
    """Return True if the URL is safe to contact (not an internal address).

    Checks:
    - Valid http/https scheme
    - Not a blocked hostname (localhost, metadata endpoints, etc.)
    - Not a private/loopback/link-local/reserved IP literal
    - Not in private CIDR ranges (10.x, 172.16-31.x, 192.168.x, 169.254.x, 0.x)
    """
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            return False
        if parsed.scheme not in ("http", "https"):
            return False
        if host in _BLOCKED_HOSTS:
            return False
        if "localhost" in host:
            return False
        for pattern in _BLOCKED_PATTERNS:
            if pattern.match(host):
                return False
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return False
        except ValueError:
            pass
        if host in ("", "[::1]"):
            return False
        return True
    except Exception:
        return False


is_safe_url = validate_url
