from __future__ import annotations

from starlette.requests import Request

from app.api.deps import client_ip
from app.core.config import settings


def _make_request(headers: dict[str, str], client_host: str | None = "203.0.113.5") -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (client_host, 12345) if client_host else None,
    }
    return Request(scope)


def test_ignores_x_forwarded_for_by_default(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    request = _make_request({"X-Forwarded-For": "198.51.100.9"})

    assert client_ip(request) == "203.0.113.5"


def test_trusts_x_forwarded_for_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = _make_request({"X-Forwarded-For": "198.51.100.9, 203.0.113.5"})

    assert client_ip(request) == "198.51.100.9"


def test_falls_back_to_socket_address_when_header_absent_even_if_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = _make_request({})

    assert client_ip(request) == "203.0.113.5"


def test_truncates_an_overlong_forwarded_value(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = _make_request({"X-Forwarded-For": "1" * 100})

    result = client_ip(request)
    assert result is not None
    assert len(result) == 45


def test_returns_none_when_no_client_and_not_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    request = _make_request({}, client_host=None)

    assert client_ip(request) is None
