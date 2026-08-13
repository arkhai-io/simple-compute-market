## Context

See `proposal.md` for motivation. The ongoing `add-local-hosted-settlement-e2e` work has already produced two substantial bodies of implementation: a private simulator-backed assembly and a protected real-Stripe driver. The simulator assembly adds a fixture wheel, image and signed manifest, provider/control/clock protocols, multiple durable stores, synthetic event delivery, Compose profiles, verification logic, and consumer scenario controls. Its remaining acceptance work is currently blocked at Compose health/orchestration despite the services returning ready responses.

The real-Stripe implementation already has fail-closed test-secret, connected-account, immutable-release, loopback-webhook, browser, provider-inspection, normalized-evidence, and marketplace lifecycle bridge components. Direct observed runs have exercised test-mode Account Links/readiness, Checkout, charge retrieval, destination transfer, and pre-transfer refund. This change promotes that lane to the only hosted financial system E2E and narrows local determinism to the hosted service's internal financial-provider contract.

The hosted authority is independently operated and released. This repository can remove consumer simulator surfaces and define the required producer contract, but simulator implementation deletion and provider-port test preservation require a companion change in that repository. Public/fork CI must remain credential-free; protected acceptance can assume Stripe connectivity and test credentials.

## Goals / Non-Goals

**Goals:**

- Assert every provider-specific behavior through Stripe test mode rather than a local behavioral replica.
- Exercise the full marketplace/authority boundary against the ordinary signed production hosted release.
- Preserve deterministic proof of Arkhai-owned uncertainty, retry, journal, inbox, and reconciliation semantics below system E2E.
- Reuse the existing protected Stripe driver and evidence structures instead of building a third harness.
- Remove all active simulator deployment, packaging, acquisition, secret, protocol, and documentation surfaces.
- Make external prerequisites and failure ownership explicit enough that protected CI failures are actionable.

**Non-Goals:**

- Make hosted financial E2E runnable by forks, offline, or without protected credentials.
- Use `stripe-mock`, replayed Stripe payloads, synthetic Stripe-compatible servers, or Stripe Billing test clocks as acceptance substitutes.
- Force Stripe to exhibit arbitrary timeout placement, acknowledgement loss, event ordering, or visibility delay.
- Weaken deterministic recovery coverage; it moves to the provider interface instead of disappearing.
- Change settlement wire formats, authority state semantics, marketplace identity, custody, production activation, or supported payment methods.
- Make Connect onboarding part of every transaction scenario; readiness and onboarding have distinct evidence cadence.
- Combine local EAS/arbiter condition conformance with financial-provider system acceptance.

## Decisions

### 1. Stop the simulator work now and supersede it with a new change

Do not complete the remaining simulator matrix before changing direction. No managed simulator validation job is currently running, and its remaining tasks validate an architecture this change retires. First preserve coherent reusable work in repository-owned commits, record which old tasks are superseded, and then implement this change.

Use a new change rather than rewriting `add-local-hosted-settlement-e2e` because that change has 31 completed tasks and material implementation history. The old change receives a final disposition pointing here; simulator-specific unchecked tasks are marked superseded rather than falsely completed. Reusable production-release, marketplace lifecycle, and Stripe work remains credited to the old change.

Alternative rejected: finish the simulator acceptance and then remove it. That would spend the highest-cost remaining work proving a surface with no intended lifetime and would increase the amount to delete.

### 2. One provider-authentic system lane

The protected lane composes the existing marketplace topology with the ordinary digest-pinned hosted production image and its normal migration, API, and reconciliation worker entry points. The authority uses Stripe test mode exactly as production uses Stripe, with test-only credentials and objects. Stripe CLI forwards real signed events to the loopback-only webhook mapping. Browser automation completes real Checkout. Provider inspection retrieves exact Stripe objects by identities and metadata derived from the accepted marketplace operation.

The lane does not use `stripe trigger` to pretend that marketplace-created resources changed state. `stripe trigger` may remain a diagnostic tool, but acceptance uses the objects created by the tested flow. Supported test payment methods/cards induce documented success, decline, insufficient-funds, and authentication outcomes.

Alternatives rejected:

- Keep hermetic and real lanes: retains two provider behavior implementations and ambiguous acceptance value.
- Use `stripe-mock`: it is stateless and explicitly does not reproduce Stripe behavior.
- Use only in-process hosted tests: misses image, migration, networking, signing, browser, webhook, worker, and marketplace composition boundaries.

