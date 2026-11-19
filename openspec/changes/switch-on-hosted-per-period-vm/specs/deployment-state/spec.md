## ADDED Requirements

### Requirement: The VM storefront chart ships a production example offering on-demand and spot

The VM storefront chart MUST ship a production example values file whose agent settles
in `arkhai.payments.v1` in live mode, declares rate servicing for `charged` and
`returned` with no setup charge, and publishes an on-demand and a spot recurring clause
whose payments clause sets `delivery_deadline_seconds` and a dispute window covering
that deadline plus the authority's minimum filing window. The example MUST render, its
rendered storefront configuration MUST pass the storefront's startup check, and it MUST
set no injected time.

#### Scenario: The production example is rendered

- **WHEN** the chart render tests render the VM storefront chart with its production
  example
- **THEN** the render succeeds and the storefront's startup check accepts the rendered
  configuration

#### Scenario: The production example withdraws rate servicing

- **WHEN** an operator removes the example's `rate_servicing` table
- **THEN** the storefront publishes no recurring option and continues servicing the rate
  deals it already holds
