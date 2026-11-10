# ADR 0004: European pilot data provider

- Status: Proposed; awaiting owner approval and credential setup
- Date: 2026-11-10

## Context

Chezaport needs a first European football competition for end-to-end ingestion. The provider must fit the free-first policy, expose fixtures and results, and map into the existing provider-neutral schemas.

## Candidate: football-data.org

Official sources reviewed:

- Coverage: https://www.football-data.org/coverage
- Pricing: https://www.football-data.org/pricing
- API documentation: https://www.football-data.org/documentation/api
- Terms: https://www.football-data.org/about
- Attribution FAQ: https://www.football-data.org/documentation/faq

The current free tier lists 12 competitions, including the Premier League, Bundesliga, La Liga, Serie A, Ligue 1, Eredivisie, Primeira Liga, Champions League and European Championship. The free tier provides fixtures, schedules and tables, but scores/schedules are delayed; live scores and deeper match data require paid plans. The documented free limit is 10 requests per minute.

Access to competition data requires registration and an API token. Unauthenticated access is limited to area and competition-list resources. The provider requires visible attribution: "Football data provided by the Football-Data.org API".

The published terms are dated 1 June 2018. They state that an API key applies to a single application, prohibit storing developer credentials in public open-source repositories, and say that after subscription cancellation the customer may no longer reference data obtained through the API on their own service. The terms do not clearly settle the intended commercial redistribution and long-term retention model for Chezaport. Team logos and profile images are separately copyrighted and require permission from their owners.

## Decision

Recommend a limited technical pilot with the Bundesliga (competition code `BL1`) using the free tier, subject to explicit owner approval and clarification of data-use rights for Chezaport's intended public/commercial use.

Do not add a provider dependency or make authenticated requests until the owner has approved the provider and configured a token locally. Never commit tokens to source control. Tests and CI must use mocked HTTP responses and must not require the live token.

## Consequences

- No paid plan is required for the initial fixtures/results/table pilot.
- Data freshness is unsuitable for a live-score product; the UI must disclose delay.
- The provider adapter must honor the 10 requests/minute limit and use bounded retries with Retry-After support.
- The application must display the required attribution.
- Logos and player photos are out of scope until their rights are independently established.
- A free token is still a credential and must be supplied through local environment configuration, not chat or a committed `.env`.
- If the provider does not confirm the required usage/redistribution rights, keep the adapter isolated and evaluate another source before production use.

## Owner action required

1. Approve or reject football-data.org as the technical pilot.
2. Before production data use, confirm the provider's terms permit Chezaport's intended use and redistribution.
3. If approved, create a free account and configure `FOOTBALL_DATA_API_TOKEN` in the local untracked `.env`. Do not paste the token into chat or commit it.
