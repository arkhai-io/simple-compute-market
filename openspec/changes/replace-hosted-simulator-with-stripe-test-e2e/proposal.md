## Why

Hosted settlement E2E currently duplicates part of Stripe's financial behavior in a private durable simulator, creating a second provider implementation whose fidelity and lifecycle must be maintained. Hosted settlement may require Stripe connectivity and protected test credentials for system acceptance; Stripe behavior should therefore be proven only against Stripe test mode, while deterministic failures owned by Arkhai should be tested below E2E through the hosted service's internal provider interface.

## What Changes

- Replace the hermetic simulator and separate real-provider lanes with one protected Stripe test-mode system E2E lane using the ordinary signed production hosted release, Stripe CLI webhook forwarding, browser-driven Checkout, a ready Connect test account, and authoritative Stripe API inspection.
- Keep marketplace ownership of the cross-service publication, discovery, negotiation, materialization, funding, fulfillment, collection, reclaim, restart, and recovery scenarios; continue consuming hosted implementation only through signed release artifacts and public network/client contracts.
- Move deterministic timeout, unknown-acknowledgement, delayed-visibility, provider-unavailability, exact-attempt failure, and arbitrary event-order cases to hosted-service integration tests at the internal financial-provider port. These tests specify provider outcomes and assert Arkhai operation-journal/reconciliation behavior without implementing or claiming Stripe semantics.
- Use Stripe-supported test cards and provider behavior for successful payment, decline, insufficient funds, authentication/3DS, Checkout completion, signed webhook delivery, destination transfer, and eligible refund evidence.
- Retain real restart/reconciliation E2E cases that can be arranged without imitating Stripe: pause webhook forwarding or workers, complete real Checkout, restart ordinary processes with durable authority state, retrieve authoritative Stripe state, and prove exactly-once transfer/refund outcomes using stable idempotency identities.
- **BREAKING:** remove the private E2E fixture wheel, simulator/control images and manifests, provider/control protocols and credentials, simulator and controlled-clock stores, synthetic event worker, hermetic/local-EAS simulator profiles, and their artifact acquisition/preflight/reporting surfaces from marketplace testing and deployment.
- Preserve local EAS/arbiter conformance as an independent condition-boundary test that does not require or simulate hosted finance. Preserve existing Alkahest E2E unchanged.
- Make the Stripe system lane protected and explicitly selected: public/fork/default CI remains credential-free and runs provider-port integration, adapter, packaging, and marketplace orchestration tests without pretending to complete hosted financial E2E.
- Classify protected-lane outcomes as product failure, test-account/readiness failure, external environment failure, or convergence timeout. Network or credential absence is reported as an unmet acceptance prerequisite, not replaced by simulator evidence or silently skipped after explicit selection.
- Retire already-created simulator artifacts through coordinated marketplace and hosted-service changes; preserve completed implementation history in the superseded changes rather than rewriting it as though the simulator had never existed.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `test-compatibility`: Hosted system acceptance uses Stripe test mode exclusively for provider behavior, assigns deterministic Arkhai recovery cases to provider-port integration tests, and defines protected/public evidence boundaries and failure attribution.
- `deployment-state`: Optional hosted test composition consumes only the signed production hosted release and protected Stripe test inputs; simulator artifacts, controls, stores, credentials, and profiles are prohibited and removed.

## Impact

- Marketplace E2E implementation and workflows: `e2e-tests`, root/e2e Make targets, `compose.hosted-settlement.yml`, `.github/workflows/hosted-real-stripe.yml`, hosted role fixtures/runbooks, evidence schema, and focused tests.
- Release verification and packaging: `scripts/verify-hosted-release.py`, hosted Compose preparation/contract tests, review-wheelhouse scope, and any E2E fixture artifact acquisition logic.
- Permanent testing/deployment documentation: `openspec/specs/test-compatibility`, `openspec/specs/deployment-state`, `docs/development/{TESTING,DEPLOYMENT_AND_CONFIG,ARCHITECTURE}.md`.
- Independently operated hosted repository: requires a companion change to retain production provider-interface integration coverage while deleting the private E2E simulator distribution, image, manifest/workflow, controls, protocols, stores, Compose topology, and simulator-specific documentation. This repository does not import or directly modify that implementation.
- No marketplace wire, accepted-plan, settlement database, provider custody, production activation, or customer-facing settlement behavior changes.
- Protected CI now requires Stripe network access, test credentials, webhook forwarding, and a ready connected account for hosted system acceptance. Forks and public contributors cannot run the full hosted financial E2E lane.

## Permanent documentation impact

- [x] `openspec/specs/test-compatibility/{spec,architecture}.md` — record Stripe-only system evidence and provider-port deterministic recovery ownership.
- [x] `openspec/specs/deployment-state/{spec,architecture}.md` — record production-release-only test composition, secret isolation, and removed simulator surfaces.
- [x] `docs/development/TESTING.md` — replace the hermetic/real-provider split with focused provider-port integration plus protected Stripe E2E.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md` — remove simulator artifact/profile instructions and document protected Stripe prerequisites and failure classes.
- [x] `docs/development/ARCHITECTURE.md` — remove the private simulator topology while retaining hosted authority/provider separation.
- [ ] No permanent documentation change.

### Knowledge to promote

- Stripe behavior is asserted only against Stripe test mode; local/provider-port fakes assert only Arkhai behavior under declared collaborator outcomes — `openspec/specs/test-compatibility/{spec,architecture}.md` and `docs/development/TESTING.md`.
- Hosted system E2E uses the ordinary signed production authority release with real Checkout, signed webhook forwarding, Connect readiness, retrieval, transfer, and refund — `openspec/specs/{test-compatibility,deployment-state}/{spec,architecture}.md`.
- Public/fork CI remains credential-free; explicit protected execution fails on missing external prerequisites and classifies infrastructure separately from product failures — `openspec/specs/test-compatibility/spec.md` and `docs/development/{TESTING,DEPLOYMENT_AND_CONFIG}.md`.
- Simulator distributions, manifests, protocols, controls, volumes, and profiles are not supported deployment or test surfaces — `openspec/specs/deployment-state/{spec,architecture}.md` and `docs/development/ARCHITECTURE.md`.

## Dependencies and Related Changes

- Supersedes the simulator-specific acceptance strategy in active marketplace change `add-local-hosted-settlement-e2e`. That change's completed implementation history remains intact; its remaining simulator validation/closeout work is stopped and its final disposition points to this change.
- Requires a companion planning change in the independently operated hosted-settlement repository before implementation removes its simulator artifacts. The companion change must preserve deterministic operation-journal/reconciliation coverage at the internal provider interface and production Stripe adapter coverage.
- Reuses completed real Stripe driver, workflow, evidence, browser, Connect readiness, provider inspection, and release-verification work where it already matches this contract.
- Does not depend on Stripe Billing test clocks; hosted Checkout/Connect/transfer/refund scenarios use only supported test-mode behavior and bounded observable waits.
