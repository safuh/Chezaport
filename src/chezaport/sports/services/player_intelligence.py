"""Historical player career and team-contribution aggregation.

All statistics are derived from canonical provider identities, fixture
participations, and normalized match events. Team attribution is never inferred
from a player's current squad alone.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from chezaport.sports.models import (
    Competition,
    ExternalIDMapping,
    Fixture,
    FixtureMatchEvent,
    FixturePlayerParticipation,
    Player,
    Season,
    Team,
    TeamMembership,
)

DEFAULT_PROVIDER = "football-data-org"


@dataclass
class _Stats:
    appearance_fixtures: set[str] = field(default_factory=set)
    start_fixtures: set[str] = field(default_factory=set)
    goals: int = 0
    assists: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    substitutions_in: int = 0
    substitutions_out: int = 0

    def add_participation(self, row: FixturePlayerParticipation) -> None:
        if row.appeared:
            self.appearance_fixtures.add(row.fixture_id)
        if row.is_starter:
            self.start_fixtures.add(row.fixture_id)

    def add_event(self, event: FixtureMatchEvent, fixture_id: str, player_external_id: str) -> None:
        payload = event.payload
        if event.event_type == "goal":
            if event.player_external_id == player_external_id:
                self.goals += 1
                self.appearance_fixtures.add(fixture_id)
            if event.secondary_player_external_id == player_external_id:
                self.assists += 1
                self.appearance_fixtures.add(fixture_id)
        elif event.event_type == "booking" and event.player_external_id == player_external_id:
            card = str(payload.get("card", "")).lower()
            self.yellow_cards += int("yellow" in card)
            self.red_cards += int("red" in card)
            self.appearance_fixtures.add(fixture_id)
        elif event.event_type == "substitution":
            if event.player_external_id == player_external_id:
                self.substitutions_in += 1
            if event.secondary_player_external_id == player_external_id:
                self.substitutions_out += 1

    def as_dict(self) -> dict[str, int]:
        return {
            "appearances": len(self.appearance_fixtures),
            "starts": len(self.start_fixtures),
            "goals": self.goals,
            "assists": self.assists,
            "yellow_cards": self.yellow_cards,
            "red_cards": self.red_cards,
            "substitutions_in": self.substitutions_in,
            "substitutions_out": self.substitutions_out,
        }


def _active_membership(periods: list[TeamMembership], on_date: date) -> bool:
    return any(
        (period.joined_on is None or period.joined_on <= on_date)
        and (period.left_on is None or period.left_on >= on_date)
        for period in periods
    )


def _infer_membership_team(
    fixture: Fixture,
    on_date: date,
    memberships_by_team: dict[str, list[TeamMembership]],
) -> str | None:
    candidates = [
        team_id
        for team_id in (fixture.home_team_id, fixture.away_team_id)
        if team_id in memberships_by_team
        and _active_membership(memberships_by_team[team_id], on_date)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _new_stats(mapping: dict[Any, _Stats], key: Any) -> _Stats:
    if key not in mapping:
        mapping[key] = _Stats()
    return mapping[key]


def _membership_read(row: TeamMembership) -> dict[str, Any]:
    return {
        "membership_id": row.id,
        "team_id": row.team_id,
        "team_name": "",
        "joined_on": row.joined_on,
        "left_on": row.left_on,
        "shirt_number": row.shirt_number,
    }


async def build_player_career(
    session: AsyncSession,
    *,
    player_id: str,
    provider: str = DEFAULT_PROVIDER,
) -> dict[str, Any]:
    """Aggregate one player's historical statistics by registered club."""
    memberships = list(
        (
            await session.scalars(
                select(TeamMembership)
                .where(TeamMembership.player_id == player_id)
                .order_by(TeamMembership.joined_on.asc().nullsfirst(), TeamMembership.id.asc())
            )
        ).all()
    )
    memberships_by_team: dict[str, list[TeamMembership]] = defaultdict(list)
    for membership in memberships:
        memberships_by_team[membership.team_id].append(membership)

    identity = await session.scalar(
        select(ExternalIDMapping).where(
            ExternalIDMapping.provider == provider,
            ExternalIDMapping.entity_type == "player",
            ExternalIDMapping.entity_id == player_id,
        )
    )

    team_stats: dict[str, _Stats] = {}
    competition_stats: dict[tuple[str, str, str], _Stats] = {}
    competition_names: dict[tuple[str, str, str], tuple[str, str]] = {}
    total_stats = _Stats()
    mapped_participations = 0
    unattributed_participations = 0
    unattributed_events = 0
    outside_membership_participations = 0
    outside_membership_events = 0
    fixtures_with_reports: set[str] = set()
    fixture_team_by_id: dict[str, str] = {}
    team_external_to_id: dict[str, str] = {}

    membership_team_ids = set(memberships_by_team)
    if identity is not None:
        participation_rows = (
            await session.execute(
                select(FixturePlayerParticipation, Fixture, Competition.name, Season.name)
                .join(Fixture, FixturePlayerParticipation.fixture_id == Fixture.id)
                .join(Competition, Fixture.competition_id == Competition.id)
                .join(Season, Fixture.season_id == Season.id)
                .where(
                    FixturePlayerParticipation.provider == provider,
                    FixturePlayerParticipation.player_external_id == identity.external_id,
                    Fixture.status == "finished",
                )
                .order_by(Fixture.kickoff_at.asc(), Fixture.id.asc())
            )
        ).all()

        event_rows = (
            await session.execute(
                select(FixtureMatchEvent, Fixture, Competition.name, Season.name)
                .join(Fixture, FixtureMatchEvent.fixture_id == Fixture.id)
                .join(Competition, Fixture.competition_id == Competition.id)
                .join(Season, Fixture.season_id == Season.id)
                .where(
                    FixtureMatchEvent.provider == provider,
                    or_(
                        FixtureMatchEvent.player_external_id == identity.external_id,
                        FixtureMatchEvent.secondary_player_external_id == identity.external_id,
                    ),
                    Fixture.status == "finished",
                )
                .order_by(Fixture.kickoff_at.asc(), Fixture.id.asc())
            )
        ).all()

        external_team_ids = {
            row.team_external_id for row, _, _, _ in participation_rows if row.team_external_id
        }
        external_team_ids.update(
            str(event.payload.get("team_external_id"))
            for event, _, _, _ in event_rows
            if event.payload.get("team_external_id") is not None
        )
        mapping_conditions = []
        if membership_team_ids:
            mapping_conditions.append(ExternalIDMapping.entity_id.in_(membership_team_ids))
        if external_team_ids:
            mapping_conditions.append(ExternalIDMapping.external_id.in_(external_team_ids))
        if mapping_conditions:
            team_mappings = (
                await session.scalars(
                    select(ExternalIDMapping).where(
                        ExternalIDMapping.provider == provider,
                        ExternalIDMapping.entity_type == "team",
                        or_(*mapping_conditions),
                    )
                )
            ).all()
            team_external_to_id = {row.external_id: row.entity_id for row in team_mappings}

        for row, fixture, competition_name, season_name in participation_rows:
            team_id = team_external_to_id.get(row.team_external_id or "")
            if team_id is None:
                team_id = _infer_membership_team(
                    fixture, fixture.kickoff_at.date(), memberships_by_team
                )
            if team_id not in {fixture.home_team_id, fixture.away_team_id}:
                team_id = None
            if team_id is None:
                unattributed_participations += 1
                continue
            periods = memberships_by_team.get(team_id, [])
            if periods and not _active_membership(periods, fixture.kickoff_at.date()):
                outside_membership_participations += 1
                continue
            fixture_team_by_id[fixture.id] = team_id
            _new_stats(team_stats, team_id).add_participation(row)
            _new_stats(
                competition_stats, (team_id, fixture.competition_id, fixture.season_id)
            ).add_participation(row)
            competition_names[(team_id, fixture.competition_id, fixture.season_id)] = (
                competition_name,
                season_name,
            )
            total_stats.add_participation(row)
            mapped_participations += 1
            fixtures_with_reports.add(fixture.id)

        for event, fixture, competition_name, season_name in event_rows:
            team_external_id = event.payload.get("team_external_id")
            team_id = (
                team_external_to_id.get(str(team_external_id))
                if team_external_id is not None
                else None
            )
            if team_id is None:
                team_id = fixture_team_by_id.get(fixture.id)
            if team_id is None:
                team_id = _infer_membership_team(
                    fixture, fixture.kickoff_at.date(), memberships_by_team
                )
            if team_id not in {fixture.home_team_id, fixture.away_team_id}:
                team_id = None
            if team_id is None:
                unattributed_events += 1
                continue
            periods = memberships_by_team.get(team_id, [])
            if periods and not _active_membership(periods, fixture.kickoff_at.date()):
                outside_membership_events += 1
                continue
            _new_stats(team_stats, team_id).add_event(event, fixture.id, identity.external_id)
            _new_stats(
                competition_stats, (team_id, fixture.competition_id, fixture.season_id)
            ).add_event(event, fixture.id, identity.external_id)
            competition_names[(team_id, fixture.competition_id, fixture.season_id)] = (
                competition_name,
                season_name,
            )
            total_stats.add_event(event, fixture.id, identity.external_id)
            fixtures_with_reports.add(fixture.id)

    team_ids = membership_team_ids | set(team_stats)
    teams = {}
    if team_ids:
        team_rows = await session.scalars(select(Team).where(Team.id.in_(team_ids)))
        teams = {team.id: team for team in team_rows.all()}

    clubs: list[dict[str, Any]] = []
    for team_id in team_ids:
        team = teams.get(team_id)
        if team is None:
            continue
        club_memberships = memberships_by_team.get(team_id, [])
        competition_items = []
        for (stats_team_id, competition_id, season_id), stats in competition_stats.items():
            if stats_team_id != team_id:
                continue
            competition_name, season_name = competition_names.get(
                (team_id, competition_id, season_id), ("", "")
            )
            competition_items.append(
                {
                    "competition_id": competition_id,
                    "competition_name": competition_name,
                    "season_id": season_id,
                    "season_name": season_name,
                    **stats.as_dict(),
                }
            )
        competition_items.sort(key=lambda item: (item["competition_name"], item["season_name"]))
        club_membership_reads = []
        for membership in club_memberships:
            read = _membership_read(membership)
            read["team_name"] = team.name
            club_membership_reads.append(read)
        clubs.append(
            {
                "team_id": team_id,
                "team_name": team.name,
                "membership_confirmed": bool(club_memberships),
                "provider_team_linked": team_id in team_external_to_id.values(),
                "membership_periods": club_membership_reads,
                "competitions": competition_items,
                **team_stats.get(team_id, _Stats()).as_dict(),
            }
        )
    clubs.sort(
        key=lambda item: (
            min(
                (membership["joined_on"] or date.min for membership in item["membership_periods"]),
                default=date.max,
            ),
            item["team_name"].casefold(),
            item["team_id"],
        )
    )

    return {
        "player_id": player_id,
        "provider": provider,
        "provider_identity_linked": identity is not None,
        "totals": {
            **total_stats.as_dict(),
            "fixtures_with_reports": len(fixtures_with_reports),
        },
        "clubs": clubs,
        "coverage": {
            "memberships": len(memberships),
            "mapped_participations": mapped_participations,
            "unattributed_participations": unattributed_participations,
            "unattributed_events": unattributed_events,
            "outside_membership_participations": outside_membership_participations,
            "outside_membership_events": outside_membership_events,
        },
    }


