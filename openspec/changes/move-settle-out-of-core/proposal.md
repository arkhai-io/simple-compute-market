## Why

Settle runs after the agreement is committed, so under `agreed-evidence-and-early-termination` D1 it is post-commitment lifecycle, not protocol. Its contract is still core's: the route table `storefront_client.settlement_routes` (`SETTLE` in its negotiation and Alkahest `escrow_uid` forms, `SETTLE_STATUS`, `REFUND`), its response models, and the typed-client method `settle_agreement`. The VM, bare-metal and API-credit storefronts each mount it, and VM seller response signing binds it. After that change lands, the same handoff exists twice: the settle route and the lifecycle `commit` message.

## What Changes

- The settle, settlement-status and refund routes retire in favour of the lifecycle routes: `commit` on the buyer lifecycle route, `read` for status, and the `reverse` command for refunds.
- The route table, response models and `settle_agreement` leave core's storefront client.
- API credits gains a lifecycle binding with explicit refusal of the event kinds it does not support.
- The Alkahest `escrow_uid` settle form moves to an Alkahest-owned route contributed by its stage.
- VM seller response signing binds the lifecycle routes instead.

## Capabilities

### Modified Capabilities

- `buyer-orchestration`: the typed client's settle methods are replaced by the lifecycle client.
- `market-composition`: the settle stage is the lifecycle `commit` handoff.
- `settlement-servicing`: the shared settlement route contract is removed.

## Non-Goals

- New lifecycle behaviour; this change only moves callers onto the lifecycle routes.

## Dependencies

- `agreed-evidence-and-early-termination`: the lifecycle routes and client.
- `move-escrow-into-alkahest`: Alkahest must own its escrow-shaped settle path before it moves. `drop-escrow-from-shared-wire` also touches the `escrow_uid` routes; whichever lands second follows the first.

## Compatibility

This breaks the settle wire contract. There is no backwards-compatibility promise; storefronts and buyer clients upgrade together.
