"""Provider-neutral payload schemas used at the ingestion boundary."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from chezaport.sports.domain.enums import FixtureStatus


class ProviderPayload(BaseModel):
    """Base schema for normalized provider records."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    external_id: str = Field(min_length=1, max_length=160)

    @field_validator("external_id")
    @classmethod
    def external_id_must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("external_id must not be blank")
        return value


class ProviderCompetition(ProviderPayload):
    """A competition as normalized from an external data provider."""

    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=180)
    sport_code: str = Field(default="football", min_length=1, max_length=32)
    country_code: str | None = Field(default=None, max_length=3)
    competition_type: str = Field(default="league", min_length=1, max_length=32)


class ProviderSeason(ProviderPayload):
    """A season/edition belonging to a provider competition."""

    competition_external_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=80)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False

    @model_validator(mode="after")
    def dates_must_be_ordered(self) -> "ProviderSeason":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class ProviderTeam(ProviderPayload):
    """A team normalized from a provider payload."""

    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=180)
    sport_code: str = Field(default="football", min_length=1, max_length=32)
    country_code: str | None = Field(default=None, max_length=3)
    short_name: str | None = Field(default=None, max_length=40)


class ProviderFixture(ProviderPayload):
    """A fixture whose related entities are identified by provider IDs."""

    competition_external_id: str = Field(min_length=1, max_length=160)
    season_external_id: str = Field(min_length=1, max_length=160)
    home_team_external_id: str = Field(min_length=1, max_length=160)
    away_team_external_id: str = Field(min_length=1, max_length=160)
    kickoff_at: datetime
    status: FixtureStatus = FixtureStatus.SCHEDULED
    home_score: int | None = Field(default=None, ge=0)
    away_score: int | None = Field(default=None, ge=0)
    round_name: str | None = Field(default=None, max_length=80)

    @field_validator("kickoff_at")
    @classmethod
    def kickoff_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("kickoff_at must include a timezone")
        return value

    @field_validator("away_team_external_id")
    @classmethod
    def teams_must_be_different(cls, value: str, info: object) -> str:
        home_team_id = getattr(info, "data", {}).get("home_team_external_id")
        if home_team_id is not None and value == home_team_id:
            raise ValueError("home and away teams must be different")
        return value
