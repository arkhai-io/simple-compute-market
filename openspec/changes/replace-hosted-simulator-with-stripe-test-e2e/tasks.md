## 1. Checkpoint and supersession boundary

- [x] 1.1 Recorded clean marketplace checkpoints `c128b902` and `81c8e47a`, hosted implementation checkpoints `f46ca41` and `d4fd002`, and hosted replacement-plan commit `03cf2e2` in `design.md`; both worktrees began the cutover clean.
- [x] 1.2 Amended `add-local-hosted-settlement-e2e/{proposal,design,tasks}.md` without rewriting completed history: hermetic task 6.3 and simulator closeout 7.6 remain explicitly incomplete/superseded, available Stripe evidence is preserved, and replacement ownership is recorded.
- [x] 1.3 Created and strictly validated hosted companion change `replace-e2e-simulator-with-scripted-provider-tests`; it owns provider-port recovery coverage, producer simulator removal, production-only release verification, permanent hosted documentation, and exact consumer handoff.

## 2. Hosted producer recovery and release prerequisite

- [x] 2.1 In the companion hosted change, inventory simulator cases by Arkhai-owned invariant versus claimed provider behavior; map timeout placement, unknown acknowledgement, delayed visibility, provider unavailability, exact-attempt failure, event duplication/order, journal recovery, and idempotency to the internal financial-provider and webhook-inbox integration boundaries.
- [x] 2.2 Implement a minimal in-process scripted financial-provider collaborator in the hosted producer tests that returns typed provider-interface outcomes without HTTP, Stripe-shaped models, provider credentials, public controls, or production packaging; prove immutable request fingerprints and deterministic attempt scripts.
- [x] 2.3 Port simulator recovery cases to the ordinary production operation journal, leases, retry policy, reconciliation worker, webhook inbox, and lifecycle code; assert Arkhai states/effects only and rename evidence so no scripted outcome is presented as Stripe behavior.
- [x] 2.4 Add or retain focused Stripe adapter tests at the SDK boundary for request construction and response/error normalization, then run the hosted producer's credential-free unit/integration, typing, package-content, forbidden-import, and comment-hygiene suites.
- [ ] 2.5 Produce and verify an ordinary signed hosted production release containing no fixture distribution, simulator/control/clock entry point, protocol, migration, manifest, capability, dependency, or image layer; record exact manifest, client wheel, service image, migration, OpenAPI/conformance, provenance, and source identities for consumer pinning.

## 3. Protected Stripe preflight and lifecycle driver

- [x] 3.1 Consolidate `e2e-tests/src/hosted_real_stripe/` into the canonical protected `stripe-test` lane while retaining gates, runtime, browser, lifecycle bridge, Stripe inspection, and schema-validated evidence; remove naming and branches whose only purpose was distinguishing the retired simulator.
- [x] 3.2 Harden preflight to verify the exact marketplace commit and signed production hosted release/client/image, `sk_test` mode and non-live returned objects, Stripe API connectivity, allowlisted connected-account ownership/readiness/capabilities, loopback-only webhook mapping, and Chromium availability before publication or financial mutation; cover every rejected prerequisite.
- [x] 3.3 Drive publication, registry discovery, negotiation, exact `fiat.stripe.v1` selection, materialization, and buyer action through ordinary marketplace clients; remove any authority-only shortcut that bypasses a marketplace boundary claimed by system evidence and assert wallet/chain/RPC absence.
- [x] 3.4 Drive real Checkout in Chromium with official Stripe test inputs, capture no action URL in run logs/evidence, forward the real signed event through Stripe CLI, and wait on named authority/marketplace state with bounded observable polling rather than fixed sleeps.
- [x] 3.5 Complete VM fulfillment and portable condition evidence through ordinary marketplace paths, allow the ordinary hosted worker to collect, and inspect exact Checkout, PaymentIntent/charge, transfer, connected destination, amount/currency, transfer group, source transaction, operation metadata, and one-effect cardinality through Stripe retrieval APIs.
- [x] 3.6 Run an isolated paid-but-unfulfilled obligation through eligible pre-transfer reclaim, assert one related Stripe refund and no transfer, repeat recovery under the original operation identity, and provide bounded cleanup/recovery instructions for externally interrupted runs.

