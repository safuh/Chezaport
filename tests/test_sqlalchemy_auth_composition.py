from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from chezaport.auth import LoginRequest, RegistrationRequest, TokenError
from chezaport.auth.tokens import TokenService
from chezaport.core.database import Base, create_session_factory
from chezaport.identity import (
    RefreshToken,
    User,
    create_sqlalchemy_auth_application,
)


@pytest.mark.asyncio
async def test_sqlalchemy_auth_composition_persists_full_lifecycle() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = create_session_factory(engine)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            application = create_sqlalchemy_auth_application(
                session,
                secret_key="x" * 32,
                access_token_lifetime=timedelta(minutes=15),
                refresh_token_lifetime=timedelta(days=7),
            )

            registration = await application.register(
                RegistrationRequest(identifier="alice@example.com", password="correct horse")
            )
            await session.commit()

            login = await application.login(
                LoginRequest(identifier="alice@example.com", password="correct horse")
            )
            await session.commit()

            refreshed = await application.refresh(login.refresh_token)
            await session.commit()

            with pytest.raises(TokenError, match="Invalid refresh token"):
                await application.refresh(login.refresh_token)
            await session.rollback()

            assert refreshed.subject == registration.subject
            assert (
                TokenService("x" * 32).decode(refreshed.access_token, expected_type="access")["sub"]
                == registration.subject
            )
            assert (
                TokenService("x" * 32).decode(login.access_token, expected_type="access")["role"]
                == "viewer"
            )
            assert (
                TokenService("x" * 32).decode(refreshed.access_token, expected_type="access")[
                    "role"
                ]
                == "viewer"
            )
            assert refreshed.refresh_token != login.refresh_token

            assert await application.logout(refreshed.refresh_token)
            await session.commit()

            with pytest.raises(TokenError, match="Invalid refresh token"):
                await application.refresh(refreshed.refresh_token)
            await session.rollback()

            user = await session.get(User, registration.subject)
            assert user is not None
            assert user.identifier == "alice@example.com"
            assert user.role == "viewer"
            assert user.password_hash != "correct horse"

            refresh_rows = await session.execute(
                select(RefreshToken).order_by(RefreshToken.token_id)
            )
            assert len(refresh_rows.scalars().all()) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_operator_validator_checks_current_persisted_role() -> None:
    from chezaport.identity import create_sync_operator_token_validator

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = create_session_factory(engine)
    tokens = TokenService("y" * 32)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            user = User(
                identifier="operator@example.com",
                password_hash="not-a-real-login-hash",
                role="viewer",
            )
            session.add(user)
            await session.commit()
            validator = create_sync_operator_token_validator(session_factory, secret_key="y" * 32)
            access = tokens.create(
                user.id, timedelta(minutes=15), token_type="access", claims={"role": "admin"}
            )
            assert await validator(access) is False
            user.role = "operator"
            await session.commit()
            assert await validator(access) is True
            user.role = "viewer"
            await session.commit()
            assert await validator(access) is False
            assert await validator("not-a-jwt") is False
            refresh = tokens.create(user.id, timedelta(minutes=15), token_type="refresh")
            assert await validator(refresh) is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_role_management_is_explicit_and_validated() -> None:
    from chezaport.identity import set_user_role

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = create_session_factory(engine)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            user = User(
                identifier="role-target@example.com",
                password_hash="not-a-real-login-hash",
            )
            session.add(user)
            await session.commit()
            assert await set_user_role(session, user.identifier, "operator") is True
            await session.commit()
            assert user.role == "operator"
            assert await set_user_role(session, "missing@example.com", "admin") is False
            with pytest.raises(ValueError, match="role must be"):
                await set_user_role(session, user.identifier, "superuser")
    finally:
        await engine.dispose()
