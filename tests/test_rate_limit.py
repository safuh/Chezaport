"""Public API rate-limit behavior."""

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from chezaport.app import create_app
from chezaport.core.config import Settings
from chezaport.core.database import Base


def test_public_api_and_match_reports_have_separate_rate_limits(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'rate-limit.db'}"

    async def prepare_database() -> None:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(prepare_database())
    app = create_app(
        Settings(
            database_url=database_url,
            public_api_rate_limit_per_minute=1,
            match_report_rate_limit_per_minute=1,
        )
    )

    with TestClient(app) as client:
        first_public = client.get("/api/v1/sports")
        second_public = client.get("/api/v1/sports")
        first_report = client.get("/api/v1/fixtures/missing/report")
        second_report = client.get("/api/v1/fixtures/missing/report")
        health = client.get("/api/health/ready")

    assert first_public.status_code == 200
    assert first_public.headers["X-RateLimit-Limit"] == "1"
    assert second_public.status_code == 429
    assert second_public.headers["Retry-After"].isdigit()
    assert second_public.headers["X-RateLimit-Remaining"] == "0"
    assert second_public.headers["X-Request-ID"]
    assert first_report.status_code == 404
    assert second_report.status_code == 429
    assert health.status_code == 200
