# Implementation Tasks

## 1. Released consumer boundary

- [x] 1.1 Pin and verify hosted release `0.1.0`: manifest
  `3f9bb7ab579fdc5388b97d7bbf28d4cb647e0b5f2bc40eb8f4ec93d8083d1da7`,
  client wheel
  `82a1493adb10536ce8c234251ece9128e3cb95817a2230d10a04e6a2444438ca`,
  image
  `sha256:3c88f345f0c9aed22348ec8ec9ae89eefd73a2f5ccbcbece60841298ed9be44b`,
  API `0.1.0`, schema `3`, capabilities, provenance, SBOM, repository/workflow,
  source revision, and signer without an editable sibling dependency.
- [x] 1.2 Add byte-compatible settlement option/selection carriers, typed hosted
  condition and fulfillment projections, constrained buyer candidates, and the
  thin `fiat.stripe.v1` adapter over the released signed client.

## 2. Marketplace lifecycle

- [x] 2.1 Extend shared obligation persistence and servicing with opaque hosted
  references, public action metadata, condition anchors, restart-safe CAS
  ordering, fulfillment-first collection, and refund-before-capacity-release.
- [x] 2.2 Publish and exact-match hosted VM options, preflight the configured
  authority, derive accepted obligations server-side, expose identifier-only
  start/status/reclaim routes, and preserve the legacy Alkahest route and rows.
- [x] 2.3 Add the buyer mechanism/asset selection and transient Checkout action
  flow while preserving interactive authority, legacy defaults, run-log
  compatibility, API-credit behavior, and bare-metal verified-only behavior.

## 3. Packaging and deployment

- [x] 3.1 Ship only the released client and thin adapter in marketplace wheels
  and the VM storefront image; update locks, reinit/build/review/publish paths,
  Compose, Helm consumer settings, and signed-release startup verification.
- [x] 3.2 Keep Stripe, EVM resolution, migrations, provider identities,
  credentials, webhooks, and financial recovery exclusively in the hosted
  authority repository; render no hosted service workload in marketplace Helm.

## 4. Evidence and closeout

- [x] 4.1 Verify the released fake-provider success and refund flows across
  built wheels: one full transfer on success and one full pre-transfer refund
  with no transfer on failure; verify signed response serialization and
  immutable image readiness through the composed marketplace topology.
- [x] 4.2 Pass core (68), kit aggregate, hosted adapter (5), VM buyer (162),
  VM storefront (980 passed, 1 skipped), API-credit, bare-metal (60),
  packaging/release-signature, comment-hygiene, and targeted strict OpenSpec
  checks. Repository-wide strict OpenSpec remains nonzero only for six unrelated
  pre-existing active changes.
- [x] 4.3 Verify supplied Stripe credentials as non-live and record the
  authoritative external blocker without simulated evidence: the platform has
  no connected accounts and Connect is not enabled, so connected-account
  transfer/refund cannot run; no reachable webhook, Kubernetes cluster,
  supported EAS testnet endpoint/funded signer, or protected publisher
  permission was provided.
- [x] 4.4 Promote durable behavior and rationale to the owning permanent specs,
  architecture, deployment, release, roadmap, and authoring documentation;
  complete comment/import hygiene, the design-promotion record, and archive.