### 3. Deterministic recovery belongs at the internal provider port

The hosted production runtime already composes a financial-provider interface. Integration tests inject a small scripted collaborator implementing that interface; they do not expose HTTP endpoints, Stripe-shaped objects, Checkout pages, webhooks, provider identifiers, or reusable simulation controls.

Each script describes only an interface outcome, for example:

- submit raises before recording any effect;
- submit records one effect then acknowledgement is unknown;
- retrieval returns not-found for bounded attempts then returns the effect;
- operation is retryably or terminally unavailable;
- a webhook inbox receives duplicate/out-of-order normalized events.

The assertions concern only production authority behavior: operation identity/fingerprint, journal state, lease/retry decisions, reconciliation convergence, inbox deduplication, and exactly-once calls at the provider port. Test names and reports say `scripted provider outcome`, never `Stripe timeout` or `Stripe event` unless actual Stripe evidence exists.

Adapter-focused tests separately verify Stripe SDK request/response/error normalization with mocks at the SDK call boundary. Protected E2E proves the adapter against real Stripe.

Alternative rejected: remove deterministic fault cases entirely. External Stripe cannot reliably furnish the failure boundaries needed to defend idempotency and uncertainty semantics.

### 4. Reuse and tighten the existing real-Stripe driver

Retain the current `e2e-tests/src/hosted_real_stripe` architecture: gates, runtime orchestration, browser driver, Stripe API inspection, lifecycle bridge, evidence model/schema, and top-level driver. Remove `real` from user-facing target/report names where it merely distinguishes the retired simulator; keep `stripe-test` explicit to prevent live-mode ambiguity.

The lifecycle bridge must drive ordinary marketplace paths, not direct authority-only shortcuts:

1. verify consumer commit and signed production hosted manifest/image/client identities;
2. preflight `sk_test` mode, API connectivity, allowlisted connected account ownership and capabilities, and loopback webhook mapping;
3. start migration/API/worker plus marketplace services;
4. publish and discover the `fiat.stripe.v1` option;
5. negotiate and materialize one accepted obligation;
6. open the returned Checkout action in Chromium and use an official test payment method;
7. wait for signed webhook ingestion and/or authoritative retrieval;
8. complete VM fulfillment and condition evidence;
9. observe collection and inspect exact Stripe effects;
10. run an isolated paid-but-unfulfilled obligation through eligible pre-transfer reclaim/refund.

The driver may call the authority's public API and Stripe inspection API, but it may not mutate marketplace or authority databases, fabricate webhook bodies, mark provider objects paid, or invoke private simulator controls.

### 5. Connected-account onboarding is periodic; readiness is per run

Ordinary protected E2E uses a long-lived, allowlisted, controller-compatible Stripe test connected account. Every run retrieves and validates its exact account identity, test mode, ownership binding, charge/transfer capabilities, and required readiness before marketplace publication. The account identifier is supplied only to the hosted authority/driver secret boundary and is not written into marketplace configuration or reports beyond an allowlisted fingerprint if needed.

A separate manual/scheduled onboarding smoke may create an Account Link and complete supported onboarding UI. It is not repeated for each transaction because KYC/account setup is account lifecycle, not transaction lifecycle, and repeated accounts increase brittleness and cleanup cost.

Alternative rejected: create/onboard a new connected account per transaction. It tests the wrong cadence and makes every purchase scenario depend on provider onboarding availability.

### 6. Restart/reconciliation E2E uses real omissions, not synthetic provider faults

Retain system recovery scenarios that can be arranged without imitating Stripe:

- stop webhook forwarding, complete Checkout, then restart forwarding/worker and recover by authoritative retrieval;
- stop the reconciliation worker before fulfillment becomes collectible, restart it with the same authority store, and observe one transfer;
- stop API or worker after an accepted obligation exists, restart without deleting the authority store, and resume through the same public operation identity;
- repeat collect/reclaim recovery calls under the original identity and prove one Stripe effect.

Do not claim the precise `accepted by Stripe but response lost` boundary at E2E. That remains a provider-port integration case. Process control must stop only ordinary authority/marketplace roles and preserve the same digest-pinned image and durable authority volume.

### 7. Mutation identity and inspection are exact

