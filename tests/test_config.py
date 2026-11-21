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
