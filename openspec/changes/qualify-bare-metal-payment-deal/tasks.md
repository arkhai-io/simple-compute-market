# Tasks

- [x] Add the three-call bare-metal payment scenario and module-owned supply/cleanup.
- [x] Register/include its marker without removing the canonical mock deal.
- [x] Document current scenario contract in test-compatibility, testing map and E2E guide.
- [x] Collect the exact three calls and run relevant scenario/CLI typing.
- [x] Run the connected scenario against a ready configured payments target.

## Closeout

- [x] Comment hygiene: `make check-comment-hygiene`.
- [x] Import placement: all added imports are module-level.
- [x] Documentation compliance: decisions promoted to owning permanent documents.
- [x] Narrative compression: retain final contract and check outcomes only.
- [x] Roadmap currency: no directional-goal or production-behavior change.
- [x] Campaign index currency: focused candidate qualification row added.
- [x] Documentation citations: `make check-doc-citations CHANGE=qualify-bare-metal-payment-deal`.
- [x] Packaging: `make check-packaging`.
- [x] End-to-end pipeline evidence: configured three-call scenario passed (3 passed, 0 skipped); public CI without payments remains explicitly blocked.
- [x] Promotion: design record names guide, testing map and permanent spec.

## Validation

At `430213a40eff4d661f5275267e990d7ad4b84ce4`, the configured payment scenario passed all three calls in 47.9 seconds with mock provisioning: receipt-gated access/result, original-run settlement and fulfillment replay, seller refund, separate reclaim and whole-host capacity return. The initial connected attempt exposed run completion treating opaque dictionary provision terms as a model; completion now uses the negotiation outcome's existing serializer. Command interfaces and settlement design are unchanged.

Exact collection, focused scenario typing, comment hygiene, scoped citations and packaging passed. CLI typing additionally required retaining already-validated seller pins in callbacks and asserting delivery's existing non-null sink boundary.
