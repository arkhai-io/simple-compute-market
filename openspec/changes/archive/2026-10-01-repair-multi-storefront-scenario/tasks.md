# Tasks — repair-multi-storefront-scenario

## Implementation status

**Implementation and post-review promotion complete.** Separate authorities are
implemented; the accepted discovery contract and development scenario are
documented in their permanent owners.

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

## 2a. Accepted review corrections

- [x] 2a.1 In `e2e-tests/tests/e2e/roles/scenarios/vms/test_multi_registry.py`,
  replace test-local fan-in with `core_buyer.orchestrator.query_registry_for_matches_multi`.
  Expect Bob at each independent authority and Alice only at A; configure the
  unreachable endpoint's trust binding and observe its connection failure.
- [x] 2a.2 In the same scenario, use `SyncRegistryClient.get_listing` for
  presence/absence and assert the typed error's status for the expected 404.
- [x] 2a.3 Correct Redis comments in `domains/vms/compose.yml`; retain the
  existing service without describing it as provisioning's job queue.
- [x] 2a.4 Extend `core/buyer/tests/unit/test_orchestrator.py` to distinguish
  same-authority mirrors from unrelated authorities. Correct the description
  in `domains/vms/buyer/src/arkhai_vms_buyer/buy_cli.py`,
  `domains/vms/buyer/src/arkhai_vms_buyer/listing_cli.py`,
  `docs/buyer-quickstart.md`, and `docs/roles.md`.
- [x] 2a.5 Record authority-scoped discovery in
  `openspec/specs/registry-discovery/spec.md` and its architecture companion;
  amend the prepared testing text in this change. Cross-authority advertisement
  equivalence remains separate future design work.
- [x] 2a.6 Run the buyer suite, focused multi-registry scenario, full local
  end-to-end target, then packaging, comment hygiene and citation checks.
  Earlier green scenario results did not prove production fan-in behavior.

## 3. Closeout

- [x] 3.1 **Comment hygiene.** `make check-comment-hygiene`.
- [x] 3.2 **Import placement.** Added client imports are module-level; moved
      the touched storefront-client imports to module scope and verified live.
- [x] 3.3 **Documentation compliance.** The development topology is in
      `docs/development/DEPLOYMENT_AND_CONFIG.md`, scenario coverage is in
      `docs/development/TESTING.md`, and authority-scoped buyer discovery is
      in `openspec/specs/registry-discovery/{spec,architecture}.md`.
- [x] 3.4 **Narrative compression.** Replaced obsolete shared-authority
      discussion with the accepted topology and concise containment history.
- [x] 3.5 **Roadmap currency.** Goal 1 records the separate-authority
      evidence and its shared-site limit; the resolved repair gap is removed.
      The independent pools-9 retirement gap remains.
- [x] 3.6 **Campaign index currency.** The repair is implemented and the
      pools-9 prerequisite is recorded as satisfied.
- [x] 3.7 **Promotion.** Decisions and validation boundaries are recorded in
      the permanent destinations listed below.

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

- Buyer unit suite: 126 passed, covering same-authority mirrors and independent
  authorities with equal listing IDs.
- API-credit buyer suite: 17 passed, including CLI help construction after both
  descriptions were corrected.
- Deployment contract suites: 25 passed.
- Full local end-to-end pipeline on 2026-10-01:
  `make -C e2e-tests test-e2e NETWORK=simple-compute-market_default` passed.
  VM/API-credit lane: 127 passed; bare-metal lane: 11 passed; no skips.
  The 21-stage multi-registry scenario passed. Phase 4 used typed registry
  reads, Phase 5 exercised production buyer fan-in, and the remaining stages
  covered separate provisioning authorities, projections, publication, and
  negotiations. This is local pipeline evidence, not a CI run.
- `make check-packaging`, comment hygiene, scoped documentation citations,
  citations in touched permanent documents, and whitespace checks passed.
  Strict OpenSpec CLI validation was unavailable in this environment.

## Design promotion record

| Accepted decision | Permanent location | Status |
|---|---|---|
| Alice and Bob each use their own provisioning authority | `docs/development/DEPLOYMENT_AND_CONFIG.md` | Promoted |
| Scenario evidence covers registry behavior and negotiations, not shared-site tenancy | `docs/development/TESTING.md`; `docs/development/ROADMAP.md` | Promoted; resolved roadmap gap removed |
| Public deterministic authority credential | `dev-env/identities/README.md` | Documented with fixture |
| Implemented status and satisfied pools-9 prerequisite | `openspec/changes/README.md` | Current |
| Buyer discovery identity and failure scope | `openspec/specs/registry-discovery/spec.md`; `openspec/specs/registry-discovery/architecture.md`; `docs/buyer-quickstart.md`; `docs/roles.md` | Promoted existing production behavior |
| Shared buyer CLI discovery descriptions | `domains/vms/buyer/src/arkhai_vms_buyer/{buy_cli,listing_cli}.py`; `domains/apicredits/buyer/src/arkhai_apicredits_buyer/{buy_cli,listing_cli}.py` | Aligned with authority-scoped discovery |
