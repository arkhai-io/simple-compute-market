# Design

Proposal stage. This design is reviewed on its own before an implementation plan
is written; there is no `tasks.md` yet.

## Context

Verified against the tree on 2026-10-01.

- `core/registry/filter-spec.yaml` (version 6, schema `compute.market` version 2)
  declares `listing_shape` with `additionalProperties: true` at the top level and
  inside `listing_resource`, and refuses only the retired `offer`,
  `offer_resource`, and `virtualization_type` spellings.
- `POST /listings` calls `reject_retired_listing_shape` and nothing else from the
  schema, then writes six named carriers. Republication merges each named carrier
  whose value is not null into the stored row. `PUT /listings/{listing_id}` changes
  only `status` and `oracle_address`.
- `GET /listings/{listing_id}` and the search route serialize the stored row through
  `order_to_dict`; responses are signed by the registry authority. Search evaluates
  filters over the same serialized form, so a discarded field can be neither
  returned nor filtered on. A publish
  request is body-bound signed by the publisher.
- Full `listing_shape` validation runs only in the dry-run validation route.
  Enforcing it at publish was previously declined because it would reject listings
  the registry has accepted for as long as it has existed.
- The registry serves more than one schema (compute, API credits, introductions),
  so whatever is chosen here is domain-neutral.

## Options

### A. Keep what the schema admits

Store each accepted listing document as published — for example one JSON document
column beside the existing carriers — and serve it. The filter specification
becomes the whole listing contract.

- Satisfies "Opaque market payload storage" literally.
- Needs a republication rule: today's per-carrier merge of non-null values has no
  meaning for an opaque document. Whole-document replacement is the natural rule
  and is observable to a publisher that republishes partial bodies.
- Existing rows have no document; serving them needs a backfill from their
  carriers or a read path that synthesizes one.
- Interacts with `index-registry-filters`: indexed paths into a document rather
  than into named columns.

### B. Admit only what is kept

Close the top level of each served `listing_shape` to the stored carriers and the
names it declares, and enforce the specification at the publish boundary.

- Smallest change; makes the served schema honest.
- Enforcing the full specification at publish is what was previously declined for
  compatibility. A narrower form enforces only top-level closure, which no stored
  listing can have violated observably, since no unnamed field was ever kept.
- Every future listing-level term is a filter-specification and registry change,
  which keeps pressure to put terms in `listing_resource`.

## Open Questions

- **Option A or B?** The review decides. Revisit trigger for B, if chosen: the
  first market term that cannot reasonably live in `listing_resource`.
- **Under A, whole-document replacement on republication?** And how existing rows
  are served.
- **Under B, full or top-level-only enforcement at publish?**
- **Does a registry-signed copy of a listing-level term carry the authority a buyer
  needs?** It attests what the registry stored, not what the seller committed to;
  `negotiation-driven-capacity-resize` asks the same question of a storefront-served
  rate structure, and the answer should be consistent.
