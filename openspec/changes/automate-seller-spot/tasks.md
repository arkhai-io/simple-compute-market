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
