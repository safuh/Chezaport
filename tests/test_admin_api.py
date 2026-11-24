"""Database-backed contract tests for administrator user management."""

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from chezaport.app import create_app
from chezaport.auth.tokens import TokenService
from chezaport.core.config import Settings
from chezaport.identity import User
from chezaport.identity.authorization import create_admin_token_validator


@pytest.mark.asyncio
async def test_admin_user_listing_role_changes_and_last_admin_protection() -> None:
    secret = "test-only-secret-key-with-at-least-32-characters"
    app = create_app(
        Settings.for_profile("test"),
        admin_token_validator=None,
    )

    async with app.router.lifespan_context(app):
        async with app.state.db_engine.begin() as connection:
            await connection.run_sync(User.metadata.create_all)
        factory = app.state.db_session_factory
        async with factory() as session:
            admin = User(
                identifier="admin@example.test", password_hash="not-a-real-hash", role="admin"
            )
            viewer = User(identifier="viewer@example.test", password_hash="not-a-real-hash")
            second_admin = User(
                identifier="second-admin@example.test",
                password_hash="not-a-real-hash",
                role="admin",
            )
            session.add_all([admin, viewer, second_admin])
            await session.commit()
            await session.refresh(admin)
            await session.refresh(viewer)
            await session.refresh(second_admin)

        app.state.admin_token_validator = create_admin_token_validator(factory, secret_key=secret)
        tokens = TokenService(secret)
        admin_token = tokens.create(admin.id, timedelta(minutes=5))
        viewer_token = tokens.create(viewer.id, timedelta(minutes=5))
        second_admin_token = tokens.create(second_admin.id, timedelta(minutes=5))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {admin_token}"}
            listing = await client.get("/api/v1/admin/users", headers=headers)
            assert listing.status_code == 200
            payload = listing.json()
            assert payload["total"] == 3
            assert {item["identifier"] for item in payload["items"]} == {
                "admin@example.test",
                "second-admin@example.test",
                "viewer@example.test",
            }
            assert all("password_hash" not in item for item in payload["items"])

            denied = await client.get(
                "/api/v1/admin/users",
                headers={"Authorization": f"Bearer {viewer_token}"},
            )
            assert denied.status_code == 403

            promoted = await client.patch(
                f"/api/v1/admin/users/{viewer.id}/role",
                json={"role": "operator"},
                headers=headers,
            )
            assert promoted.status_code == 200
            assert promoted.json()["role"] == "operator"

            demoted_admin = await client.patch(
                f"/api/v1/admin/users/{admin.id}/role",
                json={"role": "viewer"},
                headers={"Authorization": f"Bearer {second_admin_token}"},
            )
            assert demoted_admin.status_code == 200
            assert demoted_admin.json()["role"] == "viewer"

            stale_admin_token = await client.get("/api/v1/admin/users", headers=headers)
            assert stale_admin_token.status_code == 403

            demoted_last_admin = await client.patch(
                f"/api/v1/admin/users/{second_admin.id}/role",
                json={"role": "viewer"},
                headers={"Authorization": f"Bearer {second_admin_token}"},
            )
            assert demoted_last_admin.status_code == 409

            invalid_role = await client.patch(
                f"/api/v1/admin/users/{viewer.id}/role",
                json={"role": "superuser"},
                headers={"Authorization": f"Bearer {second_admin_token}"},
            )
            assert invalid_role.status_code == 422

        async with factory() as session:
            persisted_admin = await session.scalar(select(User).where(User.id == admin.id))
            assert persisted_admin is not None
            assert persisted_admin.role == "viewer"
    await app.state.db_engine.dispose()
