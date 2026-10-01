# Tasks — repair-multi-storefront-scenario

## Implementation status

**Not started.** The blocked stages are skipped with their reason recorded; no
product change yet. Opened by `repair-storefront-alkahest-configuration`, whose
scope ends at the e2e fixtures.

## 1. Declare the limitation

- [x] 1.1 Skip `test_06b_buyer_starts_negotiation_with_alice` and
      `test_06c_negotiations_are_distinct_objects_on_distinct_storefronts` with
      a reason naming the single storefront principal, ROADMAP Goal 1, and this
      change.
- [x] 1.2 Leave the registry stages running. Alice's registry path does not
      depend on provisioning, and those stages are the scenario's subject.
- [ ] 1.3 **Confirm the skip set after the next run.** `00g` reads system
      status only and `02b` imports a storefront-local CSV, so both are
      expected to pass — but neither has been observed passing, because the
      whole scenario was skipped until this week. Widen the skip set only on
      evidence, and record any other failure as a finding rather than folding
      it into this limitation.

## 2. Give each storefront its own provisioning authority

Design accepted; expand these tasks with exact affected files and focused
validation during planning, before implementation.

- [x] 2.1 Select separate provisioning services for Alice and Bob. Each
      authority retains one storefront counterparty; multiple storefronts per
      site and reuse of rotation overlap for independent sellers are excluded.
- [ ] 2.2 Wire Alice's separate provisioning service with isolated state,
      authority identity, storefront trust, and callback destination.
- [ ] 2.3 Configure Alice to trust and call her authority using the existing
      identity protocol; retain Bob's separate authority binding.
- [ ] 2.4 Remove explicit `06b`/`06c` skips and demonstrate the complete
      two-storefront scenario passing, checking the runtime skip set.
- [ ] 2.5 Seed Alice's inventory through her authority in
      `e2e-tests/tests/e2e/roles/scenarios/vms/test_multi_registry.py` and remove
      the local-derivation opt-out from
      `domains/vms/storefront/storefront.alice.toml`. Verify projection-backed
      listings before considering the pools-9 prerequisite complete.

## 3. Closeout

- [ ] 3.1 **Comment hygiene.** `make check-comment-hygiene`.
- [ ] 3.2 **Import placement.**
- [ ] 3.3 **Documentation compliance.** Promote development topology to
      `docs/development/DEPLOYMENT_AND_CONFIG.md` and scenario coverage to
      `docs/development/TESTING.md` after code review.
- [ ] 3.4 **Narrative compression.**
- [ ] 3.5 **Roadmap currency.** Reconcile Goal 1's gap with the accepted
      separate-authority scope; do not claim shared-site substitution or leave
      a resolved gap pointing at an archived change.
- [ ] 3.6 **Campaign index currency.**
- [ ] 3.7 **Promotion.**

- [ ] 3.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=repair-multi-storefront-scenario` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
- [ ] 3.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
- [ ] 3.10 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads
      the root declaration.
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Alice and Bob each use their own provisioning authority | `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Scenario evidence covers registry behavior and negotiations, not shared-site tenancy | `docs/development/TESTING.md`; `docs/development/ROADMAP.md` |
