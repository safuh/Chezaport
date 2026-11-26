"""Environment profile validation tests."""

import pytest
from pydantic import ValidationError

from chezaport.core.config import Environment, Settings


def test_staging_requires_postgresql() -> None:
    with pytest.raises(ValidationError, match="staging requires a PostgreSQL"):
        Settings(
            environment=Environment.STAGING,
            debug=False,
            database_url="sqlite+aiosqlite:///:memory:",
        )


def test_staging_enforces_production_like_defaults() -> None:
    settings = Settings(
        environment=Environment.STAGING,
        debug=False,
        database_url="postgresql+asyncpg://user:secret@localhost:5432/staging",
    )

    assert settings.debug is False
    assert settings.log_json is True


def test_staging_profile_factory_uses_postgresql() -> None:
    settings = Settings.for_profile(Environment.STAGING)

    assert settings.environment is Environment.STAGING
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.log_json is True


def test_jwt_secret_must_meet_minimum_length() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(jwt_secret_key="too-short")


def test_auth_token_lifetimes_are_bounded() -> None:
    settings = Settings(access_token_minutes=30, refresh_token_days=14)
    assert settings.access_token_minutes == 30
    assert settings.refresh_token_days == 14


def test_managed_postgresql_urls_are_normalized_for_asyncpg() -> None:
    settings = Settings(
        environment=Environment.PRODUCTION,
        debug=False,
        database_url="postgresql://user:secret@db.example.com:5432/chezaport",
    )

    assert settings.database_url == (
        "postgresql+asyncpg://user:secret@db.example.com:5432/chezaport"
    )


def test_legacy_postgres_scheme_is_normalized_for_asyncpg() -> None:
    settings = Settings(database_url="postgres://user:secret@localhost:5432/chezaport")

    assert settings.database_url.startswith("postgresql+asyncpg://")
