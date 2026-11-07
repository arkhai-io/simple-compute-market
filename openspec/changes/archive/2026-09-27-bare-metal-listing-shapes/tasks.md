# Tasks — bare-metal listing shapes

Complete. Implemented, validated end to end, promoted, and archived. The pool-override
work moved to `publish-indicative-listing-rates` (its section 3b), and sections 3 and
7 remain only as markers of that move. Design, review, and debugging rationale is in
`design.md`.

## 1. Design

- [x] 1.1 Open questions decided: the compute-family schema, one close and republish,
      the nested `capabilities` mapping retired, and overrides carrying clauses and
      terms only.
- [x] 1.3 Decisions audited against the code:
      - `domains/compute` package;
      - `unflatten_shape`;
      - the shape derived from declared capacity and attributes, requiring `gpu` and
        one `units`;
      - the shape digest in derivation identity;
      - claim attributes;
      - region from the pool hint;
      - a minimal opening guard;
      - the bare-metal `pool-override` command, since moved out.
- [x] 1.2 Planned. The decisions taken while planning are in `design.md`: the durable
      accepted generation (since moved out), the payload kind, explicit listing
      fields, the envelope version, resource-first reconciliation,
      `list --resource`, and the flat test layout.
- [x] 1.4 Design review resolved:
      - the VM commitment scoped to VM;
      - the guard as a domain function, landing before
        `bare-metal-and-credits-domain-stacks` §4a;
      - the override work moved to `publish-indicative-listing-rates`.

## 2. Compute-family schema and the shape utility

- [x] 2.1 `kit/capability-shape`: `unflatten_shape`, the exact inverse of
      `flatten_shape` (0.2.0).
- [x] 2.2 Tests: round trip, digest equality, and refusals.
- [x] 2.3 `domains/compute` (`arkhai-compute` 0.1.0): `COMPUTE_CAPABILITY_SCHEMA` and
      the flat constants; standard library plus the capability-shape kit only.
- [x] 2.4 Its schema and import-boundary tests.
- [x] 2.5 `arkhai_vms` re-exports it as `VM_CAPABILITY_SCHEMA` (0.5.0).
- [x] 2.6 Evidence: capability-shape 38, compute 6, and VM domain 38 passed.

## 3. Pool-override kit route service — moved

Moved to `publish-indicative-listing-rates` section 3b.

## 4. Bare-metal domain: listing, derivation, classification, identity

- [x] 4.1 `BareMetalListing` publishes `region` and the schema's flat fields, forbids
      extras, and derives `shape` and `shape_digest`.
- [x] 4.2 `TrustedBareMetalResource` carries the declared capacity and attributes.
- [x] 4.3 `shapes.py`: `derive_bare_metal_shape`, which requires one `units`,
      schema-only quantities, positive integers, and a GPU count and model.
- [x] 4.4 Listings are built from the derived shape and the pool region.
- [x] 4.5 Classification holds a region-less pool and an unreadable declaration.
      Candidates and source identity carry the digest, and the identity fields are
      updated.
- [x] 4.6 Fixtures put hardware in declared capacity and attributes.
      `fixtures/listing.py` is added for consumers.
- [x] 4.7 Dependencies and reinit (0.6.0).
- [x] 4.8 Tests: `test_shapes.py`, `test_schema.py`, `test_publication.py`,
      `test_projections.py`, `test_storefront_publication.py`, and
      `test_inventory_guard.py`.
- [x] 4.9 Provisioning service suites pass unchanged: the site still copies
      `capabilities` into the view, and consumers ignore it.
- [x] 4.10 Evidence: bare-metal domain 131 passed. `pool_region` lives in the
      storefront, so the domain package does not depend on `kit/resource-pools`.

## 5. Bare-metal storefront: publication

- [x] 5.1 The derivation key includes the shape digest, taken from the listing's own
      shape, and the source envelope is version 2.
- [x] 5.2 `site_reading.py` reads admission, region, and `listing_shapes` for
      publication and the guard. The cycle holds and reports region-less pools and
      unreadable declarations, reports ignored `capabilities`, and matches bindings
      by resource before key.
- [x] 5.5 Tests: a correction publishes a successor; a legacy key closes as
      `source_gone`; the holds and reports; the envelope and key persistence.

## 6. Bare-metal storefront: claims and the opening guard

- [x] 6.1 `claims.py`: one whole-machine claim for both reservation paths, with
      `units: 1` and the trusted listing's `claimed_attributes`.
- [x] 6.2 `recheck_bare_metal_listing_source`, a pure domain function over
      classification.
- [x] 6.3 `opening_guard.py` fetches the bound site's projection. `open()` calls it
      once, before the Alkahest and hosted paths branch: a mismatch or absence is
      refused with 409, an unconfirmable source with 503.
