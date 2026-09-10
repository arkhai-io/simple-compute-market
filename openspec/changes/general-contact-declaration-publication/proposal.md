# Opt-in general contact declaration publication

Issue: https://github.com/arkhai-io/simple-compute-market/issues/223

## Why

Operators need to publish contact-only machine declarations, including third-party machine facts, without claiming physical authority. The strict declaration and immutable source carriers already exist; the operator publication surface does not.

## What changes

Add `publish-declarations --offers PATH` and opt-in startup configuration for the schema-3 general carrier. Validate the entire bounded file, configured contact profile and privacy, signed registry schema and existing listing identities before listing writes or registry POSTs. Preserve synthetic v1/v2 inputs, physical publication and immutable historical intent.

This work uses disposable local fixtures only. It adds no capacity admission, provisioning adapter, automatic withdrawal, backfill, deployment or release.

## Permanent documentation impact

- [ ] `openspec/specs/storefront-publication/spec.md`: general publication, preflight, identity and retry requirements.
- [ ] `openspec/specs/storefront-publication/architecture.md`: declaration publication rationale and authority boundary.
- [ ] `docs/development/DEPLOYMENT_AND_CONFIG.md`: additive command, environment opt-in and exact public notice.
- [ ] `openspec/changes/README.md`: new change row and dependency state after independent review.

Permanent edits are proposed for separate review; promotion is not complete in this candidate.
