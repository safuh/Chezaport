"""Manual, one-shot synchronization for configured football information feeds.

Usage:
    uv run python -m chezaport.sports.sync
    uv run python -m chezaport.sports.sync --competition PL --since 2026-08-01

The command performs read-only provider requests and idempotent local ingestion.
It does not expose provider credentials or add public sync endpoints.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chezaport.core.config import Settings, get_settings
from chezaport.core.database import create_engine, create_session_factory, session_scope
from chezaport.sports.domain.enums import CanonicalEntityType
from chezaport.sports.integrations.errors import ProviderConfigurationError
from chezaport.sports.integrations.factory import build_sports_provider_registry
from chezaport.sports.integrations.registry import SportsProviderRegistry
from chezaport.sports.models import Competition, ExternalIDMapping, Season
from chezaport.sports.services.bootstrap import seed_default_sports
from chezaport.sports.services.sync import SportsSyncReport, SportsSyncService

_PROVIDER = "football-data-org"


async def synchronize_competitions(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    registry: SportsProviderRegistry,
    competition_codes: Sequence[str],
    *,
    since: datetime | None = None,
) -> tuple[SportsSyncReport, ...]:
    """Synchronize configured competition catalogues, teams, and fixtures.

    All ingestion for this run is committed as one transaction. Any record-level
    ingestion failure aborts the run so partial reference data is not published.
    """
    if not settings.football_data_api_token:
        raise ProviderConfigurationError(
            "set FOOTBALL_DATA_API_TOKEN in the local environment before syncing"
        )
    configured_codes = {code.strip().upper() for code in settings.football_data_competition_codes}
    codes = tuple(dict.fromkeys(code.strip().upper() for code in competition_codes))
    if not codes or any(code not in configured_codes for code in codes):
        raise ProviderConfigurationError(
            "requested competition codes must be included in FOOTBALL_DATA_COMPETITION_CODES"
        )

    reports: list[SportsSyncReport] = []
    async with session_scope(session_factory) as session:
        await seed_default_sports(session)
        service = SportsSyncService(session, registry, audit_session_factory=session_factory)

        catalogue = await service.sync_competitions(_PROVIDER, "football")
        _require_success(catalogue)
        reports.append(catalogue)

        for code in codes:
            competition = await session.scalar(
                select(Competition).where(Competition.slug == code.lower())
            )
            if competition is None:
                raise RuntimeError(f"provider did not return configured competition {code}")
            competition_external_id = await _external_id(
                session,
                CanonicalEntityType.COMPETITION,
                competition.id,
            )

            seasons = await service.sync_seasons(code, competition_external_id)
            _require_success(seasons)
            reports.append(seasons)

            teams = await service.sync_teams(code, competition_external_id)
            _require_success(teams)
            reports.append(teams)

            season = await session.scalar(
                select(Season)
                .where(Season.competition_id == competition.id)
                .order_by(Season.is_current.desc(), Season.start_date.desc())
                .limit(1)
            )
            if season is None:
                raise RuntimeError(f"provider returned no seasons for competition {code}")
            season_external_id = await _external_id(
                session,
                CanonicalEntityType.SEASON,
                season.id,
            )

            fixtures = await service.sync_fixtures(
                code,
                competition_external_id,
                season_external_id,
                since=since,
            )
            _require_success(fixtures)
            reports.append(fixtures)
    return tuple(reports)


async def synchronize_fixtures(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    registry: SportsProviderRegistry,
    competition_codes: Sequence[str],
    *,
    since: datetime | None = None,
) -> tuple[SportsSyncReport, ...]:
    """Refresh only fixtures for already-imported competitions and seasons.

    This is the lightweight polling path used between full catalogue syncs.
    It makes one upstream request per configured competition and keeps team /
    season catalogues out of the frequent refresh cycle.
    """
    if not settings.football_data_api_token:
        raise ProviderConfigurationError(
            "set FOOTBALL_DATA_API_TOKEN before refreshing provider fixtures"
        )
    configured_codes = {code.strip().upper() for code in settings.football_data_competition_codes}
    codes = tuple(dict.fromkeys(code.strip().upper() for code in competition_codes))
    if not codes or any(code not in configured_codes for code in codes):
        raise ProviderConfigurationError(
            "requested competition codes must be included in FOOTBALL_DATA_COMPETITION_CODES"
        )

    refresh_from = since or datetime.combine(
        datetime.now(UTC).date() - timedelta(days=7), time.min, tzinfo=UTC
    )
    reports: list[SportsSyncReport] = []
    async with session_scope(session_factory) as session:
        service = SportsSyncService(session, registry, audit_session_factory=session_factory)
        for code in codes:
            competition = await session.scalar(
                select(Competition).where(Competition.slug == code.lower())
            )
            if competition is None:
                raise RuntimeError(
                    f"competition {code} has not been imported; run a full sync first"
                )
            competition_external_id = await _external_id(
                session, CanonicalEntityType.COMPETITION, competition.id
            )
            season = await session.scalar(
                select(Season)
                .where(Season.competition_id == competition.id)
                .order_by(Season.is_current.desc(), Season.start_date.desc())
                .limit(1)
            )
            if season is None:
                raise RuntimeError(
                    f"competition {code} has no imported season; run a full sync first"
                )
            season_external_id = await _external_id(session, CanonicalEntityType.SEASON, season.id)
            report = await service.sync_fixtures(
                code,
                competition_external_id,
                season_external_id,
                since=refresh_from,
            )
            _require_success(report)
            reports.append(report)
    return tuple(reports)


async def _external_id(
    session: AsyncSession,
    entity_type: CanonicalEntityType,
    entity_id: str,
) -> str:
    value = await session.scalar(
        select(ExternalIDMapping.external_id).where(
            ExternalIDMapping.provider == _PROVIDER,
            ExternalIDMapping.entity_type == entity_type.value,
            ExternalIDMapping.entity_id == entity_id,
        )
    )
    if value is None:
        raise RuntimeError(f"missing provider mapping for {entity_type.value} {entity_id}")
    return value


def _require_success(report: SportsSyncReport) -> None:
    if report.failed:
        failures = "; ".join(
            item.error or "unknown ingestion error" for item in report.ingestion.items if item.error
        )
        raise RuntimeError(
            f"{report.resource.value} ingestion had {report.failed} failure(s): {failures}"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronize configured football information.")
    parser.add_argument(
        "--competition",
        action="append",
        dest="competitions",
        help="Competition code to sync; repeat for multiple configured competitions.",
    )
    parser.add_argument(
        "--fixtures-only",
        action="store_true",
        help="Refresh fixtures only; requires a prior full catalogue sync.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Run one full sync, then continuously refresh fixtures.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=120,
        help="Fixture refresh interval in watch mode (minimum 60 seconds; default 120).",
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        help="Only request fixtures from this UTC date onward (YYYY-MM-DD).",
    )
    return parser.parse_args()


async def _run(
    settings: Settings,
    competitions: Sequence[str],
    since: date | None,
    *,
    fixtures_only: bool = False,
    watch: bool = False,
    interval_seconds: int = 120,
) -> None:
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        since_at = datetime.combine(since, time.min, tzinfo=UTC) if since else None
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            registry = build_sports_provider_registry(settings, client=client)

            async def emit(reports: Sequence[SportsSyncReport]) -> None:
                for report in reports:
                    print(
                        f"{report.resource.value}: fetched={report.records_fetched} "
                        f"created={report.created} updated={report.updated} "
                        f"unchanged={report.unchanged} failed={report.failed}",
                        flush=True,
                    )

            if watch:
                if interval_seconds < 60:
                    raise ValueError("--interval-seconds must be at least 60")
                print("Starting initial full catalogue sync…", flush=True)
                await emit(
                    await synchronize_competitions(
                        settings, session_factory, registry, competitions, since=since_at
                    )
                )
                print(
                    f"Fixture polling active every {interval_seconds}s; press Ctrl+C to stop.",
                    flush=True,
                )
                while True:
                    await asyncio.sleep(interval_seconds)
                    try:
                        reports = await synchronize_fixtures(
                            settings, session_factory, registry, competitions
                        )
                        await emit(reports)
                    except (
                        Exception
                    ) as exc:  # keep the long-running poller alive on transient errors
                        print(
                            "Fixture refresh failed "
                            f"({type(exc).__name__}); will retry next cycle.",
                            flush=True,
                        )
            elif fixtures_only:
                reports = await synchronize_fixtures(
                    settings, session_factory, registry, competitions, since=since_at
                )
                await emit(reports)
            else:
                reports = await synchronize_competitions(
                    settings, session_factory, registry, competitions, since=since_at
                )
                await emit(reports)
    finally:
        await engine.dispose()


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    competitions = args.competitions or settings.football_data_competition_codes
    if args.watch and args.fixtures_only:
        raise SystemExit(
            "--watch already performs an initial full sync; do not combine --fixtures-only"
        )
    asyncio.run(
        _run(
            settings,
            competitions,
            args.since,
            fixtures_only=args.fixtures_only,
            watch=args.watch,
            interval_seconds=args.interval_seconds,
        )
    )


if __name__ == "__main__":
    main()
