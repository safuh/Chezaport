from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from chezaport.app import create_app
from chezaport.core.config import Environment, Settings
from chezaport.core.database import Base
from chezaport.identity import create_sqlalchemy_auth_application


@pytest.mark.asyncio
async def test_auth_http_uses_sqlalchemy_composition(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}"
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()

    settings = Settings(
        environment=Environment.TEST,
        database_url=database_url,
    )

    def application_factory(session):
        return create_sqlalchemy_auth_application(
            session,
            secret_key="x" * 32,
            access_token_lifetime=timedelta(minutes=15),
            refresh_token_lifetime=timedelta(days=7),
        )

    with TestClient(create_app(settings, application_factory)) as client:
        registered = client.post(
            "/api/auth/register",
            json={"identifier": "alice@example.com", "password": "correct horse"},
        )
        assert registered.status_code == 201

        logged_in = client.post(
            "/api/auth/login",
            json={"identifier": "alice@example.com", "password": "correct horse"},
        )
        assert logged_in.status_code == 200
        tokens = logged_in.json()

        refreshed = client.post(
            "/api/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert refreshed.status_code == 200

        replay = client.post(
            "/api/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert replay.status_code == 401

        logged_out = client.post(
            "/api/auth/logout",
            json={"refresh_token": refreshed.json()["refresh_token"]},
        )
        assert logged_out.status_code == 204

        revoked = client.post(
            "/api/auth/refresh",
            json={"refresh_token": refreshed.json()["refresh_token"]},
        )
        assert revoked.status_code == 401


def test_environment_secret_composes_auth_and_live_role_authorization(tmp_path: Path) -> None:
    import sqlite3

    database_path = tmp_path / "auto-auth.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    engine = create_async_engine(database_url)

    import asyncio

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(prepare())
    settings = Settings(
        environment=Environment.TEST,
        database_url=database_url,
        jwt_secret_key="a-high-entropy-test-secret-with-more-than-32-characters",
    )

    with TestClient(create_app(settings)) as client:
        registered = client.post(
            "/api/auth/register",
            json={"identifier": "operator@example.test", "password": "correct horse"},
        )
        assert registered.status_code == 201
        logged_in = client.post(
            "/api/auth/login",
            json={"identifier": "operator@example.test", "password": "correct horse"},
        )
        assert logged_in.status_code == 200
        access_token = logged_in.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        viewer_denied = client.get("/api/v1/admin/users", headers=headers)
        assert viewer_denied.status_code == 403

        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "UPDATE users SET role = 'admin' WHERE identifier = ?",
                ("operator@example.test",),
            )
            connection.commit()

        # The same unexpired viewer-issued access token now follows the persisted role.
        admin_allowed = client.get("/api/v1/admin/users", headers=headers)
        operator_allowed = client.get("/api/v1/ops/sync-runs", headers=headers)
        assert admin_allowed.status_code == 200
        assert admin_allowed.json()["total"] == 1
        assert operator_allowed.status_code == 200
