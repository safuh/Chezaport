"""Tests for provider-to-canonical ID resolution."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chezaport.core.database import Base
from chezaport.sports.domain.enums import CanonicalEntityType
from chezaport.sports.integrations.errors import ExternalIDConflictError
from chezaport.sports.models import ExternalIDMapping  # noqa: F401
from chezaport.sports.services.external_ids import ExternalIDResolver


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_register_and_resolve_external_id(session_factory) -> None:
    async with session_factory() as session:
        resolver = ExternalIDResolver(session)
        mapping = await resolver.register(
            provider="sample",
            entity_type=CanonicalEntityType.TEAM,
            entity_id="canonical-team-1",
            external_id="provider-team-9",
        )
        assert mapping.id
        assert await resolver.resolve(
            provider="sample",
            entity_type=CanonicalEntityType.TEAM,
            external_id="provider-team-9",
        ) == "canonical-team-1"
        await session.rollback()


async def test_register_is_idempotent_for_same_mapping(session_factory) -> None:
    async with session_factory() as session:
        resolver = ExternalIDResolver(session)
        first = await resolver.register(
            provider="sample", entity_type=CanonicalEntityType.TEAM,
            entity_id="team-1", external_id="remote-1",
        )
        second = await resolver.register(
            provider="sample", entity_type=CanonicalEntityType.TEAM,
            entity_id="team-1", external_id="remote-1", source_url="https://example.test/team/1",
        )
        assert first.id == second.id
        assert second.source_url == "https://example.test/team/1"
        await session.rollback()


async def test_register_rejects_external_id_reassignment(session_factory) -> None:
    async with session_factory() as session:
        resolver = ExternalIDResolver(session)
        await resolver.register(
            provider="sample", entity_type=CanonicalEntityType.TEAM,
            entity_id="team-1", external_id="remote-1",
        )
        with pytest.raises(ExternalIDConflictError):
            await resolver.register(
                provider="sample", entity_type=CanonicalEntityType.TEAM,
                entity_id="team-2", external_id="remote-1",
            )
        await session.rollback()


async def test_register_rejects_second_external_id_for_entity(session_factory) -> None:
    async with session_factory() as session:
        resolver = ExternalIDResolver(session)
        await resolver.register(
            provider="sample", entity_type=CanonicalEntityType.TEAM,
            entity_id="team-1", external_id="remote-1",
        )
        with pytest.raises(ExternalIDConflictError):
            await resolver.register(
                provider="sample", entity_type=CanonicalEntityType.TEAM,
                entity_id="team-1", external_id="remote-2",
            )
        await session.rollback()
