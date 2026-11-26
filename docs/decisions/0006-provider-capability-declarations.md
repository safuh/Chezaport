# ADR 0006: Explicit provider capability declarations

- Status: Accepted
- Date: 2026-11-10

## Context

A competition route is only a priority list. It does not prove that every
candidate supplies every resource for that competition. Providers can have
different competition coverage and may expose fixtures without standings,
teams without player profiles, or delayed data without live updates. Selecting
a provider solely because it appears in a route can therefore produce
unsupported requests or unsafe fallback behavior.

## Decision

1. Every `SportsDataProvider` declares immutable `ProviderCapabilities`.
2. Capabilities enumerate canonical competition codes and normalized resource
   families: competitions, seasons, teams, and fixtures.
3. `SportsProviderRegistry.providers_for_competition` can filter the ordered
   candidates by an exact resource request.
4. A provider is eligible only when it explicitly declares both the competition
   and resource. Missing coverage is not interpreted as universal support.
5. The registry continues to return candidates only. It does not make HTTP
   requests, select a provider based on health, or perform automatic failover.
6. Freshness, field-level availability, quotas, attribution, and legal
   permissions remain provider-specific metadata and must be documented before
   enabling a provider for production.

## Consequences

- Provider coverage can be tested without credentials or network access.
- Resource-specific routing can avoid sending requests to a provider that does
  not declare support.
- A future adapter must publish its supported canonical competition codes and
  resource families as part of its implementation.
- This declaration is intentionally coarse-grained. It does not imply that all
  fields within a resource are available, nor that data is live or redistributable.
