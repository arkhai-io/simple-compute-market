## Context

The migrated proposal combined a diagnostic host-capacity check with authoritative candidate filtering and ranking. Current code has a one-host asynchronous diagnostic endpoint, while multidimensional admission belongs to the site-capacity ledger and concrete candidate selection belongs to `PhysicalSettlementScheduler`.

## Goals / Non-Goals

**Goals:**
- Record whether any coherent unimplemented acceptance boundary remains.
- Preserve the current authority split between diagnostics, admission, and scheduling.

**Non-Goals:**
- Add placement authority to a diagnostic endpoint.
- Duplicate POOLS admission or fulfillment scheduling.

## Decisions

### Reject the migrated change as superseded

The requested vCPU/RAM/GPU fit behavior now exists at the authoritative site-admission and fulfillment-scheduling layers. Returning ranked eligible hosts from the old diagnostic route would create a competing selection path without durable reservation or assignment semantics.

The active delta will not be synchronized. If operators later need read-only host search, a new change must define its caller, authoritative data source, ranking stability, and inability to reserve or assign capacity.

## Evidence

- One-host diagnostic: `HostController.check_capacity` and `HostOperationsService.check_capacity` in the compute provisioning service.
- Multidimensional admission: `kit/site/src/market_site/ledger.py`.
- Candidate fit and ordering: `kit/fulfillment/src/market_fulfillment/scheduling.py` and scheduler tests.
- Durable ownership: `openspec/specs/site-capacity/spec.md` and `openspec/specs/fulfillment/spec.md`.

## Risks / Trade-offs

- **[Operators still want ranked diagnostics]** → Capture a fresh read-only capability rather than reviving this authority-confused delta.

## Promotion Record

No requirement is promoted. Current permanent specifications already describe the accepted admission and scheduling authorities.
