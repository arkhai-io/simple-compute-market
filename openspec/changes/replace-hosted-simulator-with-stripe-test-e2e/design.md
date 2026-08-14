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
2. preflight a test-mode secret (`sk_test` or least-privilege `rk_test`), non-live returned objects, API connectivity, allowlisted connected account ownership and capabilities, and loopback webhook mapping;
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

The replacement decisions are promoted as current behavior at the following
permanent destinations. Consumer documentation is in this repository;
producer documentation named below is owned and published independently by
`hosted-settlement-service`.

| Accepted decision | Permanent owner and location |
|---|---|
| Provider-specific Checkout, webhook, connected-account, retrieval, transfer, refund, decline, and authentication behavior is accepted only against Stripe test mode | Consumer evidence contract: `openspec/specs/test-compatibility/{spec,architecture}.md`; developer guidance: `docs/development/TESTING.md`; operator stages: `e2e-tests/tests/e2e/roles/README.md` |
| Timeout placement, unknown acknowledgement, delayed visibility, provider unavailability, exact-attempt failure, event duplication/order, journal recovery, and idempotency are Arkhai claims tested with provider-neutral scripted outcomes at the hosted financial-provider or webhook-inbox boundary | Consumer ownership statement: `openspec/specs/test-compatibility/{spec,architecture}.md`; producer normative implementation boundary: `hosted-settlement-service/openspec/specs/test-compatibility/{spec,architecture}.md`; developer explanation: `docs/development/{ARCHITECTURE,TESTING}.md` |
| The scripted provider is a direct test injection with no HTTP/provider-shaped API, credential, reusable control surface, clock/event endpoint, production entry point, dependency, or release artifact | Consumer prohibition: `openspec/specs/deployment-state/{spec,architecture}.md`; producer artifact/composition contract: `hosted-settlement-service/openspec/specs/deployment-state/{spec,architecture}.md` and `hosted-settlement-service/docs/{ARCHITECTURE,DEPLOYMENT,RELEASING}.md` |
| Protected financial E2E consumes only one ordinary signed production hosted manifest, exact released client wheel, digest-pinned service image, ordinary migration/API/worker roles, and public network/client contracts | `openspec/specs/deployment-state/{spec,architecture}.md`; `docs/development/{ARCHITECTURE,DEPLOYMENT_AND_CONFIG}.md`; `e2e-tests/tests/e2e/roles/README.md` |
| Marketplace owns publication, discovery, negotiation, materialization, buyer action, VM fulfillment, collection/reclaim, status, restart, and recovery scenarios; hosted owns financial authority, provider adapter, operation journal, webhook inbox, and reconciliation | `docs/development/ARCHITECTURE.md`; `openspec/specs/test-compatibility/architecture.md`; producer boundary in `hosted-settlement-service/docs/ARCHITECTURE.md` |
| Exact run identity keeps marketplace repository/commit separate from hosted manifest digest, client wheel version/hash, image digest, signed release repository/workflow reference/source commit, and the separate protected producer workflow run identity used as orchestration evidence; operation identity remains opaque and durable | `openspec/specs/test-compatibility/{spec,architecture}.md`; `docs/development/TESTING.md`; `e2e-tests/tests/e2e/roles/README.md` |
| Protected preflight proves the exact release, a test-mode secret (`sk_test` or least-privilege `rk_test`), non-live objects, Stripe connectivity, allowlisted connected-account ownership/capabilities/readiness, exact loopback webhook mapping, and Chromium before the applicable mutation boundary | `openspec/specs/deployment-state/{spec,architecture}.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md`; `e2e-tests/tests/e2e/roles/README.md` |
| Protected outcomes use `product`, `account`, `environment`, and `timeout`; classification never converts a failed assertion into success | `openspec/specs/test-compatibility/{spec,architecture}.md`; `docs/development/TESTING.md`; `e2e-tests/tests/e2e/roles/README.md` |
| Evidence is allowlisted and excludes credentials, action/onboarding URLs, account/customer/card data, raw webhooks, unrestricted provider payloads, unrelated objects, and secret-bearing process output | `openspec/specs/{test-compatibility,deployment-state}/spec.md`; `docs/development/{TESTING,DEPLOYMENT_AND_CONFIG}.md`; `e2e-tests/tests/e2e/roles/README.md` |
| Setup/read-only observation may retry within bounds; financial mutation and recovery retain the original durable production idempotency identity; exact related objects, never latest-account objects, satisfy assertions | `openspec/specs/test-compatibility/{spec,architecture}.md`; `docs/development/TESTING.md`; `e2e-tests/tests/e2e/roles/README.md` |
| Connect onboarding is manual/scheduled account lifecycle work, while exact allowlisted-account readiness is checked on every protected transaction run | `openspec/specs/test-compatibility/architecture.md`; `docs/development/{TESTING,DEPLOYMENT_AND_CONFIG}.md`; `e2e-tests/tests/e2e/roles/README.md` |
| Missed-webhook and process-restart evidence uses real forwarding/process omissions, preserved authority state, and the original operation identity; it does not imitate provider faults | `openspec/specs/test-compatibility/{spec,architecture}.md`; `docs/development/{ARCHITECTURE,TESTING}.md`; `e2e-tests/tests/e2e/roles/README.md` |
| Default/fork CI remains credential-free and does not discover secret-bearing tests; the only protected hosted financial target is `hosted-stripe-test` | `openspec/specs/{test-compatibility,deployment-state}/spec.md`; `docs/development/{TESTING,DEPLOYMENT_AND_CONFIG}.md`; `e2e-tests/tests/e2e/roles/README.md` |
| Alkahest E2E remains independent. Local EAS/allowlisted-arbiter work is only condition-boundary conformance and currently has no standalone hosted operator target | `openspec/specs/test-compatibility/architecture.md`; `docs/development/TESTING.md`; `e2e-tests/tests/e2e/roles/README.md` |
| Active deployment, packaging, workflow, configuration, release-verification, schema, and permanent-documentation surfaces expose no alternate provider artifact, control topology, or test-only hosted release | `openspec/specs/deployment-state/{spec,architecture}.md`; `docs/development/{ARCHITECTURE,DEPLOYMENT_AND_CONFIG}.md` |
| Completed simulator-era implementation remains historical but its incomplete acceptance and closeout are superseded by this replacement | `openspec/changes/add-local-hosted-settlement-e2e/{proposal,design,tasks}.md` |
| This evidence cutover does not change the hosted settlement product goal | No `docs/development/ROADMAP.md` change |

