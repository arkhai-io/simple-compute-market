## Context

The repository already has `compose.hosted-settlement.yml`, which consumes a digest-pinned image and signed release directory and joins migration, API, worker, and Bob's storefront to one Compose project. It does not provide a deterministic provider, staged hosted lifecycle scenario, private-artifact acquisition boundary, or protected real-Stripe lane. The generated smoke in the private hosted repository imports the marketplace adapter through an in-process ASGI transport; that proves useful contract behavior but reverses lasting consumer ownership and omits packaging, networking, worker, browser, and restart boundaries.

The hosted authority remains privately implemented and separately released. This public repository may reveal the client/wire contract it must use, but must not require hosted source, private artifacts, or credentials for its default build. Existing `test-compatibility` rules require exact staged state dependencies and observable asynchronous seams. Existing settlement changes establish scheme-tagged wallet-free identity and one common Stripe/Alkahest runtime; this change consumes those results rather than redefining them.

## Goals / Non-Goals

**Goals:**

- Prove the VM marketplace and a released private hosted authority compose end to end on one workstation and in protected CI.
- Keep scenario ownership in the consumer repository while consuming hosted code only as immutable signed artifacts.
- Provide deterministic hermetic lifecycle/recovery evidence and separately labeled real Stripe compatibility evidence.
- Preserve ordinary public builds, tests, and Alkahest flows without private access.
- Make failures attributable to release verification, composition, marketplace lifecycle, authority lifecycle, provider simulation, or external Stripe.

**Non-Goals:**

- Open-source, vendor, mount, or inspect hosted service/simulator implementation.
- Add a marketplace-owned financial provider, authority state machine, webhook handler, or simulator control API.
- Treat simulated outcomes as Stripe evidence.
- Require EVM/EAS infrastructure for wallet-free hosted tests or replace the local EAS conformance suite.
- Add hosted settlement to every market domain; this change proves the existing VM composition only.
- Change production activation, custody semantics, or the accepted settlement lifecycle.

## Decisions

### 1. Keep scenario ownership downstream and artifact ownership upstream

`simple-market-service` owns the marketplace scenario, stage carrier, Compose overlay, targets, and assertions. `hosted-settlement-service` owns the authority, simulator, private control client, images, and signed manifests. A protected producer workflow may check out an exact consumer commit and invoke this repository's target, but no hosted package imports marketplace code and no marketplace runtime imports hosted source.

The existing `.dist/cross-repo-smoke.py` behavior is split: hosted retains client/service conformance; this repository gains adapter/system evidence. A third integration repository is deferred because only one marketplace currently consumes the authority and would add release coordination without clarifying ownership.

### 2. Extend the existing artifact-only Compose overlay

Extend `compose.hosted-settlement.yml`; do not introduce a source-building sibling overlay. Production-like and real-Stripe modes keep the existing migrate/API/worker services and named authority volume. Hermetic mode adds only signed E2E artifacts declared by the private E2E manifest: the E2E authority image/entry points, simulator service, durable simulator volume, and isolated control address.

All images use immutable `repository@sha256:digest` references verified before `compose up`. The authority stays on container port 8080 and retains the current non-conflicting host mapping (18080 unless made configurable). Storefront configuration uses `http://hosted-settlement-api:8080`. Ready gating verifies manifest digest, schema, API version, and capabilities; Compose health alone is not sufficient evidence.

The overlay remains opt-in and composes with `compose.vms.yml`. Named volumes are retained during restart stages and removed between independent scenarios.

### 3. Use two evidence lanes

**Hermetic lane:** the private simulator deterministically controls Checkout, funding/expiry, transfer/refund outcomes, event delivery, failures, authoritative visibility, and time. It proves marketplace/authority composition and failure recovery without external network access.

**Real Stripe lane:** the ordinary hosted release uses `sk_test_...`, a ready Express test account, browser-driven Checkout, Stripe CLI forwarding to `localhost:18080/webhooks/stripe`, and authoritative Stripe inspection. It proves SDK/API, Checkout, webhook-signature, Connect, transfer, and refund compatibility. Credentials and connected accounts exist only in authorized local files or protected CI.

Results and target names remain separate. Neither lane silently falls back to the other.

### 4. Keep private controls outside marketplace runtime

The staged test runner may consume a private control client/CLI installed only in the hosted E2E test image or invoke a versioned external command supplied by the E2E manifest. Storefront, buyer, core settlement, and production marketplace images receive no control endpoint, credential, provider model, or simulator dependency.

The harness exposes a narrow fixture protocol to scenario code: set outcome, fund/expire Checkout, withhold/release/duplicate event, advance monotonic clock, wait for named simulator state, and inspect sanitized effects by operation reference. The control client verifies its contract version and authenticates with an E2E-only credential. The scenario never edits authority or simulator databases directly.

### 5. Add a dedicated staged VM hosted scenario

Create a separate scenario and state carrier rather than branching the Alkahest full-deal module. Stages are sequential and name exact producer/consumer fields:

1. verify hosted production/E2E manifests and composition readiness;
2. verify wallet-free storefront status and account readiness;
3. create/resume a hosted listing and assert published `fiat.stripe.v1` option;
4. discover and negotiate through the buyer surface;
5. materialize and capture the buyer redirect action plus stable marketplace operation identity;
6. fund through simulator control or browser Checkout;
7. complete VM fulfillment and publish portable condition evidence;
8. observe condition readiness and collection;
9. inspect exactly one transfer and terminal marketplace/authority projections;
10. run isolated reclaim and recovery scenarios from clean stores.