## 4. Real restart, omission, and provider outcome scenarios

- [x] 4.1 Add a missed-webhook scenario that pauses Stripe CLI forwarding, completes real Checkout, restarts forwarding and the ordinary worker against preserved authority state, and proves authoritative Stripe retrieval converges without recreating Checkout/payment or duplicating a terminal effect.
- [x] 4.2 Add API and worker restart scenarios after accepted materialization and before collection/reclaim; preserve the digest-pinned production image and authority volume, resume through the original marketplace operation identity, and prove exactly one transfer or refund.
- [x] 4.3 Add Stripe-supported payment-outcome cases for documented success, decline/insufficient funds, and authentication/3DS behavior at the lowest browser/system level that observes the real contract; do not emulate unsupported arbitrary provider transitions or use `stripe trigger` as a substitute for marketplace-created object behavior.
- [x] 4.4 Keep Connect onboarding as a separate manual/scheduled browser smoke while validating the maintained connected account on every transaction run; document account rotation/readiness recovery without exposing Account Link URLs or provider/customer details.

## 5. Evidence, isolation, and failure attribution

- [x] 5.1 Update the protected evidence model/schema to classify `product`, `account`, `environment`, and `timeout` outcomes; include only exact consumer/release identities, scenario/stage, opaque operation identity, normalized state/amount/currency/cardinality, and bounded diagnostics, and reject secrets, action URLs, customer/card data, raw webhooks, and unrestricted provider payloads.
- [x] 5.2 Derive unique per-run marketplace/Stripe metadata and stable idempotency keys from durable operation identities; retrieve exact related objects rather than latest-account results and prove concurrent or prior test objects cannot satisfy assertions.
- [x] 5.3 Restrict retries to preflight/read-only polling and production mutations under the original durable idempotency identity; add tests that the harness never reissues a financial mutation directly under a new identity and never converts an environment/account failure into success.
- [x] 5.4 Add allowlist/redaction tests for process output, uploaded artifacts, reports, exception paths, and interrupted cleanup; verify protected credentials are delivered only to their consuming roles and destroyed after every workflow outcome.

## 6. Remove marketplace simulator surfaces

- [x] 6.1 Simplify `scripts/verify-hosted-release.py`, `scripts/prepare-hosted-compose.py`, root/e2e Make targets, and focused script tests to accept only the ordinary signed production hosted release for financial E2E; remove E2E manifest, fixture wheel/image, control schema/protocol/capability, simulator migration, and local private-image branches.
- [x] 6.2 Remove simulator/control/clock/event-worker services, networks, volumes, health gates, credentials, and hermetic/local-EAS hosted profiles from `compose.hosted-settlement.yml` and related configuration fixtures; retain ordinary migration/API/worker, authority persistence, Stripe webhook mapping, storefront composition, and independent local EAS condition conformance.
- [x] 6.3 Remove marketplace simulator scenario drivers/state/evidence, private control clients and tests, simulator restart controls, fixture package/review-wheelhouse scope, and private acquisition instructions; preserve marketplace lifecycle, Stripe driver, production release verification, and generic restart helpers that remain used.
- [x] 6.4 For every file requiring deletion, present the repository-required single-line tombstone at its original path during review, then remove accepted tombstones before final production validation; add active-surface scans proving no simulator fixture distribution, image, manifest, protocol, control, clock, store, event worker, target, or import remains outside archived change history.

## 7. Public and protected workflow boundaries

- [x] 7.1 Update `.github/workflows/hosted-real-stripe.yml` into the canonical protected Stripe test-mode workflow: trusted exact commits only, least-privilege credentials, production hosted release verification, ready account, Stripe CLI forwarding, Chromium, serialized/isolated identities, sanitized uploads, and cleanup on every result.
- [ ] 7.2 Keep default/fork CI credential-free and independent of private hosted source or Stripe inputs; run public client conformance, marketplace hosted orchestration with injected public-client results, packaging/configuration/release-verifier checks, and existing Alkahest/local-EAS suites without collecting or skipping protected tests.
- [x] 7.3 Add workflow and target tests proving explicit protected invocation fails before mutation with the exact missing credential, network, account, webhook, browser, or release prerequisite and that default public entry points never probe for them.
- [x] 7.4 Define trusted-change and scheduled-drift triggers for protected Stripe acceptance across hosted client/adapter, settlement runtime, storefront/buyer hosted flow, authority lifecycle/provider code, and harness changes; report external/account unavailability distinctly without weakening required product assertions.