The production-only hosted release is signed by `local-release-authority` at `0x78379a48a88afbe69dcbc943b80f390bf1b3315e`. Its canonical manifest digest is `sha256:dabc29ede1ecb23f0f16652967c53e27d82b0863684d7b9028c84336bbb8347f`, and the exact `release-manifest.json` file hash pinned by `manifests/hosted-settlement-v0.1.0-trust.json` is `sha256:abe70559d7424fe36e586f2ab2276aa1adb117f958520a9389961087b21fef19`.

The consumer pins client wheel `arkhai_hosted_settlement_client-0.1.0-py3-none-any.whl` at `sha256:47ed10de818f7349a902ccb539806832938253ece1d0c2cde6e9bdca75f8b6ed` and `localhost/arkhai-hosted-settlement-service@sha256:3f5dac22407de929b6cbc2dfa5b6827ac152759213866013ece8f92da5871c21`. The producer release additionally binds service wheel `sha256:6643956f8630549483a1c3029aa0cb712351753411be2268036a44c3733b4aad`, migrations schema 4 `sha256:933c809825e6ab474625553d2d33c00dada562646e5e007f12c0b8d925cbf571`, OpenAPI `sha256:a74d212c776cf0b99dc0937864325ad2da797cc2c7cb75549746c3acab364aef`, conformance `sha256:78886513a201c2ae860bb33c32f05de2afbe5ea65466eac4ed59bfc6b2b27b27`, SPDX SBOM `sha256:0d2b106fe30ee66022e5be3d4c79a73a36abc4820005ba0b55850d235b6a04cd`, and provenance `sha256:248e9bd1715a43fd05e2b42cd5dd9ca06d3ad4e05aed8803d076fb26fe245786`.

Producer repository `arkhai/hosted-settlement-service`, workflow ref `.github/workflows/release.yml@local/ff19f18297af87de15e78581ae07b29530487c4f`, source commit `ff19f18297af87de15e78581ae07b29530487c4f`, and producer run identity `local:ff19f18` remain separate from marketplace commit `0b995f7960b705ee51d024aacade9df36888c1f9` and protected Stripe workflow run identity. Marketplace release preflight verified this tuple before generating `.dist/hosted-settlement-compose.env`; later closeout-only documentation and import-placement commits are not represented as provider evidence.

Protected local Stripe test-mode runs produced sanitized schema-v2 evidence. Collection, reclaim/refund, decline, and insufficient-funds scenarios passed against the exact release above. Authoritative provider inspection for the successful collection found one charge, one Checkout Session, one PaymentIntent, and one related transfer; reclaim found the one expected refund and no duplicate transfer or refund. Missed-webhook, API-restart, worker-restart, and authentication attempts did not pass: Stripe-hosted interactive CAPTCHA/Chromium availability, Checkout contract rejection, or bounded convergence timeout remained unresolved external/product outcomes. The harness retained their non-success classifications and did not substitute focused tests for provider evidence.
