"""Canonical persistence for provider-backed fixture reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from chezaport.sports.integrations.schemas import ProviderMatchDetails
from chezaport.sports.models import FixtureMatchEvent, FixturePlayerParticipation
from chezaport.sports.services.match_events import normalize_match_events


def _participation_rows(report: ProviderMatchDetails) -> list[dict[str, Any]]:
    """Build one participation record per identifiable player and fixture."""
    players: dict[tuple[str, str], dict[str, Any]] = {}

    def add_person(
        team_id: str | None,
        person: Any,
        *,
        starter: bool = False,
        bench: bool = False,
    ) -> None:
        external_id = person.external_id
        if not external_id:
            return
        key = (team_id or "", external_id)
        row = players.setdefault(
            key,
            {
                "team_external_id": team_id,
                "player_external_id": external_id,
                "player_name": person.name,
                "is_starter": False,
                "is_bench": False,
                "appeared": False,
                "position": person.position,
                "shirt_number": person.shirt_number,
            },
        )
        row["is_starter"] = row["is_starter"] or starter
        row["is_bench"] = row["is_bench"] or bench
        if starter:
            row["appeared"] = True

    for side in (report.home_team, report.away_team):
        for person in side.lineup:
            add_person(side.external_id, person, starter=True)
        for person in side.bench:
            add_person(side.external_id, person, bench=True)

    def participation_key(team_id: str | None, external_id: str) -> tuple[str, str]:
        if team_id:
            return (team_id, external_id)
        existing = [key for key in players if key[1] == external_id]
        return existing[0] if len(existing) == 1 else ("", external_id)

    for event in report.substitutions:
        team_id = event.team_external_id
        if event.player_in_external_id:
            key = participation_key(team_id, event.player_in_external_id)
            row = players.setdefault(
                key,
                {
                    "team_external_id": team_id,
                    "player_external_id": event.player_in_external_id,
                    "player_name": event.player_in_name,
                    "is_starter": False,
                    "is_bench": False,
                    "appeared": False,
                    "position": None,
                    "shirt_number": None,
                },
            )
            row["appeared"] = True
        if event.player_out_external_id:
            key = participation_key(team_id, event.player_out_external_id)
            row = players.setdefault(
                key,
                {
                    "team_external_id": event.team_external_id,
                    "player_external_id": event.player_out_external_id,
                    "player_name": event.player_out_name,
                    "is_starter": False,
                    "is_bench": False,
                    "appeared": False,
                    "position": None,
                    "shirt_number": None,
                },
            )
            row["appeared"] = True

    return list(players.values())


def _event_player_ids(event_type: str, payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    if event_type == "goal":
        return payload.get("scorer_external_id"), payload.get("assist_external_id")
    if event_type == "booking":
        return payload.get("player_external_id"), None
    return payload.get("player_in_external_id"), payload.get("player_out_external_id")


async def replace_canonical_fixture_report(
    session: AsyncSession,
    *,
    provider: str,
    fixture_id: str,
    report: ProviderMatchDetails,
) -> tuple[int, int]:
    """Atomically replace a provider/fixture event and participation snapshot.

    A complete refreshed report replaces the previous canonical rows. Repeated
    imports therefore remain idempotent, while corrected provider data removes
    stale events and squad records. The caller owns the surrounding transaction.
    """
    payload = report.model_dump(mode="json")
    normalized = normalize_match_events(payload, provider=provider, fixture_id=fixture_id)

    await session.execute(
        delete(FixtureMatchEvent).where(
            FixtureMatchEvent.provider == provider,
            FixtureMatchEvent.fixture_id == fixture_id,
        )
    )
    await session.execute(
        delete(FixturePlayerParticipation).where(
            FixturePlayerParticipation.provider == provider,
            FixturePlayerParticipation.fixture_id == fixture_id,
        )
    )

    event_rows: list[FixtureMatchEvent] = []
    for item in normalized:
        primary, secondary = _event_player_ids(item["event_type"], item["payload"])
        event_rows.append(
            FixtureMatchEvent(
                provider=provider,
                fixture_id=fixture_id,
                event_type=item["event_type"],
                source_key=item["source_key"],
                minute=item["minute"],
                player_external_id=primary,
                secondary_player_external_id=secondary,
                payload=item["payload"],
            )
        )
    participation = [
        FixturePlayerParticipation(
            provider=provider,
            fixture_id=fixture_id,
            **row,
        )
        for row in _participation_rows(report)
    ]
    session.add_all([*event_rows, *participation])
    await session.flush()
    return len(event_rows), len(participation)