- [x] 6.4 Tests:
      - the claim's construction (`test_fulfillment_service.py`) and its admission
        semantics, run through `kit/site`'s `dict_resource_satisfies_claim`
        (`test_claims.py`);
      - every guard outcome over HTTP, including the hosted path.

## 7. Bare-metal storefront: overrides — moved

Moved to `publish-indicative-listing-rates` section 3b. Retained here:

- [x] 7.5 The storefront at 0.6.0, with its pins, reinit, and Dockerfile.
- [x] 7.6 The domain package's import-boundary test (no VM import) replaces the
      planned storefront assertion.

## 8. Bare-metal buyer

- [x] 8.1 `bare-metal list --resource`, compiled through `compile_resource_query`
      with the specification's ETag. The fulfillment transport gains `begin()`
      (0.3.1).
- [x] 8.2 Tests: compilation, ETag, and refusal of an undeclared field. Buyer 14
      passed.

## 9. Combined shell and remaining consumers

- [x] 9.1 VM storefront pins and lock. VM storefront 1,334 passed. Two Alkahest
      integration tests could not start a local chain in either environment and are
      unrun.
- [x] 9.2 Consumers relocked, with `arkhai-compute` added to their reinit. VM buyer
      196 passed.

## 10. Build, packaging, and reinit

- [x] 10.1 `dist-compute` and `test-compute` targets.
- [x] 10.2 Wheel contents checked.
- [x] 10.3 `py.typed` is shipped. Unrun: no type check is configured for these
      packages (only `core/` configures one).
- [x] 10.4 `make check-reinit` passes. `make check-internal-locks` is added and passes
      (R.3).

## 11. End-to-end and operator documentation

- [x] 11.1 The publication scenario declares hardware in `capacity` and `attributes`,
      discovers the listing by `gpu_model`, `gpu_count`, and `region` (and not by
      `gpu_count>=9`), and holds a region-less pool.
- [x] 11.2 `test_bare_metal_deal.py` builds no declaration; unchanged.
- [x] 11.3 `docs/bare-metal-seller-quickstart.md`: registration and round behaviour.
- [x] 11.4 `bare-metal-mock-provisioned-deal`'s design carries the declaration,
      settlement, and fulfillment-start context.

## Review follow-ups

- [x] R.1 6.4's evidence corrected, and site-matcher contract tests added.
- [x] R.2 Status line corrected.
- [x] R.3 Stale internal pins fixed across eight consumer locks.
      `make check-internal-locks` added.
- [x] R.4 VM buyer and VM storefront relocked.
- [x] R.5 The raw-HTTP tests this change touched use typed clients over the in-process
      app: `StorefrontClient` over `httpx.ASGITransport`, and the production buyer's
      clients over `tests/loopback.py`.
      - Interim: `arkhai-bare-metal-buyer` is a dev-only test dependency. Each
        client moving into the package that owns its route is a need in
        `kit-owned-storefront-shell`.
      - Hand-built requests remain only for rejection paths and for one marked
        debt, the seller-role introduction read.
      - Defects fixed:
        - four routes verified a re-serialized body; they now verify the body sent;
        - negotiation reads were unauthenticated; they now require the
          administrator's signed contract;
        - `/fulfillments/begin` had no typed client.
- [x] R.7 `negotiate_new(selection_only=True)` for selection-only openings, with one
      shared proposal builder for both clients.
- [x] R.8 E2E debugging: stale client pins, and the registry list model's `id`.
- [x] R.9 Settlement restates no negotiated term, in both domains. Fulfillment starting
      on settlement is decided and owned by `bare-metal-mock-provisioned-deal`.
      Canonical client 0.22.0 (44 passed).

## 12. Closeout

- [x] 12.1 **Comment hygiene.** `make check-comment-hygiene` passes. A direct read of
      the touched production files finds no provenance.
- [x] 12.2 **Import placement.** New imports are module-level. The one touched local
      import, `from .common import resolve_buyer_wallet` in the VM buyer's
      `settle_cli.py`, stays local. Moving it was attempted: it failed
      `test_alkahest_resume_settles_without_restating_negotiated_terms`, which
      patches `common.resolve_buyer_wallet` and needs the call-time lookup.
- [x] 12.3 **Documentation compliance.** Each accepted decision's destination is in the
      record below:
      - normative rules in `spec.md`;
      - rationale in `architecture.md`;
      - the layer, the commitment models, and the authority row in
        `ARCHITECTURE.md`;
      - bare-metal declaration authoring requirements only in
        `DEPLOYMENT_AND_CONFIG.md`, linking to the storefront-publication
        specification for what publication does with them.
      Amended after closeout review. The first promotion also restated
      publication, hold, and claim behaviour in the deployment guide, which owns
      configuration authoring rather than storefront semantics. That behaviour is
      specified once, in `storefront-publication`.
