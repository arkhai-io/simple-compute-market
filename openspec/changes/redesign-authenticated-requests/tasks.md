# Tasks

## Status

Design phase; not planned. Section 1 holds the decisions `design.md` owes; each is a
gate, recorded with its reasoning in `design.md` before planning begins. Implementation
sections, and the closeout task `openspec/README.md` requires, are written once the
gates are settled.

## 1. Decision gates

- [ ] 1.1 Decide where the shared replay contract and store implementation live, given
      that the storefront, registry, provisioning service, and site authorities all use
      them, and record it with the package-layer reasoning.
- [ ] 1.2 Decide how a route declares how an exact retry is resolved — re-run or
      recorded outcome — what an undeclared route defaults to, and how a test proves a
      route declared re-runnable really converges.
- [ ] 1.3 Decide the reservation horizon: derived from the skew bound and lease or
      configured, and where and how pruning runs.
- [ ] 1.4 Decide how long a retained outcome lives and what an exact retry receives
      once it has expired, given that silently re-running is wrong for exactly those
      routes.
- [ ] 1.5 Decide the migration of existing rows, whose recorded bodies cannot be
      attributed to an operation or resource.
- [ ] 1.6 Decide the restated `marketplace-identity` exact-reuse requirement, so that
      re-running an idempotent route and refusing an expired outcome both conform.
      Consume/generalize unify-compute-delivery-path's route retry declaration, preserving
      all retained marketplace-identity clauses/scenarios (reservation, first-use skew,
      changed reuse, request/response signing, credential re-run/live admission/no-body,
      same-operation mutation retry and credential purge). Archive unify first; re-diff
      as supersets against current specs if order changes.
- [ ] 1.7 Decide the disposition of `retain-authenticated-request-outcomes`:
      superseded, narrowed, or folded in. Update its status and the campaign index
      accordingly.
