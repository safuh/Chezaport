# ADR 0005: Competition-aware provider routing

- Status: Accepted
- Date: 2026-11-10

## Context

Sports-data vendors differ in competition coverage, available fields, update
freshness, authentication requirements, quotas, and data-use terms. A single
global provider setting would make it difficult to add alternatives safely.
Blindly switching providers after an HTTP error is also unsafe: an alternate
source may not cover the competition or may return different resource
semantics and external identifiers.

The first pilot competition is the English Premier League (EPL), identified
internally by the competition code `PL`. The approved initial provider is
football-data.org.

## Decision

1. Provider adapters implement the existing provider-neutral
   `SportsDataProvider` protocol and normalize vendor payloads into Chezaport
   schemas.
2. `SportsProviderRegistry` registers adapters by stable provider name.
3. `CompetitionProviderRoute` defines an ordered candidate list per canonical
   competition code. EPL is routed to `football-data` first.
4. Provider-specific credentials, quotas, retry policy, and HTTP behavior stay
   inside the adapter/configuration boundary, not in domain models.
5. Provider external IDs remain namespaced by provider and resolve through
   `ExternalIDMapping`; canonical Chezaport IDs remain stable when sources
   change.
6. The registry exposes ordered candidates but does not perform blind,
   automatic failover. A caller may try an alternate only when that provider
   has verified coverage for the competition and requested resource, and the
   failure is safe to retry elsewhere.
7. Rate limits are provider-specific. A 429 response must honor the provider's
   retry metadata or wait until its quota resets; it must not trigger a rapid
   request storm against another provider.
8. Every provider must have documented coverage, quota, freshness, attribution,
   and data-use/redistribution terms before being enabled for production.

## Initial provider constraints

football-data.org currently lists the English Premier League in its free
coverage. The free plan advertises delayed scores, fixtures, schedules and
league tables, with a limit of 10 requests per minute. Authenticated access
requires an API token. Visible attribution is required. Live scores and deeper
match statistics are not included in the free plan.

The project must not assume live-score availability or redistribute provider
data beyond the rights granted by the provider's current terms. The owner must
configure the token locally through environment variables; secrets must never
be committed to Git or pasted into chat.

## Consequences

- A second provider can be added without changing canonical sports models or
  ingestion service contracts.
- Routes can be changed independently for each competition.
- Different providers can be assigned to different competitions or ordered as
  qualified alternatives.
- Automatic failover remains a later, explicit policy built on top of coverage
  metadata, provider health, quota state, and idempotent ingestion.
- Provider selection and data freshness should be visible in operational logs
  and eventually API metadata.

## References

- https://www.football-data.org/coverage
- https://www.football-data.org/pricing
- https://www.football-data.org/documentation/faq
- https://docs.football-data.org/general/v4/policies.html
