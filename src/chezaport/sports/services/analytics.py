"""Deterministic football analytics derived from canonical finished fixtures."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from chezaport.sports.models import Fixture, Season, Team


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
    team_id: str | None = None,
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
    if team_ids is not None and team_id is not None:
        raise ValueError("provide either a team pair or one team, not both")
    if team_ids is not None:
        first, second = team_ids
        statement = statement.where(
            ((Fixture.home_team_id == first) & (Fixture.away_team_id == second))
            | ((Fixture.home_team_id == second) & (Fixture.away_team_id == first))
        )
    elif team_id is not None:
        statement = statement.where(
            (Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id)
        )
    result = await session.execute(statement)
    return [(fixture, home_name, away_name) for fixture, home_name, away_name in result.all()]


async def calculate_competition_statistics(
    session: AsyncSession, *, competition_id: str, season_id: str
) -> dict[str, object]:
    """Summarize completed match outcomes and scoring for one competition season."""
    fixtures = await _finished_fixtures(session, competition_id=competition_id, season_id=season_id)
    home_wins = draws = away_wins = home_goals = away_goals = 0
    highest: dict[str, object] | None = None
    highest_goals = -1
    total_goals = 0
    for fixture, home_name, away_name in fixtures:
        assert fixture.home_score is not None and fixture.away_score is not None
        home_score, away_score = fixture.home_score, fixture.away_score
        home_goals += home_score
        away_goals += away_score
        total_goals += home_score + away_score
        if home_score > away_score:
            home_wins += 1
        elif home_score < away_score:
            away_wins += 1
        else:
            draws += 1
        if home_score + away_score > highest_goals:
            highest_goals = home_score + away_score
            highest = {
                "fixture_id": fixture.id,
                "kickoff_at": fixture.kickoff_at,
                "home_team_id": fixture.home_team_id,
                "home_team_name": home_name,
                "away_team_id": fixture.away_team_id,
                "away_team_name": away_name,
                "home_score": home_score,
                "away_score": away_score,
                "total_goals": home_score + away_score,
            }
    played = len(fixtures)
    return {
        "played": played,
        "total_goals": total_goals,
        "average_goals_per_match": round(total_goals / played, 2) if played else None,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "home_wins": home_wins,
        "draws": draws,
        "away_wins": away_wins,
        "highest_scoring_match": highest,
    }


async def calculate_competition_season_comparison(
    session: AsyncSession, *, competition_id: str
) -> list[dict[str, object]]:
    """Compare completed-season outcomes and scoring within one competition."""
    result = await session.execute(
        select(Season)
        .where(Season.competition_id == competition_id)
        .order_by(Season.start_date.asc(), Season.name.asc(), Season.id.asc())
    )
    seasons = list(result.scalars().all())
    comparison: list[dict[str, object]] = []
    for season in seasons:
        statistics = await calculate_competition_statistics(
            session, competition_id=competition_id, season_id=season.id
        )
        standings = await calculate_standings(
            session, competition_id=competition_id, season_id=season.id
        )
        champion = standings[0] if standings else None
        comparison.append(
            {
                "season_id": season.id,
                "season_name": season.name,
                "start_date": season.start_date,
                "end_date": season.end_date,
                "played": statistics["played"],
                "total_goals": statistics["total_goals"],
                "average_goals_per_match": statistics["average_goals_per_match"],
                "home_wins": statistics["home_wins"],
                "draws": statistics["draws"],
                "away_wins": statistics["away_wins"],
                "teams_with_results": sum(1 for row in standings if row["played"]),
                "teams_in_competition": len(standings),
                "leader": (
                    {
                        "team_id": champion["team_id"],
                        "team_name": champion["team_name"],
                        "points": champion["points"],
                        "goal_difference": champion["goal_difference"],
                        "position": champion["position"],
                    }
                    if champion is not None
                    else None
                ),
                "highest_scoring_match": statistics["highest_scoring_match"],
            }
        )
    return comparison


async def calculate_standings(
    session: AsyncSession, *, competition_id: str, season_id: str
) -> list[dict[str, object]]:
    """Calculate a conventional 3-1-0 table from finished fixtures only.

    Tie-break order is points, goal difference, goals scored, then team name.
    Postponed, abandoned, cancelled, live, and unplayed fixtures are excluded.
    """
    fixtures = await _finished_fixtures(session, competition_id=competition_id, season_id=season_id)
    participating_team_ids = (
        select(Fixture.home_team_id)
        .where(Fixture.competition_id == competition_id, Fixture.season_id == season_id)
        .union(
            select(Fixture.away_team_id).where(
                Fixture.competition_id == competition_id, Fixture.season_id == season_id
            )
        )
    )
    participants = await session.execute(
        select(Team.id, Team.name).where(Team.id.in_(participating_team_ids))
    )
    totals: dict[str, TeamTotals] = {}

    def ensure(team_id: str, name: str) -> TeamTotals:
        if team_id not in totals:
            totals[team_id] = TeamTotals(team_id=team_id, team_name=name)
        return totals[team_id]

    for team_id, team_name in participants.all():
        ensure(team_id, team_name)

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


async def calculate_team_season_statistics(
    session: AsyncSession, *, competition_id: str, season_id: str, team_id: str
) -> dict[str, object]:
    """Calculate a team's season record and home/away split from finished fixtures."""
    fixtures = await _finished_fixtures(
        session, competition_id=competition_id, season_id=season_id, team_id=team_id
    )
    played = won = drawn = lost = goals_for = goals_against = clean_sheets = 0
    home_played = home_won = home_drawn = home_lost = home_goals_for = home_goals_against = 0
    away_played = away_won = away_drawn = away_lost = away_goals_for = away_goals_against = 0
    biggest_win: dict[str, object] | None = None
    biggest_margin = 0
    for fixture, home_name, away_name in fixtures:
        if team_id not in (fixture.home_team_id, fixture.away_team_id):
            continue
        assert fixture.home_score is not None and fixture.away_score is not None
        is_home = fixture.home_team_id == team_id
        scored = fixture.home_score if is_home else fixture.away_score
        conceded = fixture.away_score if is_home else fixture.home_score
        played += 1
        goals_for += scored
        goals_against += conceded
        clean_sheets += int(conceded == 0)
        prefix = "home" if is_home else "away"
        if is_home:
            home_played += 1
            home_goals_for += scored
            home_goals_against += conceded
        else:
            away_played += 1
            away_goals_for += scored
            away_goals_against += conceded
        outcome = "won" if scored > conceded else "lost" if scored < conceded else "drawn"
        if outcome == "won":
            won += 1
        elif outcome == "lost":
            lost += 1
        else:
            drawn += 1
        if is_home:
            home_won += int(outcome == "won")
            home_drawn += int(outcome == "drawn")
            home_lost += int(outcome == "lost")
        else:
            away_won += int(outcome == "won")
            away_drawn += int(outcome == "drawn")
            away_lost += int(outcome == "lost")
        margin = scored - conceded
        if margin > biggest_margin:
            biggest_margin = margin
            biggest_win = {
                "fixture_id": fixture.id,
                "kickoff_at": fixture.kickoff_at,
                "opponent_id": fixture.away_team_id if is_home else fixture.home_team_id,
                "opponent_name": away_name if is_home else home_name,
                "venue": prefix,
                "goals_for": scored,
                "goals_against": conceded,
                "goal_margin": margin,
            }

    def split(
        matches: int, wins: int, draws: int, losses: int, scored: int, conceded: int
    ) -> dict[str, object]:
        return {
            "played": matches,
            "won": wins,
            "drawn": draws,
            "lost": losses,
            "goals_for": scored,
            "goals_against": conceded,
            "goal_difference": scored - conceded,
            "win_rate": round(wins / matches * 100, 2) if matches else None,
        }

    return {
        "played": played,
        "won": won,
        "drawn": drawn,
        "lost": lost,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "goal_difference": goals_for - goals_against,
        "clean_sheets": clean_sheets,
        "win_rate": round(won / played * 100, 2) if played else None,
        "home": split(
            home_played, home_won, home_drawn, home_lost, home_goals_for, home_goals_against
        ),
        "away": split(
            away_played, away_won, away_drawn, away_lost, away_goals_for, away_goals_against
        ),
        "biggest_win": biggest_win,
    }