Every protected run creates a unique run/negotiation/obligation namespace and derives stable idempotency keys and Stripe metadata from durable marketplace operation identities. Inspection retrieves exact Checkout, PaymentIntent/charge, transfer, and refund relationships rather than selecting the latest account object.

Setup and read-only retrieval may retry with bounded exponential backoff. A financial mutation may be retried only through the production code under the original durable idempotency identity. The E2E driver never retries a failed mutation by issuing a new direct provider request or changing the operation identity.

The transfer assertion includes amount, currency, connected destination, transfer group, source transaction, operation metadata, and cardinality. Reclaim includes refund relation/cardinality and absence of transfer.

### 8. Failure classification is evidence, not retry policy

Use four terminal result classes:

- `product`: tested state, signature, amount, relation, cardinality, or transition is wrong;
- `account`: connected account identity/capability/readiness is unsuitable;
- `environment`: credentials, Stripe/CLI/browser/network/protected artifact access, or loopback forwarding is unavailable;
- `timeout`: prerequisites were valid but a named observable state did not converge within its bound.

Preflight account/environment failures occur before marketplace publication or provider mutation. After mutation begins, loss of connectivity remains an environment result but the report retains the opaque operation identity needed for authorized cleanup/recovery. Classification never changes a failing assertion into success.

Sanitized JSON evidence is schema-validated and allowlisted. It contains source/release identities, scenario/stage, opaque operation identity, normalized state, amount/currency, cardinality, and failure class. It excludes secrets, account/customer/card details, raw provider IDs where not essential, Checkout/Account Link URLs, raw events, and service bodies.

### 9. Public CI retains meaningful non-provider coverage

Default and fork CI run:

- settlement option/plan and hosted adapter mapping tests;
- scripted provider-port operation-journal/reconciliation tests in the private hosted producer's credential-free suite;
- public client conformance fixtures;
- marketplace buyer/storefront orchestration with injected public-client responses;
- configuration, packaging, signed production release verification, and image readiness tests that need no private source or Stripe secret;
- Alkahest and local EAS condition-boundary suites independently.

The protected Stripe lane runs for trusted changes touching hosted client/adapter, settlement runtime, hosted storefront/buyer flows, authority provider/lifecycle code, or its own harness, plus a scheduled drift run. Explicit local invocation fails with a named prerequisite; default public invocation neither skips nor discovers secret-bearing tests.

### 10. Delete simulator surfaces in coordinated producer/consumer cutovers

Consumer removal includes simulator-aware branches in Compose preparation and release verification, hermetic/local-EAS hosted targets, simulator scenario drivers/state/evidence, private control boundary tests, fixture wheel/image packaging scope, simulator credential/config fixtures, synthetic restart control, and documentation.

Producer removal is owned by a companion hosted-repository change: delete the fixture distribution/image/manifest/workflow, control/provider/clock processes and protocols, simulator migrations/stores, simulator Compose, and simulator-specific documentation. Preserve or rewrite valuable fault cases as internal provider-port integration tests before deleting their fixture implementation.

The consumer must not merge a state that still selects deleted producer artifacts. The producer may release the simplified production-only contract first because existing production behavior is unchanged; the consumer then removes simulator selection and pins that exact release.


## Implementation checkpoints

- Marketplace implementation checkpoint: `c128b902` (`test(e2e): add hosted settlement release scenarios`) contains ordinary hosted-release composition, marketplace lifecycle, the protected Stripe driver/evidence, and simulator consumer surfaces; no unrelated uncommitted work remained when this cutover began.
- Marketplace replacement plan: `81c8e47a` (`spec: replace hosted simulator with Stripe E2E`).
- Hosted implementation checkpoint: `f46ca41` (`feat(e2e): publish hosted settlement simulator`) contains the fixture/simulator/control/clock implementation and production injection seams.
- Hosted documentation checkpoint: `d4fd002` (`docs(e2e): define simulator release contract`).
- Hosted replacement change: `replace-e2e-simulator-with-scripted-provider-tests`, committed as `03cf2e2` (`spec: replace settlement simulator with provider tests`). It owns provider-port recovery migration, producer simulator deletion, permanent hosted documentation, and the exact production-only release handoff required before consumer deletion.

The consumer and producer worktrees were clean at these checkpoints. Completed implementation history remains in the superseded changes; neither superseded change claims the incomplete simulator acceptance matrix.

## Risks / Trade-offs