## 8. Cross-repository and installed-artifact verification

- [ ] 8.1 Build the marketplace review wheelhouse and affected buyer/storefront/E2E images from staged wheels pinned to the production hosted release; inspect package contents and lock/provenance manifests to prove no sibling editable source or simulator fixture remains.
- [ ] 8.2 Run focused unit, integration, typing, config, Compose/render, package-boundary, secret-canary, and CLI/entry-point checks for every touched marketplace package and the companion hosted producer change; resolve failures rather than narrowing the claimed removal boundary.
- [ ] 8.3 Run installed-artifact smoke for production hosted migration/API/worker readiness, marketplace storefront/buyer composition, Stripe webhook loopback mapping, and restart-preserved authority state using exact digest-pinned images and staged wheels.
- [ ] 8.4 Run protected Stripe collection, reclaim/refund, missed-webhook retrieval, API restart, worker restart, and supported payment-outcome scenarios; record exact consumer commit, hosted production manifest/client/image/source identities and disclose any genuinely external unavailable scenario without substituting focused tests as provider evidence.
- [ ] 8.5 Run existing Alkahest E2E unchanged and local EAS/allowlisted-arbiter condition conformance independently; prove neither starts Stripe nor a simulator and neither is used to claim hosted financial behavior.

## 9. Permanent documentation and change disposition

- [x] 9.1 Synchronize the verified deltas into `openspec/specs/test-compatibility/{spec,architecture}.md` and `deployment-state/{spec,architecture}.md`, removing the hermetic/private-simulator evidence model and recording Stripe-only provider acceptance, provider-port deterministic recovery, production-release-only composition, protected/public boundaries, and failure attribution as current behavior.
- [x] 9.2 Update `docs/development/TESTING.md`, `DEPLOYMENT_AND_CONFIG.md`, and `ARCHITECTURE.md` to remove simulator topology/artifact/profile instructions and document the protected Stripe lane, credential-free focused coverage, producer/consumer release boundary, prerequisites, secret isolation, and recovery ownership without change-history prose.
- [x] 9.3 Update the hosted role runbook, developer commands, configuration examples, and workflow/operator references to use the production-release Stripe test target and independent local EAS/Alkahest commands; remove stale hermetic, simulator, control, and private E2E artifact instructions.
- [ ] 9.4 Complete the companion hosted producer's permanent spec/architecture/testing/deployment promotion and archive/disposition its simulator change only after scripted-provider integration and production-only release evidence pass; record the exact permanent destinations and producer release in this change.

## 10. Final validation and closeout

- [ ] 10.1 Run focused strict validation for this change, the superseded `add-local-hosted-settlement-e2e` disposition, and the companion hosted change, then repository-wide strict OpenSpec validation and repository-wide checks; report unrelated active-change failures separately.
- [ ] 10.2 Complete plan closeout: run `make check-comment-hygiene` and directly remove temporary change/review/migration narrative from touched production comments/docstrings; review every local import added or touched and move it to module scope unless a reproduced cycle or documented deliberate lazy-load requirement proves otherwise, then rerun owning tests; audit accepted decisions against permanent-document placement; compress completed task notes to final behavior, material evidence, unresolved external work, and permanent destinations; update `docs/development/ROADMAP.md` only if the product goal mapping changed and otherwise record no roadmap impact; and complete this change's design-promotion record with exact consumer/producer release identities and validation evidence.
- [ ] 10.3 Confirm no active simulator surface or review tombstone remains, all accepted financial test objects are terminal/recoverable under their original identities, protected reports are sanitized, public/fork checks remain credential-free, the old change records its superseded disposition, and the replacement change is ready for code review and synchronization/archive.
