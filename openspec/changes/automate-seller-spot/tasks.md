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

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 5.1 **Comment hygiene.** Run `make check-comment-hygiene`, then direct-read the comments and docstrings this change touches for the fuzzier provenance-narration rule the target cannot catch mechanically.
- [ ] 5.2 **Import placement.** Review every import this change adds or touches and move it to module level where safe; retain a local import only against an observed circular import or a documented lazy-load reason, verified against the real suite.
- [ ] 5.3 **Documentation compliance.** Re-check this change's accepted decisions against `openspec/README.md`'s placement rules. It carries delta specs for `settlement-servicing`, `site-capacity`, `storefront-publication`; confirm each landed in the owning `openspec/specs/<capability>/spec.md`, and that durable conceptual rationale sits in the companion `architecture.md` rather than only in `design.md`.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations, moving durable rationale into `design.md` first.
- [ ] 5.5 **Roadmap currency.** This change sits under the lesser goal “Settlement and deal servicing depth”, which has no roadmap goal behind it, so it most likely owes `docs/development/ROADMAP.md` nothing. Confirm that and record the no-impact disposition explicitly rather than omitting the step.
- [ ] 5.6 **Campaign index currency.** Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md` to match its state at completion, or record the disposition here if its status and campaign placement are both unchanged.
- [ ] 5.7 **Promotion.** Add a design-promotion record, mapping every accepted decision to its exact permanent heading, and verify no production source references `openspec/changes/automate-seller-spot`.
