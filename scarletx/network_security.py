from __future__ import annotations

import ipaddress
import socket
from urllib.parse import SplitResult, urlsplit


def _is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_global


def validate_public_https_url(url: str) -> SplitResult:
    """Validate a remote-art URL before the backend connects to it.

    Metadata-provided artwork is untrusted network input. ScarletX only allows
    HTTPS targets that resolve exclusively to globally routable addresses.
    """
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise ValueError("remote artwork must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("remote artwork URLs cannot contain credentials")

    host = parsed.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise ValueError("remote artwork target is not publicly routable")
        return parsed

    try:
        rows = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("remote artwork hostname could not be resolved") from exc
    addresses = {row[4][0] for row in rows if row and len(row) > 4 and row[4]}
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise ValueError("remote artwork hostname resolves to a non-public address")
    return parsed
