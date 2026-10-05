## Why

Domains choose their settlement path by comparing mechanism IDs where they happen to need to. About 50 comparisons across 28 files in buyer CLIs, storefront controllers, negotiation runtimes, fulfillment planners and the API-credits service check `== ARKHAI_PAYMENTS_MECHANISM` or `== "alkahest.v1"`. Core buyer orchestration branches on whether an `accepted_escrow_proposal` exists: escrow means Alkahest or contact exchange, anything else falls through to the domain's `agreement_settlement` hook. Bare metal stores Arkhai payment evidence in its `escrows` table, marking the row with `chain_name == "arkhai.payments.v1"` and putting the transaction ID in `escrow_uid`.

This conflicts with the pipeline decision from `settle-through-arkhai-payments`: each stage consumes its predecessor's output, and compatibility between domain and mechanism is explicit per domain. Explicit should mean declared once. Today it is scattered, so adding a mechanism means finding every comparison, and porting the stack means reproducing incidental control flow rather than a declared table.

## What Changes

- Each domain declares, per role, one table from mechanism ID to a domain-owned settle stage, built from that mechanism kit's own API. This table is the only place a domain names a mechanism. A domain publishes options only for mechanisms that have a stage, so an unsupported selection is impossible rather than handled.
- Core buyer orchestration dispatches on the Agreement's `settlement.mechanism` through the domain table. It no longer has a branch for "has an escrow proposal or not". Until `move-escrow-into-alkahest` lands, the Alkahest stage reads its escrow proposal from the outcome itself.
- Settle stages produce domain settlement evidence keyed by negotiation ID: mechanism, settlement reference, status and mechanism-owned evidence. Stages after settlement (fulfillment planning, resume, credit issuance, the API-credits service) read that evidence and never compare mechanism IDs. Bare-metal and VM Arkhai evidence moves out of `escrows` rows.
- Seller settle routes dispatch the same way. `/api/v1/settle/{escrow_uid}` remains Alkahest's surface until `drop-escrow-from-shared-wire`.

## Capabilities

### Modified Capabilities

- `market-composition`: a domain composes one mechanism-to-stage table per role.
- `settlement-configuration`: registration remains the shared surface for publication, readiness and compatibility. Settling is not a registration hook.
- `buyer-orchestration`: dispatch on the Agreement's mechanism, with no escrow branch.
- `api-credits`, `vm-storefront-fulfillment`, `physical-provisioning`: domain evidence tables, and dispatch through the table.

## Non-Goals

- A shared settle interface that all mechanisms implement. Each stage is domain-owned and calls its kit's own API (see design).
- Moving escrow carriers, `ConditionalEscrowClient` or the servicing runtime. That is `move-escrow-into-alkahest`.
- Changing listing or registry wire formats. That is `drop-escrow-from-shared-wire`.

## Compatibility

There is no backwards-compatibility promise. Domain SQLite schemas are rebuilt by editing the migrations that introduce them, not by adding copy-then-drop migrations.
