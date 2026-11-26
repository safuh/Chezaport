"""Application factory and composition root."""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ExceptionHandler

from .api.router import api_router
from .auth.application import AuthenticationApplication
from .core.config import Settings, get_settings
from .core.errors import (
    BackboneError,
    backbone_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from .core.lifespan import lifespan
from .core.logging import configure_logging
from .core.middleware import RateLimitMiddleware, RequestContextMiddleware
from .identity.composition import create_sqlalchemy_auth_application
from .web.routes import router as web_router

AuthApplicationFactory = Callable[[AsyncSession], AuthenticationApplication]


def create_app(
    settings: Settings | None = None,
    auth_application_factory: AuthApplicationFactory | None = None,
    sync_operator_token_validator: Callable[[str], Awaitable[bool]] | None = None,
    admin_token_validator: Callable[[str], Awaitable[bool]] | None = None,
) -> FastAPI:
    """Create a configured FastAPI application with optional auth composition.

    Authentication dependencies are supplied by the consuming application so
    secrets, token lifetimes, and persistence remain explicit composition concerns.
    """
    resolved = settings or get_settings()
    configure_logging(resolved)

    app = FastAPI(
        title=resolved.app_name,
        version=resolved.app_version,
        debug=resolved.debug,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    if auth_application_factory is None and resolved.jwt_secret_key is not None:
        secret_key = resolved.jwt_secret_key
        app.state.auth_application_factory = lambda session: create_sqlalchemy_auth_application(
            session,
            secret_key=secret_key,
            access_token_lifetime=timedelta(minutes=resolved.access_token_minutes),
            refresh_token_lifetime=timedelta(days=resolved.refresh_token_days),
        )
    else:
        app.state.auth_application_factory = auth_application_factory
    app.state.sync_operator_token_validator = sync_operator_token_validator
    app.state.admin_token_validator = admin_token_validator

    app.add_middleware(
        RateLimitMiddleware,
        public_requests_per_minute=resolved.public_api_rate_limit_per_minute,
        match_report_requests_per_minute=resolved.match_report_rate_limit_per_minute,
    )
    app.add_middleware(RequestContextMiddleware)
    if resolved.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.cors_origins,
            allow_credentials=resolved.cors_allow_credentials,
            allow_methods=resolved.cors_allow_methods,
            allow_headers=resolved.cors_allow_headers,
        )

    app.add_exception_handler(
        BackboneError,
        cast(ExceptionHandler, backbone_error_handler),
    )
    app.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, validation_error_handler),
    )
    app.add_exception_handler(
        StarletteHTTPException,
        cast(ExceptionHandler, http_error_handler),
    )
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(api_router, prefix=resolved.api_prefix)
    app.include_router(web_router)
    return app