- **[Protected E2E is unavailable to forks and offline developers]** → Keep all Arkhai-owned logic covered in credential-free focused/integration suites; publish sanitized protected results against exact commits and release identities.
- **[Stripe/network/account failures add noise]** → Fail preflight before mutation, classify account/environment separately, use a maintained test account, bound read-only retries, and schedule periodic drift checks.
- **[Real test objects accumulate]** → Namespace every run, use exact metadata, refund eligible payments, retain bounded cleanup tooling, and never use broad destructive account cleanup.
- **[Some uncertainty boundaries cannot be induced end to end]** → Test them at the production provider interface and state explicitly that they prove Arkhai behavior, not Stripe behavior.
- **[Removing a large completed simulator diff risks deleting reusable work]** → Commit coherent checkpoints first; remove by named surface with package/content/config scans and preserve public lifecycle/Stripe driver code.
- **[Protected code could exfiltrate credentials]** → Run only trusted commits, scope credentials, isolate roles, keep webhook mapping loopback-only, redact at source, schema-validate evidence, and upload only allowlisted reports.
- **[Long-lived connected account drifts]** → Validate ownership and capabilities on every run; maintain onboarding as a separate scheduled/manual smoke and classify drift as account readiness.
- **[Two repositories cut over out of order]** → Land the producer's production-only release contract first, then pin it in the consumer; fail closed on any manifest/client/image mismatch.

## Migration Plan

1. Stop the ongoing simulator acceptance session. Checkpoint coherent reusable marketplace and hosted-service work without marking the remaining simulator tasks complete.
2. Add a final disposition to `add-local-hosted-settlement-e2e`: retain its completed production-release, lifecycle, and Stripe evidence; mark simulator-only remaining work superseded by this change; do not archive it as fully accepted simulator behavior.
3. Create and approve the companion hosted-repository change. Convert valuable simulator tests to internal provider-port integration tests and verify equivalent Arkhai recovery coverage before deleting fixture code.
4. Stabilize the existing protected Stripe driver against the ordinary production hosted release: complete preflight, real marketplace lifecycle bridge, Checkout, webhook, transfer, refund, restart/retrieval, exact inspection, evidence classification, and cleanup.
5. Remove consumer simulator artifacts and branches, then remove producer simulator distributions/topology in the coordinated order described above. Build and inspect all affected wheels/images to prove no fixture package or simulator entry point remains.
6. Run public focused/package/configuration/Alkahest/EAS suites and protected Stripe collection, reclaim, missed-webhook retrieval, and worker/API restart scenarios. Record exact consumer commit and hosted production manifest/image/client identities.
7. Promote the delta to permanent specs and architecture/testing/deployment documentation, update runbooks/workflows, complete comment hygiene and the design-promotion record, then archive the superseded and replacement changes according to their recorded disposition.

Rollback before the consumer cutover restores the checkpointed simulator-capable revisions and matching producer artifacts, but no new simulator acceptance work is performed. After the production-only hosted release and consumer removal are active, rollback restores both repositories and exact signed artifacts together; a mixed state is rejected by release preflight. Stripe-created test objects and accepted authority operations are recovered or refunded through the original operation identities rather than deleted from databases.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Provider-specific behavior is accepted only against Stripe test mode | `openspec/specs/test-compatibility/{spec,architecture}.md`; `docs/development/TESTING.md` |
| Deterministic Arkhai recovery uses scripted outcomes at the hosted financial-provider interface | `openspec/specs/test-compatibility/{spec,architecture}.md`; hosted producer testing architecture |
| Protected E2E consumes only the ordinary signed production hosted release | `openspec/specs/deployment-state/{spec,architecture}.md`; `docs/development/{ARCHITECTURE,DEPLOYMENT_AND_CONFIG}.md` |
| Public/fork and protected hosted checks have distinct credential/evidence boundaries | `openspec/specs/test-compatibility/spec.md`; `docs/development/{TESTING,DEPLOYMENT_AND_CONFIG}.md` |
| Simulator artifacts, controls, stores, protocols, and profiles are absent from active surfaces | `openspec/specs/deployment-state/{spec,architecture}.md`; `docs/development/ARCHITECTURE.md` |
| Connect onboarding is periodic while readiness is checked per protected run | `openspec/specs/test-compatibility/architecture.md`; protected E2E runbook |
| No roadmap impact unless the final implementation changes the hosted settlement product goal rather than its evidence strategy | Record final disposition here and update `docs/development/ROADMAP.md` only if applicable |
