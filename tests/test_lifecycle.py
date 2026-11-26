from fastapi.testclient import TestClient

from chezaport.app import create_app
from chezaport.core.config import Settings


def test_startup_initializes_database_resources() -> None:
    settings = Settings.for_profile("test")
    app = create_app(settings)

    with TestClient(app):
        assert app.state.startup_complete is True
        assert app.state.db_engine is not None
        assert app.state.db_session_factory is not None

    assert app.state.startup_complete is False


def test_liveness_does_not_require_database() -> None:
    settings = Settings.for_profile("test")
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_jwt_secret_composes_auth_and_database_backed_role_validators() -> None:
    settings = Settings.for_profile("test").model_copy(
        update={"jwt_secret_key": "a-high-entropy-test-secret-with-32-plus-chars"}
    )
    app = create_app(settings)

    with TestClient(app):
        assert callable(app.state.auth_application_factory)
        assert callable(app.state.sync_operator_token_validator)
        assert callable(app.state.admin_token_validator)
