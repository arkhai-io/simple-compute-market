## 1. Prerequisites and artifact contract

- [ ] 1.1 Confirm `add-hosted-account-identities`, `add-nonchain-marketplace-identities`, and `unify-settlement-mechanism-configuration` are implemented, strictly validated, promoted, and archived; record the final client, principal, configuration, CLI, and recovery contracts in `design.md` without copying active-change prose into production code.
- [ ] 1.2 Confirm private hosted change `add-hosted-settlement-e2e-simulator` has published an immutable E2E manifest, production release compatibility identity, authority/simulator image digests, control schema/client version, simulator migration schema, capabilities, and sanitized acquisition instructions.
- [ ] 1.3 Inventory `compose.hosted-settlement.yml`, `Makefile`, `scripts/verify-hosted-release.py`, `e2e-tests/{Makefile,Dockerfile,pyproject.toml,config,src,tests/e2e/roles}`, `.github/workflows/{tests,e2e}.yml`, and the generated hosted cross-repo smoke in `design.md`; assign every existing behavior to hosted conformance, marketplace focused tests, hermetic system evidence, real Stripe evidence, or removal.

## 2. Private release preflight and local composition

- [ ] 2.1 Extend `scripts/verify-hosted-release.py` and focused tests to verify production versus E2E manifest identity, exact client/service compatibility, image digests, simulator/control schema versions, migration schemas, required capabilities, repository/workflow/source identity, and E2E-only designation before stack startup; reject floating tags, unsigned local artifacts, mismatched wheels, and production manifests for hermetic mode.
- [ ] 2.2 Refactor `compose.hosted-settlement.yml` to preserve the existing digest-pinned migrate/API/worker and named authority volume while adding profile-selected private simulator/control services and durable simulator state; keep controls on the internal network, use the authority service name internally, retain a configurable non-conflicting loopback host port, and mount no sibling source.
- [ ] 2.3 Add hosted-only wallet-free storefront and buyer configuration fixtures under the existing E2E config ownership, with `[Identity]` plus `[Settlement]`/`[Settlement.stripe]`, portable conditions, exact trust pins, and no `[Wallet]`, `[Chains]`, RPC, chain signer, provider, webhook, database, administrator, simulator-control, or Stripe secret fields in marketplace runtime config.
- [ ] 2.4 Add explicit root/e2e Make targets for preflight, clean startup, restart-preserving execution, clean-volume teardown, hermetic hosted execution, local EAS profile, and real Stripe execution; ordinary build/test/E2E targets must not resolve private artifacts, and an explicitly selected hosted target must fail before startup with the exact missing private input rather than skip.
- [ ] 2.5 Add Compose/render/preflight tests for local private image and immutable registry image inputs, port coexistence, ready digest/schema/capability mismatch, wrong control version, missing Secret/environment file, production/E2E artifact confusion, internal-only controls, no source/editable mount, and clean versus restart-preserving volume behavior.

## 3. Marketplace-owned staged hosted scenario

- [ ] 3.1 Add a dedicated hosted VM `DealState` carrier and exact `require_state` producers/consumers under `e2e-tests/tests/e2e/roles/scenarios/vms/`; do not branch or reinterpret the existing Alkahest full-deal state, and add state-dependency tests for every field.
- [ ] 3.2 Add private-control process/client fixtures only to the opt-in hosted E2E test image/selection; expose version check, outcome plan, fund/expire, event gate, monotonic clock advance, named-state wait, and sanitized effect inspection without importing hosted service/simulator source or placing controls in storefront/buyer packages.
- [ ] 3.3 Implement stages for verified authority/simulator readiness, wallet-free common settlement status, account readiness, hosted listing create/resume/publication, registry discovery, buyer negotiation, accepted `fiat.stripe.v1` Terms, materialization, buyer redirect action, and stable marketplace/authority operation identities.
- [ ] 3.4 Implement stages for simulated funding, VM provisioning/fulfillment completion, portable condition projection, ordinary claim-worker evaluation/collection, terminal buyer/storefront/authority status, and sanitized inspection of exactly one matching transfer with expected amount, currency, destination fixture, transfer group, and source relation.
- [ ] 3.5 Assert no wallet/chain/RPC/EAS client is constructed in the default hosted scenario, no provider identifier/control URL/credential/raw event escapes its allowed test boundary, and default public test discovery/import works when all private artifacts and packages are absent.

## 4. Hermetic recovery and coexistence evidence

- [ ] 4.1 Add isolated clean-store scenarios for satisfied collection and false-condition expiry reclaim, advancing only the simulator clock and asserting exactly one refund with no transfer after ordinary marketplace reclaim/reconciliation.
- [ ] 4.2 Add withheld, duplicate, and out-of-order event scenarios proving authoritative retrieval and webhook idempotency converge without sleeps, state regression, duplicate Checkout, transfer, or refund.
- [ ] 4.3 Add retryable failure, timeout-before-submit, unknown-after-submit, and delayed-visibility scenarios for transfer and refund; restart authority API/worker at the uncertain boundary and prove stable operation identity and exactly one terminal provider effect.
- [ ] 4.4 Add storefront and worker restart scenarios after materialization, funding, fulfillment evidence, and provider submission; preserve named volumes and prove the original accepted obligation resumes without rematerialization or fallback.
- [ ] 4.5 Add dual-mechanism cases for hosted-only, Alkahest-only, both-ready priority order, each one-unready state, none-ready failure, readiness recovery, and post-acceptance priority/enablement change; prove existing hosted operations stay on Stripe and existing Alkahest scenarios remain unchanged.
- [ ] 4.6 Add the separately selected local Anvil/EAS/allowlisted-arbiter profile using the simulator for finance; run only condition-boundary cases and keep wallet-free/real-Stripe targets independent from it.

