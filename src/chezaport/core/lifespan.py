"""Application lifespan and resource lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from chezaport.identity.authorization import (
    create_admin_token_validator,
    create_sync_operator_token_validator,
)

from .config import Settings
from .database import create_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create shared infrastructure at startup and dispose it at shutdown."""
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory
    if settings.jwt_secret_key is not None:
        if app.state.sync_operator_token_validator is None:
            app.state.sync_operator_token_validator = create_sync_operator_token_validator(
                session_factory, secret_key=settings.jwt_secret_key
            )
        if app.state.admin_token_validator is None:
            app.state.admin_token_validator = create_admin_token_validator(
                session_factory, secret_key=settings.jwt_secret_key
            )
    app.state.startup_complete = False

    try:
        if settings.environment.value != "test":
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        app.state.startup_complete = True
        yield
    finally:
        app.state.startup_complete = False
        await engine.dispose()
