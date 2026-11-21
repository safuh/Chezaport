"""Deterministic football analytics derived from canonical finished fixtures."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from chezaport.sports.models import Fixture, Team


@dataclass(slots=True)
class TeamTotals:
    """Mutable accumulator used while building a competition table."""

    team_id: str
    team_name: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0
    _form: list[str] = field(default_factory=list)

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    def as_dict(self, position: int) -> dict[str, object]:
        return {
            "position": position,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "played": self.played,
            "won": self.won,
            "drawn": self.drawn,
            "lost": self.lost,
            "goals_for": self.goals_for,
            "goals_against": self.goals_against,
            "goal_difference": self.goal_difference,
            "points": self.points,
            "form": "".join(self._form[-5:]),
        }


async def _finished_fixtures(
    session: AsyncSession,
    *,
    competition_id: str,
    season_id: str,
    team_ids: tuple[str, str] | None = None,
) -> list[tuple[Fixture, str, str]]:
    """Fetch completed fixtures with both canonical team names."""
    home = aliased(Team)
    away = aliased(Team)
    statement = (
        select(Fixture, home.name, away.name)
        .join(home, Fixture.home_team_id == home.id)
        .join(away, Fixture.away_team_id == away.id)
        .where(
            Fixture.competition_id == competition_id,
            Fixture.season_id == season_id,
            Fixture.status == "finished",
            Fixture.home_score.is_not(None),
            Fixture.away_score.is_not(None),
        )
        .order_by(Fixture.kickoff_at.asc(), Fixture.id.asc())
    )
    if team_ids is not None:
        first, second = team_ids
        statement = statement.where(
            ((Fixture.home_team_id == first) & (Fixture.away_team_id == second))
            | ((Fixture.home_team_id == second) & (Fixture.away_team_id == first))
        )
    result = await session.execute(statement)
    return [(fixture, home_name, away_name) for fixture, home_name, away_name in result.all()]


async def calculate_standings(
    session: AsyncSession, *, competition_id: str, season_id: str
) -> list[dict[str, object]]:
    """Calculate a conventional 3-1-0 table from finished fixtures only.

    Tie-break order is points, goal difference, goals scored, then team name.
    Postponed, abandoned, cancelled, live, and unplayed fixtures are excluded.
    """
    fixtures = await _finished_fixtures(session, competition_id=competition_id, season_id=season_id)
    totals: dict[str, TeamTotals] = {}

    def ensure(team_id: str, name: str) -> TeamTotals:
        if team_id not in totals:
            totals[team_id] = TeamTotals(team_id=team_id, team_name=name)
        return totals[team_id]

    for fixture, home_name, away_name in fixtures:
        assert fixture.home_score is not None and fixture.away_score is not None
        home = ensure(fixture.home_team_id, home_name)
        away = ensure(fixture.away_team_id, away_name)
        home.played += 1
        away.played += 1
        home.goals_for += fixture.home_score
        home.goals_against += fixture.away_score
        away.goals_for += fixture.away_score
        away.goals_against += fixture.home_score
        if fixture.home_score > fixture.away_score:
            home.won += 1
            away.lost += 1
            home.points += 3
            home._form.append("W")
            away._form.append("L")
        elif fixture.home_score < fixture.away_score:
            away.won += 1
            home.lost += 1
            away.points += 3
            home._form.append("L")
            away._form.append("W")
        else:
            home.drawn += 1
            away.drawn += 1
            home.points += 1
            away.points += 1
            home._form.append("D")
            away._form.append("D")

    ordered = sorted(
        totals.values(),
        key=lambda row: (
            -row.points,
            -row.goal_difference,
            -row.goals_for,
            row.team_name.casefold(),
        ),
    )
    return [row.as_dict(position) for position, row in enumerate(ordered, start=1)]


async def calculate_team_form(
    session: AsyncSession,
    *,
    competition_id: str,
    season_id: str,
    team_id: str,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Return a team's most recent completed results, newest first."""
    fixtures = await _finished_fixtures(session, competition_id=competition_id, season_id=season_id)
    form: list[dict[str, object]] = []
    for fixture, home_name, away_name in reversed(fixtures):
        if team_id not in (fixture.home_team_id, fixture.away_team_id):
            continue
        assert fixture.home_score is not None and fixture.away_score is not None
        is_home = fixture.home_team_id == team_id
        goals_for = fixture.home_score if is_home else fixture.away_score
        goals_against = fixture.away_score if is_home else fixture.home_score
        outcome = "W" if goals_for > goals_against else "L" if goals_for < goals_against else "D"
        form.append(
            {
                "fixture_id": fixture.id,
                "kickoff_at": fixture.kickoff_at,
                "opponent_id": fixture.away_team_id if is_home else fixture.home_team_id,
                "opponent_name": away_name if is_home else home_name,
                "venue": "home" if is_home else "away",
                "goals_for": goals_for,
                "goals_against": goals_against,
                "outcome": outcome,
            }
        )
        if len(form) >= limit:
            break
    return form


async def calculate_head_to_head(
    session: AsyncSession,
    *,
    competition_id: str,
    season_id: str,
    team_a_id: str,
    team_b_id: str,
) -> dict[str, object]:
    """Aggregate completed meetings between two teams in one competition season."""
    if team_a_id == team_b_id:
        raise ValueError("team IDs must be different")
    fixtures = await _finished_fixtures(
        session,
        competition_id=competition_id,
        season_id=season_id,
        team_ids=(team_a_id, team_b_id),
    )
    team_a_wins = 0
    draws = 0
    team_b_wins = 0
    team_a_goals = 0
    team_b_goals = 0
    meetings: list[dict[str, object]] = []
    for fixture, home_name, away_name in reversed(fixtures):
        assert fixture.home_score is not None and fixture.away_score is not None
        a_home = fixture.home_team_id == team_a_id
        a_goals = fixture.home_score if a_home else fixture.away_score
        b_goals = fixture.away_score if a_home else fixture.home_score
        team_a_goals += a_goals
        team_b_goals += b_goals
        if a_goals > b_goals:
            team_a_wins += 1
        elif a_goals < b_goals:
            team_b_wins += 1
        else:
            draws += 1
        meetings.append(
            {
                "fixture_id": fixture.id,
                "kickoff_at": fixture.kickoff_at,
                "home_team": home_name,
                "away_team": away_name,
                "home_score": fixture.home_score,
                "away_score": fixture.away_score,
            }
        )
    return {
        "team_a_id": team_a_id,
        "team_b_id": team_b_id,
        "played": len(fixtures),
        "team_a_wins": team_a_wins,
        "draws": draws,
        "team_b_wins": team_b_wins,
        "team_a_goals": team_a_goals,
        "team_b_goals": team_b_goals,
        "meetings": meetings,
    }
