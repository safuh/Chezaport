"""Database-backed authorization for operational sports endpoints."""

from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chezaport.auth.tokens import TokenError, TokenService

from .models import User


def create_sync_operator_token_validator(
    session_factory: async_sessionmaker[AsyncSession], *, secret_key: str
) -> Callable[[str], Awaitable[bool]]:
    """Build a fail-closed validator that checks JWT and the user's current DB role.

    Roles are least-privilege: viewer cannot operate sync; operator and admin can.
    Database lookup means demotion/revocation takes effect without waiting for JWT expiry.
    """
    tokens = TokenService(secret_key)

    async def validate(token: str) -> bool:
        try:
            payload = tokens.decode(token, expected_type="access")
        except TokenError:
            return False
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            return False
        async with session_factory() as session:
            role = await session.scalar(select(User.role).where(User.id == subject))
        return role in {"operator", "admin"}

    return validate
