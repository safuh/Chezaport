"""Run the idempotent canonical sports bootstrap.

Usage:
    uv run python -m chezaport.sports.seed
"""

import asyncio

from chezaport.core.config import get_settings
from chezaport.core.database import create_engine, create_session_factory, session_scope
from chezaport.sports.services.bootstrap import seed_default_sports


async def _seed() -> int:
    engine = create_engine(get_settings())
    try:
        session_factory = create_session_factory(engine)
        async with session_scope(session_factory) as session:
            return await seed_default_sports(session)
    finally:
        await engine.dispose()


def main() -> None:
    created = asyncio.run(_seed())
    print(f"Sports bootstrap complete; created {created} reference record(s).")


if __name__ == "__main__":
    main()
