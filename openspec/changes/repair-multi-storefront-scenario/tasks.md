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

## 2. Let provisioning serve more than one storefront

- [ ] 2.1 Decide whether a storefront principal implies a site binding.
      `ProvisioningIdentityContext` holds `storefront_principal` and
      `storefront_site_id` as single values; both have to become plural, and
      whether they are paired or configured independently is the design
      question.
- [ ] 2.2 Configure a set of storefront principals, bootstrapping each into the
      `seller` role. The authority already trusts several principals per role
      during rotation, so this is a configuration shape rather than a trust
      model change.
- [ ] 2.3 Add Alice's principal to the development compose identities.
- [ ] 2.4 Remove the skips and confirm the four stages pass.

## 3. Closeout

- [ ] 3.1 **Comment hygiene.** `make check-comment-hygiene`.
- [ ] 3.2 **Import placement.**
- [ ] 3.3 **Documentation compliance.** Goal 1's open-gap row is this change's
      one permanent edit; confirm it still reads true at archival, and remove
      the row rather than leaving it pointing at an archived change.
- [ ] 3.4 **Narrative compression.**
- [ ] 3.5 **Roadmap currency.** Goal 1's current-state paragraph should stop
      describing a storefront as substitutable only in principle.
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
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The provisioning service cannot presently serve two storefronts | ROADMAP Goal 1 open-gap table |
