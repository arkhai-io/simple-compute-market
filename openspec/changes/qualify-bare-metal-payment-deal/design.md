# Design

## Decisions

Reuse the bare-metal driver for backed whole-machine seeding and mock access semantics. A pool override supplies one hourly USD/6 option without changing other pools. Keep control-flow tests distinct from the canonical Alkahest stages.

Use the shared payment serializer under `bare_metal.arkhai_payments`, pin false receipt mode, and generate only a public SSH key for configuration. Registry and seller responses verify against lane-owned pins.

Replay reads validated original-run references and resolves the run-recorded profile/principal through `BuyerProfileService`. It calls `SyncStorefrontClient.settle_agreement`; it neither buys again nor invents a settle CLI. All fulfillment reads and teardown sign as that purchase buyer.

Financial refund calls the actual pinned seller and checks the payer snapshot. Physical teardown separately follows mock reclaim, lease release callback and whole-host capacity return. Finalizers resume held loops and remove owned rules.

## Alternatives

The ordinary lane buyer fixtures use a different signer and cannot read this purchase. Shared Alkahest stages bind escrow semantics and cannot represent a payment purchase. Real SSH belongs to the protected lane.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Three-call payment and physical release contract | `openspec/specs/test-compatibility/spec.md#scenario-bare-metal-payment-purchase-is-qualified` |
| Bare-metal lane payment scenario map | `docs/development/TESTING.md#4-system-integration-tests-end-to-end` |
| Configuration and first-use entry point | `e2e-tests/README.md#bare-metal-payment-deal` |

No repository-wide architectural change or roadmap-goal state change: this qualifies existing fixed-term behavior, not the spot roadmap. The focused campaign index records this scenario separately.
