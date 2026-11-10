"""Application service for resolving provider IDs to canonical entities.

The caller owns the SQLAlchemy transaction. This service never commits or
creates sessions, which keeps ingestion jobs and API requests composable.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chezaport.sports.domain.enums import CanonicalEntityType
from chezaport.sports.integrations.errors import ExternalIDConflictError
from chezaport.sports.models import ExternalIDMapping


class ExternalIDResolver:
    """Resolve and register provider identifiers without vendor coupling."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(
        self,
        *,
        provider: str,
        entity_type: CanonicalEntityType,
        external_id: str,
    ) -> str | None:
        """Return the canonical entity ID, or None when no mapping exists."""
        mapping = await self._session.scalar(
            select(ExternalIDMapping).where(
                ExternalIDMapping.provider == provider,
                ExternalIDMapping.entity_type == entity_type.value,
                ExternalIDMapping.external_id == external_id,
            )
        )
        return mapping.entity_id if mapping is not None else None

    async def register(
        self,
        *,
        provider: str,
        entity_type: CanonicalEntityType,
        entity_id: str,
        external_id: str,
        source_url: str | None = None,
    ) -> ExternalIDMapping:
        """Create an idempotent mapping or refresh its last-seen metadata.

        Reassigning an external ID to another canonical entity, or assigning a
        second external ID from the same provider to one canonical entity, is
        rejected. The database unique constraints remain the final concurrency
        guard; callers should handle IntegrityError and retry the transaction
        after a concurrent registration race.
        """
        if not provider.strip() or not entity_id.strip() or not external_id.strip():
            raise ValueError("provider, entity_id, and external_id must not be blank")

        identity_filter = (
            ExternalIDMapping.provider == provider,
            ExternalIDMapping.entity_type == entity_type.value,
            ExternalIDMapping.external_id == external_id,
        )
        existing = await self._session.scalar(
            select(ExternalIDMapping).where(*identity_filter)
        )
        now = datetime.now(UTC)
        if existing is not None:
            if existing.entity_id != entity_id:
                raise ExternalIDConflictError(
                    f"{provider}:{entity_type.value}:{external_id} is already mapped "
                    f"to canonical entity {existing.entity_id}"
                )
            existing.last_seen_at = now
            if source_url is not None:
                existing.source_url = source_url
            return existing

        canonical_mapping = await self._session.scalar(
            select(ExternalIDMapping).where(
                ExternalIDMapping.provider == provider,
                ExternalIDMapping.entity_type == entity_type.value,
                ExternalIDMapping.entity_id == entity_id,
            )
        )
        if canonical_mapping is not None:
            raise ExternalIDConflictError(
                f"{provider}:{entity_type.value}:{entity_id} already has external ID "
                f"{canonical_mapping.external_id}"
            )

        mapping = ExternalIDMapping(
            provider=provider,
            entity_type=entity_type.value,
            entity_id=entity_id,
            external_id=external_id,
            source_url=source_url,
            last_seen_at=now,
        )
        self._session.add(mapping)
        await self._session.flush()
        return mapping
