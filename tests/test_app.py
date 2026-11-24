from fastapi.testclient import TestClient

from chezaport.app import create_app
from chezaport.core.config import Settings


def make_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        cors_origins=["https://example.com"],
    )


def test_health_endpoint() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_request_id_is_generated_and_returned() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_valid_request_id_is_propagated() -> None:
    request_id = "2f3b5b74-6a89-4e8e-a1b0-8e4ef1c4f9b1"
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/health", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id


def test_invalid_request_id_is_replaced() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/health", headers={"X-Request-ID": "not-a-uuid"})

    assert response.headers["X-Request-ID"] != "not-a-uuid"


def test_not_found_uses_error_envelope() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_cors_policy_is_explicit() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.options(
            "/api/health",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://example.com"


def test_versioned_api_discovery_endpoint() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/v1/")

    assert response.status_code == 200
    assert response.json() == {"name": "Chezaport API", "version": "v1"}


def test_admin_api_fails_closed_when_authorization_is_not_configured() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/v1/admin/users")

    assert response.status_code == 503


def test_admin_api_requires_bearer_access_token() -> None:
    async def allow_admin(_: str) -> bool:
        return True

    with TestClient(create_app(make_settings(), admin_token_validator=allow_admin)) as client:
        response = client.get("/api/v1/admin/users")

    assert response.status_code == 401


def test_admin_api_rejects_non_admin_token() -> None:
    async def deny_admin(_: str) -> bool:
        return False

    with TestClient(create_app(make_settings(), admin_token_validator=deny_admin)) as client:
        response = client.get(
            "/api/v1/admin/users", headers={"Authorization": "Bearer viewer-token"}
        )

    assert response.status_code == 403