## 5. Protected real Stripe lane

- [ ] 5.1 Add an authorized local/protected-CI driver that verifies non-live `sk_test` mode and a ready controller-compatible test account, starts the ordinary hosted image, captures the Stripe CLI `whsec` secret without logging it, and forwards signed events to the loopback-only `/webhooks/stripe` mapping.
- [ ] 5.2 Drive the marketplace-owned discovery/negotiation/materialization path and real Checkout in Chromium with Stripe test inputs; wait for authoritative authority/marketplace state and complete the VM portable fulfillment path without persisting Checkout or Account Link URLs.
- [ ] 5.3 Verify through protected provider inspection exactly one matching Checkout and destination transfer, expected amount/currency/account, transfer group, source transaction, and operation metadata; add an eligible pre-transfer refund case when deterministic provider/account state permits and report it separately when externally unavailable.
- [ ] 5.4 Add a protected/manual workflow or private producer-workflow contract that checks out an exact trusted marketplace commit, uses least-privilege short-lived artifact/provider credentials, never exposes secrets to fork code, records both source/release identities, uploads only allowlisted sanitized evidence, and tears down local volumes/processes on every outcome.

## 6. Focused verification

- [ ] 6.1 Run focused hosted adapter, settlement runtime, storefront publication/status/CLI, buyer negotiation/settlement/recovery, E2E state dependency, release verification, Compose/render, package-content, and secret-redaction suites plus affected Ruff and mypy checks.
- [ ] 6.2 Build/install marketplace wheels and E2E images from the review wheelhouse with no sibling editable source; prove the default build and ordinary E2E run without private registry/package access, then run the hermetic hosted stack from exact signed private artifacts.
- [ ] 6.3 Run hermetic collection, reclaim, event, uncertainty, restart, readiness/coexistence, and wallet-free scenarios; run local EAS profile separately and existing Alkahest E2E unchanged.
- [ ] 6.4 Run available real Stripe test-mode Checkout/Connect/transfer/refund evidence and disclose unavailable credentials, webhook reachability, account readiness, protected workflow, or external service behavior without substituting simulator output.
- [ ] 6.5 Run `make check`, targeted strict validation for this change, repository-wide strict OpenSpec validation, and report unrelated active-change failures separately.

## 7. Closeout

Per `openspec/README.md` plan-closeout requirements.

- [ ] 7.1 Run `make check-comment-hygiene`; review touched comments/docstrings and remove change/task IDs, migration narrative, tombstones, temporary artifact paths, private identifiers, old cross-repo-smoke ownership claims, and secrets while retaining current boundary rationale.
- [ ] 7.2 Review imports, wheels, images, Compose renders, reports, and workflows: no hosted service/simulator source or editable path ships; production marketplace packages contain no test controls; public/fork workflows receive no private credential; existing Alkahest and ordinary E2E entry points remain intact.
- [ ] 7.3 Promote consumer-owned artifact-bound system evidence, staged deterministic controls, and separate real-provider reporting to `openspec/specs/test-compatibility/{spec,architecture}.md` and `docs/development/TESTING.md`.
- [ ] 7.4 Promote optional private local composition, ready/release gating, secret isolation, and public contributor behavior to `openspec/specs/deployment-state/{spec,architecture}.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md`; clarify the external hosted release boundary in `docs/development/ARCHITECTURE.md` only where needed.
- [ ] 7.5 Update `e2e-tests/tests/e2e/roles/README.md` and owning command/config references with current invocation, state, evidence, reset, and external-limit behavior; update or explicitly leave `ROADMAP.md` unchanged with rationale.
- [ ] 7.6 Compress completed task notes to final behavior/evidence, record the hosted E2E and production manifest identities used for acceptance, and complete the design-promotion record below before archive.

## Design Promotion Record

| Accepted decision | Permanent location |
|---|---|
| Marketplace owns consumer scenarios while hosted owns private implementation/artifacts | `openspec/specs/test-compatibility/{spec,architecture}.md`; `docs/development/ARCHITECTURE.md` if clarification is needed |
| Local hosted composition consumes signed immutable artifacts and never sibling source | `openspec/specs/deployment-state/{spec,architecture}.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Hermetic lifecycle evidence and real Stripe compatibility evidence are separate lanes | `openspec/specs/test-compatibility/{spec,architecture}.md`; `docs/development/TESTING.md` |
| Default public builds and fork CI require no private artifacts or credentials | `openspec/specs/deployment-state/{spec,architecture}.md`; workflow/developer documentation |
| Test controls remain isolated from marketplace production runtime and public APIs | `openspec/specs/{test-compatibility,deployment-state}/{spec,architecture}.md` |
| Wallet-free portable conditions are the default; local EAS conformance is separate | `openspec/specs/test-compatibility/{spec,architecture}.md`; E2E role documentation |
