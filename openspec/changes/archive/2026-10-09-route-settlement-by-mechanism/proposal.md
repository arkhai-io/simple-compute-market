## Why

Domains choose their settlement path by comparing mechanism IDs where they happen to need to. 50 concrete-ID comparisons across 26 production files in buyer CLIs, storefront controllers, negotiation runtimes, fulfillment planners and the API-credits service check `== ARKHAI_PAYMENTS_MECHANISM` or `== "alkahest.v1"`. Core buyer orchestration branches on whether an `accepted_escrow_proposal` exists: escrow means Alkahest or contact exchange, anything else falls through to the domain's `agreement_settlement` hook. Bare metal has a dedicated payment-evidence table but still accepts legacy `escrows` rows marked with `chain_name == "arkhai.payments.v1"`; VM and API-credit payment delivery still use escrow-shaped progress rows.

This conflicts with the pipeline decision from `settle-through-arkhai-payments`: each stage consumes its predecessor's output, and compatibility between domain and mechanism is explicit per domain. Explicit should mean declared once. Today it is scattered, so adding a mechanism means finding every comparison, and porting the stack means reproducing incidental control flow rather than a declared table.

## What Changes

- Each domain declares, per role, one table from mechanism ID to a domain-owned settle stage, built from that mechanism kit's own API. This table is the only dispatch declaration; mechanism-specific validation stays inside its stage. A domain publishes options only for mechanisms that have a stage, so an unsupported selection is impossible rather than handled.
- Core buyer orchestration dispatches on the Agreement's `settlement.mechanism` through the domain table. It no longer has a branch for "has an escrow proposal or not". Until `move-escrow-into-alkahest` lands, the Alkahest stage reads its escrow proposal from the outcome itself.
- Settle stages produce domain settlement evidence keyed by negotiation ID: mechanism, settlement reference, status and mechanism-owned evidence. Stages after settlement (fulfillment planning, resume and credit issuance) read that evidence; the API-credits service reads only its issuance authorization. None compares mechanism IDs. Arkhai evidence and delivery progress use domain records rather than `escrows` rows.
- The credits service receives only the storefront's authenticated, immutable issuance authorization, never raw settlement evidence or a mechanism allowlist. Its grant identity derives uniformly from negotiation ID.
- An optional shared stage convention belongs in a kit, not core; its package is chosen when it is first implemented. Its adapters are deferred; this change does not require mechanisms to adopt it.
- Seller settle routes dispatch the same way. `/api/v1/settle/{escrow_uid}` remains Alkahest's surface until `drop-escrow-from-shared-wire`.

## Capabilities

### Modified Capabilities

- `market-composition`: a domain composes one mechanism-to-stage table per role.
- `settlement-configuration`: registration remains the shared surface for publication, readiness and compatibility. Settling is not a registration hook.
- `buyer-orchestration`: dispatch on the Agreement's mechanism, with no escrow branch.
- `api-credits`, `vm-storefront-fulfillment`, `physical-provisioning`: domain evidence tables, and dispatch through the table.
- `negotiation-protocol`: a fresh selection bargains its option's amount, and a plan the seller materializes from a selection is checked against the selected entry.

## Non-Goals

- A shared settle interface that all mechanisms implement. Each stage is domain-owned and calls its kit's own API (see design).
- Moving escrow carriers, `ConditionalEscrowClient` or the servicing runtime. That is `move-escrow-into-alkahest`.
- Changing listing or registry wire formats. That is `drop-escrow-from-shared-wire`.

## Compatibility

There is no backwards-compatibility promise. Domain SQLite schemas are rebuilt by editing the migrations that introduce them, not by adding copy-then-drop migrations. The credits issuance producer and consumer change together; old payloads and legacy grant adoption are not supported.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Core table/evidence ownership and unconstrained mechanism flow: `market-composition/spec.md`, its architecture companion, and repository composition/dependency-layer sections.
- Registration vs execution and supported-stage admission: `settlement-configuration/spec.md` and `architecture.md`.
- Agreement-based buyer dispatch and recovery: `buyer-orchestration/spec.md` and `architecture.md`.
- Domain evidence storage, delivery gating and restart continuity: `vm-storefront-fulfillment` and `physical-provisioning` specs and architecture companions.
- Storefront settlement authority and neutral credits issuance authorization: `api-credits/spec.md` and `architecture.md`.
- Optional convention ownership, with adapters explicitly deferred: `market-composition/architecture.md` and `settlement-configuration/architecture.md`.
- Goal 6 dispatch-gap currency at implementation completion: `docs/development/ROADMAP.md`. Exact promotion headings are recorded in `design.md`.