async def build_team_player_contributions(
    session: AsyncSession,
    *,
    team_id: str,
    competition_id: str | None = None,
    season_id: str | None = None,
    metric: str = "goals",
    limit: int = 100,
    offset: int = 0,
    provider: str = DEFAULT_PROVIDER,
) -> dict[str, Any]:
    """Aggregate provider-confirmed player contributions for one canonical team."""
    team = await session.get(Team, team_id)
    memberships = list(
        (
            await session.scalars(
                select(TeamMembership)
                .where(TeamMembership.team_id == team_id)
                .order_by(
                    TeamMembership.joined_on.asc().nullsfirst(), TeamMembership.player_id.asc()
                )
            )
        ).all()
    )
    membership_by_player: dict[str, list[TeamMembership]] = defaultdict(list)
    for membership in memberships:
        membership_by_player[membership.player_id].append(membership)

    team_mapping = await session.scalar(
        select(ExternalIDMapping).where(
            ExternalIDMapping.provider == provider,
            ExternalIDMapping.entity_type == "team",
            ExternalIDMapping.entity_id == team_id,
        )
    )
    fixture_statement = select(Fixture.id).where(
        Fixture.status == "finished",
        or_(Fixture.home_team_id == team_id, Fixture.away_team_id == team_id),
    )
    if competition_id is not None:
        fixture_statement = fixture_statement.where(Fixture.competition_id == competition_id)
    if season_id is not None:
        fixture_statement = fixture_statement.where(Fixture.season_id == season_id)

    participation_rows = []
    event_rows = []
    if team_mapping is not None:
        participation_rows = (
            await session.execute(
                select(FixturePlayerParticipation, Fixture)
                .join(Fixture, FixturePlayerParticipation.fixture_id == Fixture.id)
                .where(
                    FixturePlayerParticipation.provider == provider,
                    FixturePlayerParticipation.team_external_id == team_mapping.external_id,
                    Fixture.id.in_(fixture_statement),
                )
                .order_by(Fixture.kickoff_at.asc(), Fixture.id.asc())
            )
        ).all()
        event_rows = (
            await session.execute(
                select(FixtureMatchEvent, Fixture)
                .join(Fixture, FixtureMatchEvent.fixture_id == Fixture.id)
                .where(
                    FixtureMatchEvent.provider == provider,
                    FixtureMatchEvent.fixture_id.in_(fixture_statement),
                    Fixture.status == "finished",
                )
                .order_by(Fixture.kickoff_at.asc(), Fixture.id.asc())
            )
        ).all()

    external_player_ids = {
        row.player_external_id for row, _ in participation_rows if row.player_external_id
    }
    for event, _ in event_rows:
        if event.player_external_id:
            external_player_ids.add(event.player_external_id)
        if event.secondary_player_external_id:
            external_player_ids.add(event.secondary_player_external_id)

    player_external_to_id: dict[str, str] = {}
    if external_player_ids:
        player_mappings = (
            await session.scalars(
                select(ExternalIDMapping).where(
                    ExternalIDMapping.provider == provider,
                    ExternalIDMapping.entity_type == "player",
                    ExternalIDMapping.external_id.in_(external_player_ids),
                )
            )
        ).all()
        player_external_to_id = {row.external_id: row.entity_id for row in player_mappings}

    player_ids = set(membership_by_player) | set(player_external_to_id.values())
    players: dict[str, Player] = {}
    if player_ids:
        player_rows = await session.scalars(select(Player).where(Player.id.in_(player_ids)))
        players = {player.id: player for player in player_rows.all()}

    stats_by_player: dict[str, _Stats] = {player_id: _Stats() for player_id in player_ids}
    participation_team_by_fixture_player: set[tuple[str, str]] = set()
    linked_provider_players: set[str] = set()
    unlinked_provider_players: set[str] = set()
    unlinked_provider_events = 0

    for row, fixture in participation_rows:
        player_id = player_external_to_id.get(row.player_external_id)
        if player_id is None:
            unlinked_provider_players.add(row.player_external_id)
            continue
        linked_provider_players.add(player_id)
        participation_team_by_fixture_player.add((fixture.id, row.player_external_id))
        stats_by_player.setdefault(player_id, _Stats()).add_participation(row)

    for event, fixture in event_rows:
        event_team_external_id = event.payload.get("team_external_id")
        if event_team_external_id is not None:
            belongs_to_team = str(event_team_external_id) == team_mapping.external_id
        else:
            belongs_to_team = any(
                (fixture.id, external_id) in participation_team_by_fixture_player
                for external_id in (
                    event.player_external_id,
                    event.secondary_player_external_id,
                )
                if external_id is not None
            )
        if not belongs_to_team:
            continue

        roles = []
        if event.event_type == "goal":
            roles = [
                event.player_external_id,
                event.secondary_player_external_id,
            ]
        elif event.event_type == "booking":
            roles = [event.player_external_id]
        elif event.event_type == "substitution":
            roles = [event.player_external_id, event.secondary_player_external_id]
        for external_id in roles:
            if external_id is None:
                continue
            player_id = player_external_to_id.get(external_id)
            if player_id is None:
                unlinked_provider_events += 1
                continue
            linked_provider_players.add(player_id)
            stats_by_player.setdefault(player_id, _Stats()).add_event(
                event, fixture.id, external_id
            )

    items = []
    for player_id, stats in stats_by_player.items():
        player = players.get(player_id)
        if player is None:
            continue
        periods = membership_by_player.get(player_id, [])
        membership_reads = [
            {
                "membership_id": row.id,
                "team_id": team_id,
                "team_name": "",
                "joined_on": row.joined_on,
                "left_on": row.left_on,
                "shirt_number": row.shirt_number,
            }
            for row in periods
        ]
        for membership in membership_reads:
            membership["team_name"] = team.name if team is not None else ""
        items.append(
            {
                "player_id": player_id,
                "player_name": player.display_name,
                "position": player.position,
                "membership_confirmed": bool(periods),
                "membership_periods": membership_reads,
                **stats.as_dict(),
            }
        )

    metric_values = {
        "goals": "goals",
        "assists": "assists",
        "appearances": "appearances",
        "starts": "starts",
        "yellow_cards": "yellow_cards",
        "red_cards": "red_cards",
    }
    metric_key = metric_values.get(metric, "goals")
    items.sort(
        key=lambda item: (
            -int(item[metric_key]),
            str(item["player_name"]).casefold(),
            str(item["player_id"]),
        )
    )
    total = len(items)
    page = items[offset : offset + limit]
    for rank, item in enumerate(page, start=offset + 1):
        item["rank"] = rank

    return {
        "team_id": team_id,
        "provider": provider,
        "provider_team_linked": team_mapping is not None,
        "competition_id": competition_id,
        "season_id": season_id,
        "metric": metric,
        "linked_players": len(linked_provider_players),
        "membership_players": len(membership_by_player),
        "unlinked_provider_players": len(unlinked_provider_players),
        "unlinked_provider_events": unlinked_provider_events,
        "items": page,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