Required hermetic cases are happy collection, withheld webhook reconciliation, duplicate/out-of-order webhook, transfer unknown-after-submit, refund unknown-after-submit, API/worker/storefront restarts, accepted-mechanism pinning after configuration changes, and hosted/Alkahest readiness isolation. Lower-level suites retain exhaustive validation and state-machine branches.

### 6. Separate condition profiles

The default hosted scenario uses the portable signed/built-in condition path and Ed25519 principals established by prerequisite changes. Wallet, Chains, RPC, chain signer, and EAS configuration are absent and asserted absent. A separate selected profile pairs the simulator with local Anvil/EAS/allowlisted arbiter conformance; it does not multiply every financial scenario across both condition modes.

### 7. Fail explicitly without burdening public contributors

Default Make, wheelhouse, image, unit/integration, and ordinary E2E targets do not resolve private artifacts. An explicitly selected hosted target performs preflight before building the stack and fails with the missing environment key, manifest path, image identity, registry authentication, or contract incompatibility. It must not convert missing private inputs into pytest skips.

Public and fork workflows never receive private credentials. A protected workflow or private producer workflow supplies short-lived registry access, exact artifact identities, and test credentials. Logs and uploaded artifacts are scrubbed and allowlisted; raw environment files, Checkout/Account Link URLs, webhooks, manifests carrying credentials, and control tokens are never uploaded.

### 8. Preserve release identity end to end

The consumer records both marketplace source commit and hosted production/E2E manifest digests in the test report. The hosted client wheel used to build marketplace artifacts must match the authority compatibility declaration. Floating tags, editable paths, and unverified sibling `.dist` contents are rejected. A local developer may build the private images in a sibling checkout, but this repository receives only the resulting signed local artifacts.

## Test Matrix

| Lane | Financial provider | Condition | Required scope |
|---|---|---|---|
| Public focused | injected adapter fake | portable | adapter mappings and common runtime behavior |
| Hermetic system | private durable simulator | portable | full VM lifecycle, retries, events, restarts, reclaim, coexistence |
| EVM conformance | private durable simulator | local Anvil/EAS | EAS marker and allowlisted arbiter boundary only |
| Real provider | Stripe test mode | portable | Checkout, signed webhook, Connect transfer/refund compatibility |
| Regression | Anvil/Alkahest | EVM | existing marketplace lifecycle unchanged |

## Risks / Trade-offs

- **Private artifacts make public reproduction incomplete.** Default public behavior remains fully testable; the optional proprietary mechanism clearly reports its access prerequisite and protected results identify exact artifacts.
- **The public scenario reveals protocol behavior.** Any client must know the supported wire contract; implementation, provider operations, simulator internals, and secrets remain private.
- **A simulator can diverge from Stripe.** It models only the provider port and is never labeled Stripe evidence; the protected real-provider lane catches integration drift.
- **Cross-repository releases can drift.** Signed compatibility metadata, exact client pins, and pre-start verification fail closed.
- **Staged E2E can become slow and brittle.** Use observable waits and explicit state, reserve full failure matrices for hermetic mode, and keep real Stripe to a narrow compatibility flow.
- **Private CI could expose credentials to consumer code.** Run only trusted commits, use least-privilege short-lived credentials, isolate fork workflows, and upload sanitized allowlisted evidence.

## Migration Plan

1. Complete and pin `add-hosted-account-identities`, `add-nonchain-marketplace-identities`, and `unify-settlement-mechanism-configuration`.
2. Consume the signed E2E artifact contract from private change `add-hosted-settlement-e2e-simulator`.
3. Extend release preflight and `compose.hosted-settlement.yml` for explicit production versus E2E manifests and isolated simulator services.
4. Add hosted-only marketplace configuration fixtures and the staged wallet-free VM scenario.
5. Add deterministic collection, reclaim, event, uncertainty, restart, and mechanism-coexistence cases.
6. Add protected private-artifact CI and sanitized evidence capture.
7. Add the separate real Stripe local/protected target and browser/webhook driver.
8. Remove marketplace-adapter behavior from the hosted generated cross-repo smoke after equivalent consumer evidence passes.

Rollback removes the opt-in targets/profile and private workflow invocation. It does not modify production data, ordinary Compose selection, existing Alkahest tests, or released authority state. A failed hosted scenario resets only its named local E2E volumes and ephemeral test accounts according to the private runbook.

## Permanent Documentation Promotion

- Artifact-bound consumer ownership, staged hermetic evidence, and separate real-provider reporting: `openspec/specs/test-compatibility/{spec,architecture}.md` and `docs/development/TESTING.md`.
- Optional private local composition, release verification, secret isolation, and public contributor behavior: `openspec/specs/deployment-state/{spec,architecture}.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- Hosted release remains external and no editable/source dependency crosses upward: `docs/development/ARCHITECTURE.md` only if its current package/release boundary needs clarification.
- Role-level invocation and state fields: `e2e-tests/tests/e2e/roles/README.md` and existing operator/developer command references, describing current behavior rather than the change history.
