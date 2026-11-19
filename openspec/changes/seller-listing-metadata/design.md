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

## Design promotion record

| Accepted decision | Permanent destination |
|---|---|
| Envelope fields, limits, and refusal at the publish boundary | `openspec/changes/seller-listing-metadata/specs/registry-discovery/spec.md` (MODIFIED "Schema-driven listing validation") |
| Metadata keys are addressable by filter-spec path | `openspec/changes/seller-listing-metadata/specs/registry-discovery/spec.md` (ADDED "Seller details are discoverable through the filter spec") |
| Storefront surfaces, override sourcing, and API-credit prose | `openspec/changes/seller-listing-metadata/specs/storefront-publication/spec.md` (ADDED requirements) |

Promotion into `openspec/specs/` happens at closeout, by the archive merging these deltas.