- [x] 12.4 **Narrative compression.** This file is reduced to behaviour, evidence,
      deferrals, and destinations.
- [x] 12.5 **Roadmap currency.** Goal 7's gap row is closed and its current state
      rewritten. Goal 1–2's vocabulary gap now names the shared compute-family
      names.
- [x] 12.6 **Campaign index currency.** This change is archived. The Goal 7 graph and
      critical path mark it done. `publish-indicative-listing-rates` and
      `unbacked-bare-metal-listings` are unblocked on it, and the rates row names
      the override adoption it owns. `settle-capacity-claim-vocabulary`'s gate
      edits `arkhai_compute`. §4a follows this change and calls its guard function.
      `bare-metal-mock-provisioned-deal` owns fulfillment-start convergence.
- [x] 12.7 **Documentation citations.**
      `make check-doc-citations CHANGE=bare-metal-listing-shapes` passes.
- [x] 12.8 **End-to-end pipeline.**
      [Run 36318761586](https://github.com/arkhai-io/simple-compute-market/actions/runs/36318761586)
      at `abac9266` passed both lanes:
      - bare metal: 8 passed, including discovery by hardware (stage 03b), withdrawal
        and reinstatement, and the region hold (stage 06);
      - VM: 126 passed and 2 existing skips, including `test_listing_shapes.py` on
        the shared schema, and VM settlement without the echoed terms.
- [x] 12.9 **Promotion.** Complete; see the record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The compute-family schema has one owner, `domains/compute`, a family vocabulary layer between the kit and the domains | `openspec/specs/market-composition/spec.md` ("The compute family shares one capability schema"); `openspec/specs/market-composition/architecture.md#the-compute-family-vocabulary`; `docs/development/ARCHITECTURE.md#repository-layers` |
| `unflatten_shape` is the exact inverse of `flatten_shape` | `openspec/specs/market-composition/spec.md` ("Family-grouped capability shapes share one flattening contract") |
| A bare-metal listing's shape is derived from its declaration; `units` exactly one and `gpu` required; publication-only data is not a source | `openspec/specs/storefront-publication/spec.md`; `openspec/specs/storefront-publication/architecture.md#bare-metal-listing-shapes` |
| Bare-metal declaration authoring requirements: `units: 1`, compute-family capacity names, `gpu_model` attribute, pool `region`, no hardware in `bare_metal_publication` | `docs/development/DEPLOYMENT_AND_CONFIG.md#capacity-definitions`, which links to the specification for their effect |
| Shape fields published top-level under compute flat names; region from the pool hint, held when absent | `openspec/specs/storefront-publication/spec.md` |
| Derivation identity includes the shape digest; old keys close as `source_gone` | `openspec/specs/storefront-publication/spec.md`; its `architecture.md#bare-metal-listing-shapes` |
| One whole unit held exclusively; the claim requires the shape's attributes | `openspec/specs/storefront-publication/spec.md`; `docs/development/ARCHITECTURE.md#storefront-capacity-boundary` |
| Opening rechecks shape and region through a domain function over classification | `openspec/specs/storefront-publication/spec.md`; its `architecture.md#bare-metal-listing-shapes` |
| The VM commitment rule is VM's | `openspec/specs/storefront-publication/spec.md` (MODIFIED "Every VM listing is a listing shape"); `docs/development/ARCHITECTURE.md#storefront-capacity-boundary` |
| A settlement request restates no negotiated term, in every domain | `openspec/specs/storefront-publication/spec.md` (MODIFIED "Seller protocol surface") |
| Negotiation routes verify the body the caller sent; bare-metal negotiation reads require the administrator's signed contract | Conformance to the existing authorization requirements, now tested through the canonical client; no new rule |
| `negotiate_new(selection_only=True)` | The canonical client's docstring; no permanent specification rule |
| `make check-internal-locks` | `Makefile` help and the script's docstring |
| Fulfillment starts when settlement is verified | Decided here; implemented and promoted by `bare-metal-mock-provisioned-deal` |
| Each route's typed client in the package that owns the route | A need recorded in `kit-owned-storefront-shell` |
| Pool-override work | Superseded here; owned by `publish-indicative-listing-rates` |
| Payload kind unchanged; listing model names the schema's flat fields | Temporary: change history only |
| Roadmap | `docs/development/ROADMAP.md` Goal 7 (gap closed, current state), and the Goal 1–2 vocabulary gap wording |
| Campaign index | `openspec/changes/README.md` (this row, the Goal 7 graph and path, and the rates, unbacked, vocabulary, domain-stacks, and deal rows) |
