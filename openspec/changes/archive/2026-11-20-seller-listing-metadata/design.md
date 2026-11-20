# Design

## Decisions

- **D1.** The listing envelope carries the seller claims beside `settlement_options`, as three optional fields shared by every domain. A flat scalar map preserves JSONPath filtering; a free-text blob or a schema-tagged string would hide its contents from filters. Agreed domain extensions stay in `listing_resource`; registry-attested facts are separate authority (#174, out of scope).
- **D2.** Limits and value shapes are defined once, in `market_core` (`core/src/market_core/listing_details.py`), and consumed by the registry's served schema, publish and dry-run checks, the storefront create models, and both domains' pool-override terms models.
- **D3.** The registry keeps the fields in the signed document it already retains whole (`published_document`), with no columns or migration of their own: a repeat publish replaces that document, so details a listing no longer states are gone from the registry along with the rest of the earlier publication. It checks the fields' limits at publish and dry-run validation, and injects their JSON Schemas into the served `listing_shape` at load time, so each registry advertises them without its operator editing a shipped YAML. Settled at the triage of `01-implementation` (F1): the first implementation stored them in nullable columns on a base predating the retained document, and a repeat publish that omitted them left the old values in place.
- **D4.** Every domain's automated publication path sources the fields from its pool override's validated `details` term, so reconciliation treats them as terms of sale: refreshed in place on change, cleared when withdrawn. Manual surfaces (VM create request, API-credit quota publish) accept them from the seller; API credits keeps its legacy resource-level `description` and publishes the same prose beside the envelope as well, so its seller request takes the shared description type and refuses prose over the envelope's limit before a listing row exists (triage of `01-implementation`, F2).
- **D5.** The clients include the fields in a request body only when stated, so requests that name none keep the bytes they always sent, and listings without the fields read exactly as before.

## Alternatives considered

- A single free-text string: only substring-searchable, and invites encoding JSON inside it. Kept only as `description`.
- `{schema, data}` (protobuf `Any`, CloudEvents `dataschema`): the data string is opaque to JSONPath filters, and one slot allows one schema per listing. Typed extensions already have `listing_resource`.
- Putting the fields inside each domain's resource model: three `extra="forbid"` models would each redeclare them, and they describe the listing rather than the resource.

## Settled during implementation

- **The served metadata object is closed.** Pydantic renders the key's character class as `patternProperties`, which alone admits a key outside the class with any value, so the served schema admitted keys publication refuses. `ListingMetadata` adds `additionalProperties: false`; what publication and the dry run admit is unchanged, and the served specification's ETag changes with its `listing_shape` (section 3).
- **The API-credit service checks the details itself.** The credits lane's seed passes its configured description to `ListingService.publish_from_quota` without the route's request model, so a seed description past the limit would have written a listing row every registry refuses; the service validates through `ListingDetails` before it reads or writes anything (section 6).
- **The quota publish command builds its request model first.** A request the model refuses is a usage error (exit 2) naming the field, before the credential is read or a storefront contacted, where the sync client's validation raised a traceback (section 6).
- **Each limit's edges are tested once.** They are `market_core`'s unit suite's; every other new test states a value far past a limit, so a limit changed in `market_core` changes one suite (`test-levels.md`, "Coverage between the levels").
- **One version bump for the whole change**, on the owner's direction at section 4's start: a minor step for every package whose contents changed, a patch for every package whose one change is a moved exact pin, and lower bounds raised to the first version holding what each consumer imports.

## Design promotion record

| Accepted decision | Permanent destination |
|---|---|
| D1: envelope placement, the three fields, and the alternatives considered | `openspec/specs/registry-discovery/spec.md`, "Schema-driven listing validation" (merged by the archive); `openspec/specs/registry-discovery/architecture.md#seller-authored-listing-details` |
| D2: limits defined once in `market_core`; the closed metadata object | `openspec/specs/registry-discovery/architecture.md#seller-authored-listing-details` |
| D3: details kept in the retained document, checked at publication and dry run, injected into the served `listing_shape` | `openspec/specs/registry-discovery/spec.md`, "Schema-driven listing validation" and "Seller details are discoverable through the filter spec" (merged by the archive); `openspec/specs/registry-discovery/architecture.md#seller-authored-listing-details` |
| D4: override-sourced details as a term of sale; manual surfaces; API-credit prose under the envelope's limit, the seed path included | `openspec/specs/storefront-publication/spec.md`, "A seller may state details beside the listing envelope", "A compute listing derives its details from the pool override", "An API-credit listing carries its seller's prose" (merged by the archive); `openspec/specs/storefront-publication/architecture.md#storefront-pool-overrides` and `#seller-authored-listing-details`; `openspec/specs/storefront-publication/configuration.md#storefront-listing-shapes-and-pool-overrides` |
| D5: clients send only stated details | `openspec/specs/registry-discovery/architecture.md#seller-authored-listing-details`; `openspec/specs/storefront-publication/architecture.md#seller-authored-listing-details` |
| Evidence | the `## Evidence` lists of `openspec/specs/registry-discovery/spec.md` and `openspec/specs/storefront-publication/spec.md` |
| Roadmap currency | No goal affected: `docs/development/ROADMAP.md` names no goal or gap for seller listing details |
| Campaign index currency | `openspec/changes/README.md`: the row set to `in closeout`, its notes rewritten, and its link pointed at the archived directory; an independent change, so no campaign graph changes; the unowned gap section 6 found, the API-credit storefront's missing registry seam, recorded under "Unowned work with no campaign" |
