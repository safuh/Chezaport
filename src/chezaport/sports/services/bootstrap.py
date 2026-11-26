"""Idempotent bootstrap of canonical sports reference data."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chezaport.sports.domain.enums import SportCode
from chezaport.sports.models import Sport

_DEFAULT_SPORTS = ((SportCode.FOOTBALL.value, "Association football"),)


async def seed_default_sports(session: AsyncSession) -> int:
    """Insert missing built-in sports without overwriting existing records.

    The caller owns the session and transaction. The function flushes changes
    but never commits, making it safe to compose with other setup work.
    """
    created = 0
    for code, name in _DEFAULT_SPORTS:
        existing_id = await session.scalar(select(Sport.id).where(Sport.code == code))
        if existing_id is None:
            session.add(Sport(code=code, name=name, is_active=True))
            created += 1
    await session.flush()
    return created
