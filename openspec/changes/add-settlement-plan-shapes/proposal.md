## Why

Settlement carriers and seller-side condition/collection persistence support multiple obligations structurally, but materialization and claim construction still use one buyer-funded escrow and reclaim is buyer-driven. Generic obligation lifecycle and concrete interval/bond policies can proceed together; heartbeat arbitration and automated oracle operation require separate unresolved authority decisions.

## What Changes

- Add durable idempotent materialize/check/collect/reclaim lifecycle for every obligation and both payer directions.
- Materialize and service deterministic interval escrows and seller-funded penalty bonds as independent obligations.
- Remove single-`obligations[0]` assumptions from seller claim construction.
- Retain trusted-oracle hooks/manual operation as baseline but defer heartbeat-gated adjudication and an automated oracle service until neutral authority/evidence design is selected.
- State: **Retained but narrowed to generic obligation lifecycle plus interval/bond policy.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `settlement-servicing`: Service every plan obligation independently with durable lifecycle and support deterministic interval escrow and penalty-bond policies.

## Dependencies and Related Changes

- Uses current N-obligation settlement carriers and seller-side servicing engine.
- `automate-seller-spot` may consume split/servicing behavior but has its own interruption boundary.
- Heartbeat arbitration and automated oracle operation require future focused changes after authority decisions.

## Non-Goals

- Do not bundle heartbeat adjudication or a deployable automated oracle into this acceptance boundary.
- Do not add a fiat codec without a committed provider/customer pairing.
- Do not assume the first obligation represents the entire plan.

## Impact

Touches shared settlement plans, Alkahest materialization/claims, storefront servicing persistence/workers, buyer reclaim compatibility, migrations, and multi-obligation lifecycle tests.
