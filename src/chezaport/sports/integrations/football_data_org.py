"""football-data.org v4 adapter for the provider-neutral sports ingestion boundary.

The adapter only normalizes public football information. It does not expose
provider response models to the application domain.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin

import httpx

from chezaport.sports.domain.enums import FixtureStatus
from chezaport.sports.integrations.capabilities import (
    ProviderCapabilities,
    ProviderResource,
)
from chezaport.sports.integrations.errors import (
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from chezaport.sports.integrations.schemas import (
    ProviderCompetition,
    ProviderFixture,
    ProviderSeason,
    ProviderTeam,
)


class FootballDataOrgProvider:
    """Async football-data.org v4 adapter.

    The caller owns the HTTP client lifecycle when injecting a client. If no
    client is supplied, the adapter creates and closes a short-lived client for
    each request. Production composition should inject a shared AsyncClient.
    """

    provider_name = "football-data-org"
    base_url = "https://api.football-data.org/v4/"

    def __init__(
        self,
        api_token: str,
        *,
        competition_codes: frozenset[str] = frozenset({"PL"}),
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        token = api_token.strip()
        if not token:
            raise ProviderConfigurationError("football-data.org API token is required")
        codes = frozenset(code.strip().upper() for code in competition_codes)
        if not codes or any(not code for code in codes):
            raise ProviderConfigurationError("at least one competition code is required")
        self._token = token
        self._competition_codes = codes
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._capabilities = ProviderCapabilities(
            competition_codes=codes,
            resources=frozenset(ProviderResource),
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def fetch_competitions(self, sport_code: str) -> tuple[ProviderCompetition, ...]:
        if sport_code.strip().lower() != "football":
            return ()
        payload = await self._get("competitions")
        return tuple(
            ProviderCompetition(
                external_id=str(item["id"]),
                name=item["name"],
                slug=_slug(item.get("code") or item["name"]),
                sport_code="football",
                country_code=(item.get("area") or {}).get("code"),
                country_name=(item.get("area") or {}).get("name"),
                competition_type=_competition_type(item.get("type")),
            )
            for item in _records(payload, "competitions")
            if item.get("code") in self._competition_codes
        )

    async def fetch_seasons(self, competition_external_id: str) -> tuple[ProviderSeason, ...]:
        payload = await self._get(f"competitions/{_safe_id(competition_external_id)}")
        competition_id = str(payload["id"])
        seasons = _records(payload, "seasons")
        current = payload.get("currentSeason")
        if not seasons and isinstance(current, dict):
            seasons = [current]
        normalized: dict[str, ProviderSeason] = {}
        for item in seasons:
            start = _optional_date(item.get("startDate"))
            end = _optional_date(item.get("endDate"))
            season_id = str(start.year) if start is not None else ""
            if not season_id:
                continue
            normalized[season_id] = ProviderSeason(
                external_id=season_id,
                competition_external_id=competition_id,
                name=_season_name(start, end),
                start_date=start,
                end_date=end,
                is_current=bool(current and str(current.get("id")) == str(item.get("id"))),
            )
        return tuple(normalized.values())

    async def fetch_teams(self, competition_external_id: str) -> tuple[ProviderTeam, ...]:
        payload = await self._get(f"competitions/{_safe_id(competition_external_id)}/teams")
        teams: list[ProviderTeam] = []
        for item in _records(payload, "teams"):
            area = item.get("area") or {}
            name = item.get("name") or item.get("shortName")
            if not name:
                continue
            teams.append(
                ProviderTeam(
                    external_id=str(item["id"]),
                    name=name,
                    slug=_slug(item.get("shortName") or name),
                    short_name=item.get("tla") or item.get("shortName"),
                    country_code=area.get("code"),
                    country_name=area.get("name"),
                )
            )
        return tuple(teams)

    async def fetch_fixtures(
        self,
        competition_external_id: str,
        season_external_id: str,
        *,
        since: datetime | None = None,
    ) -> tuple[ProviderFixture, ...]:
        params: dict[str, str] = {"season": _season_query(season_external_id)}
        if since is not None:
            if since.tzinfo is None or since.utcoffset() is None:
                raise ValueError("since must be timezone-aware")
            date_from = since.astimezone(UTC).date()
            # football-data.org requires dateFrom and dateTo together. Keep a
            # rolling one-year window so one refresh includes recent corrections
            # and all scheduled fixtures still ahead in the selected season.
            date_to = max(datetime.now(UTC).date(), date_from) + timedelta(days=365)
            params["dateFrom"] = date_from.isoformat()
            params["dateTo"] = date_to.isoformat()
        payload = await self._get(
            f"competitions/{_safe_id(competition_external_id)}/matches",
            params=params,
        )
        fixtures: list[ProviderFixture] = []
        for item in _records(payload, "matches"):
            home = item.get("homeTeam") or {}
            away = item.get("awayTeam") or {}
            utc_date = item.get("utcDate")
            if not home.get("id") or not away.get("id") or not utc_date:
                continue
            season = item.get("season") or {}
            season_start = _optional_date(season.get("startDate"))
            season_key = (
                str(season_start.year)
                if season_start is not None
                else _season_query(season_external_id)
            )
            score = item.get("score") or {}
            full_time = score.get("fullTime") or {}
            fixtures.append(
                ProviderFixture(
                    external_id=str(item["id"]),
                    competition_external_id=str(
                        (item.get("competition") or {}).get("id", competition_external_id)
                    ),
                    season_external_id=season_key or _season_query(season_external_id),
                    home_team_external_id=str(home["id"]),
                    away_team_external_id=str(away["id"]),
                    kickoff_at=_datetime(utc_date),
                    status=_fixture_status(item.get("status")),
                    home_score=full_time.get("home"),
                    away_score=full_time.get("away"),
                    round_name=(
                        str(item["matchday"])
                        if item.get("matchday") is not None
                        else item.get("stage")
                    ),
                )
            )
        return tuple(fixtures)

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = urljoin(self.base_url, path.lstrip("/"))
        headers = {"X-Auth-Token": self._token, "Accept": "application/json"}
        try:
            if self._client is not None:
                response = await self._client.get(url, headers=headers, params=params)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(url, headers=headers, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("football-data.org request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("football-data.org request failed") from exc

        if response.status_code == 429:
            retry_after = _retry_after(response.headers)
            raise ProviderRateLimitError(
                "football-data.org rate limit reached",
                retry_after_seconds=retry_after,
            )
        if response.status_code in (401, 403):
            raise ProviderConfigurationError(
                "football-data.org rejected credentials or resource access "
                f"({response.status_code})"
            )
        if response.status_code >= 500:
            raise ProviderUnavailableError(
                f"football-data.org returned server error ({response.status_code})"
            )
        if response.status_code >= 400:
            raise ProviderConfigurationError(
                f"football-data.org rejected request ({response.status_code})"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderUnavailableError("football-data.org returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ProviderUnavailableError("football-data.org returned an unexpected payload")
        return data


def _records(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = payload.get(key, [])
    return (
        [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []
    )


def _safe_id(value: str) -> str:
    result = value.strip()
    if not result or not result.isdigit():
        raise ValueError("provider resource ID must be numeric")
    return result


def _slug(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def _competition_type(value: str | None) -> str:
    return "league" if value in ("LEAGUE", "LEAGUE_CUP") else "cup"


def _optional_date(value: Any) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def _season_name(start: date | None, end: date | None) -> str:
    if start is None:
        return "Unknown season"
    if end is None:
        return str(start.year)
    return f"{start.year}/{str(end.year)[-2:]}"


def _season_query(value: str) -> str:
    result = value.strip()
    if not result.isdigit() or len(result) != 4:
        raise ValueError("season_external_id must be a four-digit season start year")
    return result


def _datetime(value: Any) -> datetime:
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("provider kickoff timestamp must be timezone-aware")
    return result


def _fixture_status(value: str | None) -> FixtureStatus:
    mapping = {
        "TIMED": FixtureStatus.SCHEDULED,
        "SCHEDULED": FixtureStatus.SCHEDULED,
        "IN_PLAY": FixtureStatus.LIVE,
        "LIVE": FixtureStatus.LIVE,
        "PAUSED": FixtureStatus.HALFTIME,
        "FINISHED": FixtureStatus.FINISHED,
        "POSTPONED": FixtureStatus.POSTPONED,
        "SUSPENDED": FixtureStatus.SUSPENDED,
        "CANCELLED": FixtureStatus.CANCELLED,
        "AWARDED": FixtureStatus.FINISHED,
    }
    return mapping.get(value or "", FixtureStatus.SCHEDULED)


def _retry_after(headers: httpx.Headers) -> float | None:
    value = headers.get("Retry-After") or headers.get("X-RequestCounter-Reset")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
