"""Explicit shell-only user role administration command."""

import argparse
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chezaport.core.config import get_settings

from .roles import VALID_ROLES, set_user_role


async def _run(identifier: str, role: str) -> int:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            changed = await set_user_role(session, identifier, role)
            if not changed:
                await session.rollback()
                print("No user found for that identifier.")
                return 1
            await session.commit()
            print(f"Updated role for {identifier} to {role}.")
            return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set a Chezaport user role from a trusted server shell."
    )
    parser.add_argument("--identifier", required=True)
    parser.add_argument("--role", required=True, choices=sorted(VALID_ROLES))
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.identifier, args.role)))


if __name__ == "__main__":
    main()
