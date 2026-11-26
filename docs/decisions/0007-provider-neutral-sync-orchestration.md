# ADR 0007: Provider-neutral synchronization orchestration

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

Chezaport has normalized provider contracts, explicit competition/resource
capabilities, bounded retry behavior, external-ID resolution, and transaction-
aware ingestion. These pieces need a small orchestration boundary that can
coordinate a fetch and an import without coupling the domain to a vendor SDK.

## Decision

- Add `SportsSyncService` as an application service over the existing provider
  registry, retry helper, and ingestion service.
- Competition discovery is invoked with an explicitly named provider because
  the canonical competition code is not known until discovery returns records.
- Season, team, and fixture synchronization resolve the ordered route candidates
  for the requested competition and resource, then select the first eligible
  candidate.
- The service does not automatically fail over. A selected provider's failure
  propagates to the caller; retry is limited to the existing typed transient
  provider failures.
- Return a structured report with provider, resource, competition scope,
  timestamps, fetched count, and the existing per-record ingestion outcomes.
- The caller supplies the `AsyncSession` and owns its transaction. The service
  never commits, rolls back, or creates sessions.
- Keep scheduling and CLI integration separate. No queue, broker, Redis,
  provider credentials, HTTP client, or network call is introduced here.

## Consequences

The orchestration can be tested deterministically with stub providers and
SQLite. Callers can inspect failed record outcomes before deciding whether to
commit or roll back. Provider-level errors remain visible to the caller rather
than being hidden by automatic failover. Competition discovery must name the
provider explicitly; subsequent resource synchronization uses configured
competition routes.
