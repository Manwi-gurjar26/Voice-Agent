from __future__ import annotations

from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.db.session import get_db

PREFIX = settings.api_v1_prefix


async def test_liveness_does_not_touch_the_database(client):
    response = await client.get(f"{PREFIX}/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"


async def test_every_response_carries_a_request_id(client):
    response = await client.get(f"{PREFIX}/health")
    assert response.headers["X-Request-ID"]


async def test_client_supplied_request_id_is_echoed_back(client):
    response = await client.get(f"{PREFIX}/health", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers["X-Request-ID"] == "trace-abc-123"


async def test_malicious_request_id_is_sanitised(client):
    response = await client.get(
        f"{PREFIX}/health", headers={"X-Request-ID": "abc\ninjected level=CRITICAL"}
    )
    assert "\n" not in response.headers["X-Request-ID"]
    assert response.headers["X-Request-ID"] == "abcinjectedlevelCRITICAL"


async def test_security_headers_are_present(client):
    response = await client.get(f"{PREFIX}/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


async def test_readiness_reports_ok_when_database_answers(app, client):
    class _FakeSession:
        async def execute(self, _statement):
            return None

    async def _override():
        yield _FakeSession()

    app.dependency_overrides[get_db] = _override
    try:
        response = await client.get(f"{PREFIX}/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "up"}


async def test_readiness_reports_503_when_database_is_down(app, client):
    class _BrokenSession:
        async def execute(self, _statement):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    async def _override():
        yield _BrokenSession()

    app.dependency_overrides[get_db] = _override
    try:
        response = await client.get(f"{PREFIX}/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "down"}


async def test_unknown_route_returns_the_error_envelope(client):
    response = await client.get(f"{PREFIX}/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
