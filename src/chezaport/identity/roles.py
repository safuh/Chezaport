"""Privileged identity-role administration primitives."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User

VALID_ROLES = frozenset({"viewer", "operator", "admin"})


async def set_user_role(session: AsyncSession, identifier: str, role: str) -> bool:
    """Set a user's role; caller must be a trusted administrative process.

    This deliberately is not exposed as public self-service registration input.
    """
    if role not in VALID_ROLES:
        raise ValueError("role must be viewer, operator, or admin")
    user = await session.scalar(select(User).where(User.identifier == identifier))
    if user is None:
        return False
    user.role = role
    await session.flush()
    return True
