# ADR 0003: Free-first football data provider selection

- Status: Deferred — keep the provider-neutral boundary
- Date: 2026-11-10

## Context

Chezaport must start with a free development path, avoid paid API dependencies, and remain suitable for a public sports information product. A provider is not acceptable merely because an endpoint responds: competition coverage, season-level field availability, rate limits, freshness, attribution, redistribution, commercial-use and image rights all matter.

The canonical domain and `SportsDataProvider` protocol remain provider-neutral. No provider-specific identifiers or payload fields should be added to canonical sports tables.

## Candidates reviewed

### OpenLigaDB

- API access: no registration or API key required.
- Published limit: 60 requests per minute per IP; the API asks clients to poll sparingly and use its last-change endpoint.
- Data scope: community-maintained football and other league-shaped sports data, with a strong visible emphasis on German and European competitions. It is not a verified source for the Kenyan FKF Premier League.
- Data licence: OpenLigaDB states that API data is under ODbL 1.0. Public use of produced works requires a source/licence notice; publicly used derivative databases trigger share-alike and machine-readable availability obligations. The database licence does not automatically clear individual logos, images, or other third-party content.
- Assessment: best low-friction candidate for a development adapter and a European sample dataset, not a global or Kenya-first source.

Sources:
- https://api.openligadb.de/
- https://www.openligadb.de/
- https://opendatacommons.org/licenses/odbl/1-0/

### football-data.org

- Free plan: 12 competitions, delayed scores and schedules, fixtures, league tables, and 10 requests per minute.
- Coverage: the published free set includes selected European competitions and international tournaments; the current free list does not include the Kenyan FKF Premier League.
- Assessment: useful if the first product scope is limited to the listed competitions; insufficient as the only source for a Kenya-first platform.

Sources:
- https://www.football-data.org/pricing
- https://www.football-data.org/coverage
- https://www.football-data.org/documentation/api

### API-Football (API-SPORTS)

- Free plan: 100 requests per day, no credit card required; plan page lists broad endpoints including fixtures, standings, teams, players, events, and statistics. Free access is limited by available seasons; a provider guide states a 10 requests/minute limit.
- Coverage: its current coverage page lists Kenya's FKF Premier League, Shield Cup, Super Cup, and Super League. Coverage and fields vary by competition and season; the coverage page alone does not prove the exact current season data is available on the free plan.
- Terms risk: the terms prohibit reselling provider data and say the provider does not grant a licence for publication of data; users must obtain any required permissions from competent rights holders. Logos/images may have separate third-party rights.
- Assessment: strongest candidate found for testing Kenyan competition availability, but do not make it a production/public-display dependency until season-level coverage and publication rights are confirmed.

Sources:
- https://www.api-football.com/pricing
- https://www.api-football.com/coverage
- https://www.api-football.com/documentation_v3
- https://www.api-football.com/terms

### TheSportsDB

- Free API: public key `123`, 30 requests per minute, with endpoint-specific result limits.
- Terms: free API use is for development lookups; publishing apps to an app store requires a paid subscription. Artwork has separate, per-image licensing and third-party rights requirements.
- Assessment: not suitable as the sole free production provider for a publicly distributed application. It may be useful for local experiments or metadata enrichment where permitted.

Sources:
- https://www.thesportsdb.com/docs/api
- https://www.thesportsdb.com/docs_terms_of_use.php

## Decision

Do not hard-code a provider choice yet.

1. Keep the provider-neutral integration schemas, protocol, and canonical ingestion service as the stable boundary.
2. Do not rely on API-Football or TheSportsDB as a public production data source under their free terms without further rights review.
3. OpenLigaDB may be used for a small development adapter and European fixture-ingestion validation, provided ODbL attribution/share-alike obligations are implemented and third-party artwork is excluded unless separately cleared.
4. Before a production adapter is selected, verify the user's first target competitions, exact season/endpoint coverage, update cadence, attribution requirements, and rights to display/cache/derive the data.

## Consequences

The next implementation increment can build adapter tests and an OpenLigaDB development adapter without locking the domain to that provider. A Kenya-first production feed remains an explicit decision gate. No paid provider or paid plan is introduced by this ADR.
