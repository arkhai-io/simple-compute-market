## REMOVED Requirements

### Requirement: Protected steps are authorized and admitted

**Reason**: Its `rate_servicing_unavailable` refusal and the scenario of a rate deal refused at commit end with this change: end service no longer refuses to commit a rate deal.

**Migration**: "Protected delivery steps are authorized and admitted" keeps every other rule and scenario, maps every refusal when no end is due to `repair_required(no_accepted_deal)`, and adds the changed-answer scenario. The `rate_servicing_unavailable` repair reason goes; no released storefront reported it (`marketplace-v0.3.0`).

## ADDED Requirements

### Requirement: Protected delivery steps are authorized and admitted

Before commit, dispatch, billing start and disclosure the path MUST call end service's `authorize_delivery` for that phase, and before activation it MUST pass end service's admission for `activate`. A pending or unknown outcome MUST leave the deal pending and resolve the same attempt; a financial allow MUST NOT override a due local end; a mechanism with no adapter MUST NOT be allowed. Any refusal when no end is due MUST be `repair_required(no_accepted_deal)`.

#### Scenario: An end wins before dispatch

- **WHEN** an end is recorded after the dispatch authorization was read but before dispatch
- **THEN** the stale admission fails, nothing is dispatched, and the deal goes to the end hand-off

#### Scenario: An authorization outcome is unknown

- **WHEN** the payment adapter cannot establish its authorization outcome
- **THEN** the deal stays pending and the next drive resolves the same authorization

#### Scenario: A rate deal's changed answer leaves it pending

- **WHEN** end service answers `pending` because the payment authority's answer to an already journaled phase changed at the same revision
- **THEN** `drive` returns pending with nothing further done, and a later drive asks again

### Requirement: Unfinished deliveries are re-driven by one routine

The compute delivery package MUST provide one routine that re-drives unfinished deliveries, and each compute storefront's `delivery-recovery` loop MUST run it over its domain's ports: the domain lists its unfinished deliveries, claims each one under its own serialization, and has the deal's settlement stage re-check its evidence before the routine drives it. A deal the domain cannot claim, or whose evidence does not re-check, MUST NOT be driven in that pass.

#### Scenario: A delivery waiting for its start is re-driven

- **GIVEN** a VM deal and a bare-metal deal each committed and waiting for their Agreement start
- **WHEN** each storefront's `delivery-recovery` loop runs at the start
- **THEN** each claims the deal, re-checks its settlement evidence and drives it through the delivery path

#### Scenario: A deal another worker holds is skipped

- **WHEN** the domain cannot claim an unfinished delivery because another worker holds it
- **THEN** the routine does not drive it in that pass
