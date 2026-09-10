# Explicit general declaration chart enrollment

## Why

The bare-metal storefront supports strict general declaration startup publication,
but its chart exposes only historical synthetic publication. Operators need an
explicit reference-only hook without changing existing rendered manifests.

Public scope: https://github.com/arkhai-io/simple-compute-market/issues/225 and
https://github.com/arkhai-io/simple-compute-market/issues/221.

## What changes

Add default-null `contactDeclarations` alongside mutually exclusive `contactOffers`.
Reuse public ConfigMap and separate registry trust/write-key references, contact-only
site exclusion, persistent storage guards and startup allowance. Keep delivery
configuration independently Secret-backed. Preserve complete historical render bytes.

No Python runtime/carrier changes, release pins, physical integration, publication,
deployment, SMTP or credential operations are part of this chart amendment.

## Permanent documentation impact

- [ ] Existing `storefront-publication` specification and architecture: explicit
  chart enrollment, strict runtime ownership and compatibility.
- [ ] `docs/development/DEPLOYMENT_AND_CONFIG.md`: value/reference/mount contract.
- [ ] `openspec/changes/README.md`: bounded amendment index entry after review.

Permanent changes are proposed separately for post-review promotion. Repository-wide
architecture and roadmap goals do not change; this only exposes an existing runtime
capability. Historical qualification and completed changes remain intact.
