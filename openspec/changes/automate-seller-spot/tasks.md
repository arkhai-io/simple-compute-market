## 1. Residual API and evidence model

- [ ] 1.1 Inventory existing interruptible publication/evaluation/truncation endpoints and exact authoritative identifiers.
- [ ] 1.2 Design durable decision and resumable operation records with migrations, redaction, version checks, and idempotency.
- [ ] 1.3 Add active interruptible-agreement view and typed client models/methods with HTTP contract tests.
- [ ] 1.4 Persist and project both dry-run and live decision evidence without treating stage events as sole authority.

## 2. Settlement and lifecycle execution

- [ ] 2.1 Implement deterministic split calculation/validation from accepted settlement terms.
- [ ] 2.2 Submit/reconcile splitter declarations idempotently with transaction/receipt persistence and retry tests.
- [ ] 2.3 Model truncation, teardown, release, and settlement as separate resumable steps with partial-failure repair.
- [ ] 2.4 Revalidate authoritative versions/state before every live mutation.

## 3. Reference runner

- [ ] 3.1 Add public-API-only strategy/runner interfaces, configuration, dry-run default, and one reference policy.
- [ ] 3.2 Add controlled scheduling, concurrency, restart, stale-decision, auth, redaction, and manual-repair tests.

## 4. Verify and promote

- [ ] 4.1 Run storefront, client, settlement, site/fulfillment, migration, packaging, and end-to-end interruption suites.
- [ ] 4.2 Promote control/evidence to `storefront-publication`, split execution to `settlement-servicing`, and authority separation to `site-capacity` specs/architecture companions.
- [ ] 4.3 Record promotion in `design.md`, update operator guidance after behavior is proven, and run strict validation before archive.
- [ ] 4.4 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 5.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
- [ ] 5.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 5.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe. Durable conceptual rationale for
      `settlement-servicing`, `site-capacity`, and `storefront-publication` sits in
      the companion `architecture.md` rather than only in `design.md`, and no
      production source references `openspec/changes/automate-seller-spot`.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 5.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
      Expected: no goal is affected, since this change sits under the lesser goal
      “Settlement and deal servicing depth”, which has no roadmap goal behind it;
      confirm and record that disposition explicitly.
- [ ] 5.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 5.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 5.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change (the end-to-end
      interruption suites of 4.1), or an explicit blocker naming its cause and the
      change that owns it, with the validations it gates treated as unrun.
- [ ] 5.9 **Promotion.** Write the permanent documents this change owes — the
      `storefront-publication` (control and evidence), `settlement-servicing` (split
      execution), and `site-capacity` (authority separation) architecture companions,
      and the operator guidance once behavior is proven (4.3) — and complete the
      design-promotion record, mapping every accepted decision to its exact permanent
      heading. A `spec.md` the deltas cover (`settlement-servicing`, `site-capacity`,
      `storefront-publication`) is written by the archive in 5.11, not by hand; the
      record names it all the same.
- [ ] 5.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=automate-seller-spot` and resolve every match,
      then `openspec validate automate-seller-spot --strict`.
- [ ] 5.11 **Archival.** Last, once every other part is checked: `openspec archive
      automate-seller-spot -y` merges the deltas into `openspec/specs/` and moves the
      change under `openspec/changes/archive/`; point the index row at the archived
      directory, and run `openspec validate --specs --strict`.