async def calculate_team_form(
    session: AsyncSession,
    *,
    competition_id: str,
    season_id: str,
    team_id: str,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Return a team's most recent completed results, newest first."""
    fixtures = await _finished_fixtures(
        session, competition_id=competition_id, season_id=season_id, team_id=team_id
    )
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


async def calculate_team_season_comparison(
    session: AsyncSession, *, competition_id: str, team_id: str
) -> list[dict[str, object]]:
    """Compare one team's completed-season record across a competition's seasons."""
    seasons_result = await session.execute(
        select(Season)
        .where(Season.competition_id == competition_id)
        .order_by(Season.start_date.asc(), Season.name.asc(), Season.id.asc())
    )
    comparisons: list[dict[str, object]] = []
    for season in seasons_result.scalars().all():
        statistics = await calculate_team_season_statistics(
            session, competition_id=competition_id, season_id=season.id, team_id=team_id
        )
        if not statistics["played"]:
            continue
        standings = await calculate_standings(
            session, competition_id=competition_id, season_id=season.id
        )
        table_row = next((row for row in standings if row["team_id"] == team_id), None)
        comparisons.append(
            {
                "season_id": season.id,
                "season_name": season.name,
                "start_date": season.start_date,
                "end_date": season.end_date,
                "position": table_row["position"] if table_row else None,
                "points": table_row["points"] if table_row else None,
                "statistics": statistics,
            }
        )
    return comparisons
