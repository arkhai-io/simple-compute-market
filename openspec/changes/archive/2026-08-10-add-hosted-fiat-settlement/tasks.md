# Implementation Tasks

## 1. Released consumer boundary

- [x] 1.1 Pin and verify hosted release `0.1.0`: manifest
  `ded5117d39dc38cd365d5502011ae65e6b4714b44c0dc1afe8b616a1bbae615a`,
  client wheel
  `354c99691aa99e22792a900ab7bb4137e101a27d0c90be9973f5fdafb999fe80`,
  image
  `sha256:3aea49495b272745f5b9c9171cf5550565ef8387462969c9eee48f0cd3035d36`,
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
- [x] 4.3 Record unavailable external checks without simulated evidence:
  deployed Helm (no cluster/credentials), Stripe test transfer/refund and
  reachable webhook (no credentials/endpoint), supported EAS testnet evidence
  (no RPC/EAS endpoint or funded signer), and protected publisher workflow
  execution (no release permission).
- [x] 4.4 Promote durable behavior and rationale to the owning permanent specs,
  architecture, deployment, release, roadmap, and authoring documentation;
  complete comment/import hygiene, the design-promotion record, and archive.
