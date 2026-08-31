from starlette.requests import Request

from scarletx.auth_routes import _client_address, _request_is_secure


def make_request(
    *,
    real_ip="203.0.113.42",
    forwarded_for="198.51.100.99, 203.0.113.42",
    forwarded_proto="https",
) -> Request:
    headers = [
        (b"x-real-ip", real_ip.encode()),
        (b"x-forwarded-for", forwarded_for.encode()),
        (b"x-forwarded-proto", forwarded_proto.encode()),
    ]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/auth/login",
            "raw_path": b"/api/auth/login",
            "query_string": b"",
            "headers": headers,
            "client": ("172.18.0.5", 43210),
            "server": ("scarletx-backend", 8000),
        }
    )


def test_forwarded_headers_are_ignored_without_explicit_proxy_trust(monkeypatch):
    monkeypatch.delenv("SCARLETX_TRUST_PROXY_HEADERS", raising=False)
    request = make_request()
    assert _client_address(request) == "172.18.0.5"
    assert _request_is_secure(request) is False


def test_nginx_real_ip_is_used_when_proxy_trust_is_enabled(monkeypatch):
    monkeypatch.setenv("SCARLETX_TRUST_PROXY_HEADERS", "1")
    request = make_request(real_ip="203.0.113.42", forwarded_for="1.2.3.4, 203.0.113.42")
    assert _client_address(request) == "203.0.113.42"
    assert _request_is_secure(request) is True


def test_proxy_trust_uses_only_https_forwarded_proto(monkeypatch):
    monkeypatch.setenv("SCARLETX_TRUST_PROXY_HEADERS", "true")
    request = make_request(forwarded_proto="http")
    assert _request_is_secure(request) is False
