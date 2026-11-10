"""Tests for provider-neutral sports ingestion schemas."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from chezaport.sports.domain.enums import FixtureStatus
from chezaport.sports.integrations.schemas import ProviderFixture, ProviderTeam


def test_provider_team_normalizes_whitespace() -> None:
    team = ProviderTeam(external_id="  team-1 ", name=" Arsenal ", slug=" arsenal ")
    assert team.external_id == "team-1"
    assert team.name == "Arsenal"
    assert team.slug == "arsenal"


def test_provider_fixture_accepts_normalized_status_and_timezone() -> None:
    fixture = ProviderFixture(
        external_id="fixture-1",
        competition_external_id="league-1",
        season_external_id="season-1",
        home_team_external_id="team-1",
        away_team_external_id="team-2",
        kickoff_at=datetime(2026, 11, 10, 15, 0, tzinfo=UTC),
        status=FixtureStatus.SCHEDULED,
    )
    assert fixture.status is FixtureStatus.SCHEDULED


def test_provider_fixture_rejects_naive_kickoff() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        ProviderFixture(
            external_id="fixture-1",
            competition_external_id="league-1",
            season_external_id="season-1",
            home_team_external_id="team-1",
            away_team_external_id="team-2",
            kickoff_at=datetime(2026, 11, 10, 15, 0),
        )


def test_provider_fixture_rejects_same_home_and_away_team() -> None:
    with pytest.raises(ValidationError, match="different"):
        ProviderFixture(
            external_id="fixture-1",
            competition_external_id="league-1",
            season_external_id="season-1",
            home_team_external_id="team-1",
            away_team_external_id="team-1",
            kickoff_at=datetime(2026, 11, 10, 15, 0, tzinfo=UTC),
        )
