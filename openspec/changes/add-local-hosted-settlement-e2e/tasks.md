## 1. Prerequisites and artifact contract

- [x] 1.1 Confirmed prerequisite identity/configuration changes are archived and recorded the final client, principal, configuration, CLI, and recovery contracts in `design.md`.
- [x] 1.2 Verified the signed private hosted release contract, production compatibility identity, image digests, control schema/client version, migration schema, capabilities, and sanitized acquisition instructions.
- [x] 1.3 Assigned existing hosted integration behavior across conformance, focused tests, hermetic system evidence, real Stripe evidence, and removal in `design.md`.

## 2. Private release preflight and local composition

- [x] 2.1 Extend `scripts/verify-hosted-release.py` and focused tests to verify production versus E2E manifest identity, exact client/service compatibility, image digests, simulator/control schema versions, migration schemas, required capabilities, repository/workflow/source identity, and E2E-only designation before stack startup; reject floating tags, unsigned local artifacts, mismatched wheels, and production manifests for hermetic mode.
- [x] 2.2 Refactor `compose.hosted-settlement.yml` to preserve the existing digest-pinned migrate/API/worker and named authority volume while adding profile-selected private simulator/control services and durable simulator state; keep controls on the internal network, use the authority service name internally, retain a configurable non-conflicting loopback host port, and mount no sibling source.
- [x] 2.3 Add hosted-only wallet-free storefront and buyer configuration fixtures under the existing E2E config ownership, with `[Identity]` plus `[Settlement]`/`[Settlement.stripe]`, portable conditions, exact trust pins, and no `[Wallet]`, `[Chains]`, RPC, chain signer, provider, webhook, database, administrator, simulator-control, or Stripe secret fields in marketplace runtime config.
- [x] 2.4 Add explicit root/e2e Make targets for preflight, clean startup, restart-preserving execution, clean-volume teardown, hermetic hosted execution, local EAS profile, and real Stripe execution; ordinary build/test/E2E targets must not resolve private artifacts, and an explicitly selected hosted target must fail before startup with the exact missing private input rather than skip.
- [x] 2.5 Add Compose/render/preflight tests for local private image and immutable registry image inputs, port coexistence, ready digest/schema/capability mismatch, wrong control version, missing Secret/environment file, production/E2E artifact confusion, internal-only controls, no source/editable mount, and clean versus restart-preserving volume behavior.

## 3. Marketplace-owned staged hosted scenario

- [x] 3.1 Added the dedicated hosted VM `DealState` carrier and exact producer/consumer dependency coverage without branching the Alkahest state.
- [x] 3.2 Added versioned private-control fixtures only to the opt-in hosted E2E image, including deterministic outcomes, funding, events, time, waits, and sanitized effect inspection.
- [x] 3.3 Implemented verified readiness, wallet-free runtime, account admission, publication, discovery, negotiation, materialization, redirect, and stable identity stages.
- [x] 3.4 Implemented simulated funding, VM fulfillment, portable condition projection, ordinary claim servicing, terminal status, and exactly-one normalized effect assertions.
- [x] 3.5 Verified the default hosted scenario constructs no wallet/chain/RPC/EAS client, leaks no private controls/provider data, and leaves public test discovery independent of private artifacts.

## 4. Hermetic recovery and coexistence evidence

- [x] 4.1 Added isolated collection and false-condition expiry-reclaim scenarios with controlled time and exactly-one terminal effect assertions.
- [x] 4.2 Added withheld, duplicate, and out-of-order event cases proving authoritative reconciliation and idempotency without sleeps.
- [x] 4.3 Added transfer/refund failure, timeout, unknown-acknowledgement, and delayed-visibility recovery cases with stable operation identity.
- [x] 4.4 Added storefront and authority restart cases across materialization, funding, fulfillment evidence, and provider submission.
- [x] 4.5 Added hosted/Alkahest readiness, priority, recovery, none-ready, and post-acceptance pinning cases without changing existing Alkahest behavior.
- [x] 4.6 Added separately selected local Anvil/EAS/allowlisted-arbiter condition conformance while keeping finance simulated.

## 5. Protected real Stripe lane

- [x] 5.1 Add an authorized local/protected-CI driver that verifies non-live `sk_test` mode and a ready controller-compatible test account, starts the ordinary hosted image, captures the Stripe CLI `whsec` secret without logging it, and forwards signed events to the loopback-only `/webhooks/stripe` mapping.
- [x] 5.2 Drive the marketplace-owned discovery/negotiation/materialization path and real Checkout in Chromium with Stripe test inputs; wait for authoritative authority/marketplace state and complete the VM portable fulfillment path without persisting Checkout or Account Link URLs.
- [x] 5.3 Verify through protected provider inspection exactly one matching Checkout and destination transfer, expected amount/currency/account, transfer group, source transaction, and operation metadata; add an eligible pre-transfer refund case when deterministic provider/account state permits and report it separately when externally unavailable.
- [x] 5.4 Add a protected/manual workflow or private producer-workflow contract that checks out an exact trusted marketplace commit, uses least-privilege short-lived artifact/provider credentials, never exposes secrets to fork code, records both source/release identities, uploads only allowlisted sanitized evidence, and tears down local volumes/processes on every outcome.

## 6. Focused verification

- [x] 6.1 Focused hosted adapter/runtime, storefront, buyer, E2E state, release, Compose, package-boundary, Ruff, and mypy checks passed.
- [x] 6.2 Built marketplace wheels and the opt-in E2E image from staged wheels; verified immutable release preflight and absence of sibling editable source.
- [ ] 6.3 Run hermetic collection, reclaim, event, uncertainty, restart, readiness/coexistence, and wallet-free scenarios; run local EAS profile separately and existing Alkahest E2E unchanged.
- [ ] 6.4 Run available real Stripe test-mode Checkout/Connect/transfer/refund evidence and disclose unavailable credentials, webhook reachability, account readiness, protected workflow, or external service behavior without substituting simulator output.
- [x] 6.5 Targeted strict validation passed; repository-wide validation reported six unrelated active-change failures. This repository has no root `make check` target, so focused package targets were used.

## 7. Closeout

Per `openspec/README.md` plan-closeout requirements.

- [x] 7.1 `make check-comment-hygiene` passed and touched comments/docs contain current boundary rationale without temporary identifiers, secrets, or migration narrative.
- [x] 7.2 Package, image, Compose, report, and workflow boundary suites verify private controls remain E2E-only, fork workflows remain credential-free, and ordinary entry points remain intact.
- [x] 7.3 Promoted artifact-bound hosted system evidence, deterministic control ownership, and separate real-provider reporting to permanent test-compatibility and testing documentation.
- [x] 7.4 Promoted immutable local composition, startup gating, secret isolation, and public contributor behavior to permanent deployment and architecture documentation.
- [x] 7.5 Updated the E2E role runbook with current stages, commands, evidence, reset, and external-limit behavior; `ROADMAP.md` remains unchanged because this work changes delivery evidence, not product intent.
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
