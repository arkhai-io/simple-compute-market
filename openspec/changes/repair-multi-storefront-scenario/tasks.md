# Tasks — repair-multi-storefront-scenario

## Implementation status

**Code and validation ready for review.** Separate authorities are implemented;
permanent documentation promotion remains pending post-code-review.

## 1. Declare the limitation

- [x] 1.1 Skip `test_06b_buyer_starts_negotiation_with_alice` and
      `test_06c_negotiations_are_distinct_objects_on_distinct_storefronts` with
      a reason naming the single storefront principal, ROADMAP Goal 1, and this
      change.
- [x] 1.2 Leave the registry stages running. Alice's registry path does not
      depend on provisioning, and those stages are the scenario's subject.
- [x] 1.3 Confirm the skip set: the focused Docker scenario passes all 21
      tests with no skips, including both Alice readiness and negotiation.

## 2. Give each storefront its own provisioning authority

Implementation files and validation:

- `domains/vms/compose.yml`: add Alice's authority with its own process-local job queue;
  preserve per-container database isolation and set Alice's callback target.
- `compose.local-identities.yml`, `Makefile`, and
  `dev-env/identities/provisioning-alice.identity.env`: inject a deterministic
  development signer distinct from Bob's authority.
- `compose.vms-fiat.yml`: keep Alice's authority under the same
  optional profile as Alice so hosted-only runs remain independent.
- `domains/vms/storefront/storefront.alice.toml`: pin Alice's authority for
  requests and callbacks, switch URLs, and enable projection derivation.
- `e2e-tests/config/config.yml` and `e2e-tests/config/config-docker.yml`:
  configure Alice's authority URL, trust pin, and admin signer.
- `e2e-tests/tests/e2e/roles/scenarios/vms/test_multi_registry.py`: seed each
  authority using typed clients, refresh both projections, remove local CSV
  seeding and negotiation skips, and assert independent negotiation results.
- `scripts/tests/test_multi_storefront_compose.py`: render Compose and prove
  identity, callback, dependency, and state isolation across the two services.
- Validate the rendered topology, collect the scenario, run the multi-registry
  scenario and relevant full end-to-end pipeline, then run comment hygiene,
  documentation citations, and `make check-packaging`.
- Permanent destinations after code review: development identity provenance in
  `dev-env/identities/README.md`, topology in deployment docs, scenario coverage
  in testing docs, and the reconciled Goal 1 gap in the roadmap. No new service
  authentication contract is introduced.

- [x] 2.1 Select separate provisioning services for Alice and Bob. Each
      authority retains one storefront counterparty; multiple storefronts per
      site and reuse of rotation overlap for independent sellers are excluded.
- [x] 2.2 Wire Alice's separate provisioning service with isolated state,
      authority identity, storefront trust, and callback destination.
- [x] 2.3 Configure Alice to trust and call her authority using the existing
      identity protocol; retain Bob's separate authority binding.
- [x] 2.4 Remove explicit `06b`/`06c` skips and demonstrate the complete
      two-storefront scenario passing, checking the runtime skip set.
- [x] 2.5 Seed Alice's inventory through her authority in
      `e2e-tests/tests/e2e/roles/scenarios/vms/test_multi_registry.py` and remove
      the local-derivation opt-out from
      `domains/vms/storefront/storefront.alice.toml`. Verify projection-backed
      listings before considering the pools-9 prerequisite complete.

## 3. Closeout

- [x] 3.1 **Comment hygiene.** `make check-comment-hygiene`.
- [x] 3.2 **Import placement.** Added client imports are module-level; moved
      the touched storefront-client imports to module scope and verified live.
- [ ] 3.3 **Documentation compliance.** Promote development topology to
      `docs/development/DEPLOYMENT_AND_CONFIG.md` and scenario coverage to
      `docs/development/TESTING.md` after code review.
- [x] 3.4 **Narrative compression.** Replaced obsolete shared-authority
      discussion with the accepted topology and concise containment history.
- [ ] 3.5 **Roadmap currency.** Reconcile Goal 1's gap with the accepted
      separate-authority scope; do not claim shared-site substitution or leave
      a resolved gap pointing at an archived change.
- [x] 3.6 **Campaign index currency.** Index records passing validation and
      review/promotion pending; pools-9 remains gated on closeout.
- [ ] 3.7 **Promotion.**

- [x] 3.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=repair-multi-storefront-scenario` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
- [x] 3.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
- [x] 3.10 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads
      the root declaration.
## Validation evidence

- Deployment contracts: 25 passed across multi-storefront, hosted Compose,
  and hosted run-target tests.
- Focused Docker multi-registry scenario: 21 passed, 381 deselected, no skips
  (2026-10-01). Both authorities accepted provisioning seed requests, both
  storefronts loaded projections, and both negotiations reached round-0 counters.
- Packaging, comment hygiene, scoped documentation citations, and whitespace
  checks pass. Strict OpenSpec CLI validation remains unrun: CLI unavailable.
- Full local pipeline on 2026-10-01:
  `make -C e2e-tests test-e2e NETWORK=simple-compute-market_default` passed:
  VM/API-credit lane 127 passed, 275 deselected; bare-metal lane 11 passed,
  391 deselected; no skips. This is local pipeline evidence, not a CI run.
- Final focused run after correcting Alice's database environment prefix and
  removing an unused Redis service: 21 passed, 381 deselected, no skips.
- The checkout's Compose project name requires a matching `NETWORK` argument;
  the first focused runner attempt failed before collection using its stale
  default network name. No product failure was involved.
- Permanent topology/coverage promotion remains pending post-code-review.
  Development credential provenance is already documented alongside its fixture.

## Design promotion record

| Accepted decision | Permanent location | Status |
|---|---|---|
| Alice and Bob each use their own provisioning authority | `docs/development/DEPLOYMENT_AND_CONFIG.md` | Prepared in design; post-review promotion pending |
| Scenario evidence covers registry behavior and negotiations, not shared-site tenancy | `docs/development/TESTING.md`; `docs/development/ROADMAP.md` | Coverage text prepared; roadmap gap scope reconciled, final closeout pending |
| Public deterministic authority credential | `dev-env/identities/README.md` | Documented with fixture |
| Review readiness and pools-9 prerequisite gate | `openspec/changes/README.md` | Current |
