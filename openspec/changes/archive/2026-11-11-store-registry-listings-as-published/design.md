# Design

## Context and motivating use

A buyer needs a listing's resolved family rates before negotiating another shape.
The VM storefront already derives and persists `rate_structure`, but publication
selects named carriers and drops it. Registry publication similarly selects six
carriers, losing any additional top-level term. The registry serves compute,
API-credit and introduction schemas; it must not interpret any domain's rates.

The initial proposal compared A (retain accepted documents) with B (close the
schema to existing carriers). B limits every new listing term to a registry code
change and encourages placing commercial terms inside capacity descriptions.
A is selected below.

The change was implemented before its design was reviewed. The owner waived the
design review in favour of a design discussion held in its place; every decision
below is settled by that discussion (round 1's owner record, `01`), and round 1's
triage records them here.

## Decisions

### D1 — Retain accepted documents whole; replace on republication

Store the complete publication body in a JSON column (`published_document`).
Reads serve it with registry-owned fields overlaid. Storing the request body
whole is less fragile than maintaining the listing schema at the database level.

Authenticate first, then validate against the configured `listing_shape` at
publication, exactly as the dry run does. Full validation closes the
disagreement in which the dry run reported `valid=false` and publication still
succeeded; publishers send a complete schema-valid document, not a partial
patch. A refused republication leaves the last stored listing in place.

Registry-owned response names (`publisher_id`, `publisher_principals`,
`created_at`, `updated_at`, `publisher_publication`, `publisher_updates`) are
reserved and refused at publication by that exact list. Otherwise every admitted
field, including nulls and unknown properties the schema admits, survives.

Republication replaces the document whole. An omitted commercial field
disappears; null is retained, not a request to merge an old value. Publisher and
listing IDs and creation time stay stable. Status survives republication unless
the publication supplies one; close and reopen stay explicit `PUT`s. `PUT`
remains a narrowly scoped status/oracle update, refuses any other key rather
than discarding it, and retains its own per-field seller evidence (D2).

Existing rows have no retained document or seller proof. Their old discovery
shape is rebuilt on read from the carrier columns, with null publication
evidence; no backfill rewrites them, and nothing invents a seller signature or a
lost rate structure. The next valid republication establishes the document and
proof atomically. The carrier columns are legacy-only, except `oracle_address`,
which `PUT` still writes and which reads serve when an oracle update is
recorded. On republished and new rows the other carriers are stale or empty and
must not be read. Removing the carriers and the rebuild path is deferred to a
carrier-removal migration, triggered when `migrate-registry-to-postgres` or
`index-registry-filters` starts; neither copies nor indexes the stale carriers.

A listing's signed `storefront_url` is its own: a storefront move reaches each
listing on its next republication. The publisher record's URL serves rebuilt
legacy rows and the publisher detail only.

Filters evaluate the served document. `index-registry-filters` stays deferred:
when activated, its index paths come from the document, plus registry-owned
lifecycle columns, and must match rebuilt legacy rows. No indexes, SQL
filtering, or runtime schema mutation are added here.

Publishing is open to any self-generated key by default
(`REGISTRY_REQUIRE_WRITE_API_KEY` defaults to false), and no request-body size
limit applies. This change adds no limit; the default deployment's write
admission is the registry write hardening gap (`openspec/changes/README.md`).

Alternatives rejected: per-field merge leaves withdrawn terms live; a backfill
cannot recover discarded data or signatures and unnecessarily rewrites rows;
immediate indexes have no measured activation evidence; B, keeping only what the
carriers name, keeps discarding admitted terms. Revisit on measured query
latency, or a demonstrated publisher need for a separately specified patch
protocol. Do not silently restore merge semantics.

### D2 — Retain the seller's exact body bytes and signed request

`publisher_publication` contains `body_base64` (the exact received HTTP body
bytes) and `request` (the complete authenticated v2 envelope, including seller
principal, operation, resource, request ID, timestamp, body hash and proof). The
marketplace signature binds the canonical JSON hash, not JSON whitespace;
retaining exact transport bytes also preserves the original representation
without pretending the protocol signs whitespace. The registry's ordinary
response signature covers the returned document and this evidence. No secrets
are retained. Size per row is acceptable at this scale.

The evidence supports this verification: a consumer decodes the body, verifies
its canonical hash and envelope signature, checks listing identity and
`listing.publish` context, and uses the terms from that verified body. This
change supplies the evidence; no buyer verifies it on this branch, and whether
and how a buyer does is decided at `negotiation-driven-capacity-resize` gate
2.1a (D4, review 23 F1). Historical verification uses the signed timestamp, not the
live request freshness window. The registry attests key ownership; the seller's
proof attests terms. Verification uses the publisher's active keys as the
registry serves them in `publisher_principals` at read time (retained keys for
an accepted deal), matching the buyer's existing trust model. A consequence of
rotation: a listing signed by a retired key is refused until republished.
Independent seller identity is a candidate for the registry write hardening gap.
Legacy rows explicitly have no seller evidence.

Lifecycle/oracle updates do not rewrite publication evidence.
`publisher_updates` retains the latest signed update for each mutable field, so
an oracle change is not misrepresented as part of the original signed
publication. Republication clears oracle update evidence and replaces
commercial content; status evidence is retained when publication omits status.
Reserved metadata cannot be spoofed by a published document.

Revisit if a versioned identity protocol changes the envelope or if consumers
need full mutation history rather than the latest field proofs. A registry-only
copy was rejected because it cannot prove what the seller published.

### D3 — Listing pricing in one top-level `pricing` object

A listing's listing-level prices travel together in a top-level `pricing`
object: `asking_rate`, in its current strict shape, and an optional
`rate_structure` keyed directly by family, with entries as the VM pricer emits
them. A flat-priced listing carries `pricing.asking_rate` only. A settlement
option's price stays with the option it prices. The compute schema does not
name families.

```json
{
  "listing_resource": {"region": "example", "offering_mode": "vm", "vcpu_count": 16},
  "pricing": {
    "asking_rate": {"amount": "2400", "asset": "<settlement clause asset>", "period": "hour"},
    "rate_structure": {
      "gpu": [{"asset": "<settlement clause asset>", "rate": "80", "per": "hour"}],
      "cpu": [{"asset": "<settlement clause asset>", "rate": "5", "per": "hour"}],
      "memory": [{"asset": "<settlement clause asset>", "rate": "1", "per": "hour"}],
      "storage": [{"asset": "<settlement clause asset>", "rate": "1", "per": "hour"}]
    }
  }
}
```

The compute filter specification declares the optional top-level `pricing`
with `asking_rate` and `rate_structure`, removes `listing_resource.asking_rate`
and the top-level `rate_structure`, and repoints the four asking-rate filters to
`$.pricing.asking_rate.*` with their query names unchanged. Version 9 is
unreleased and stays 9. Every in-repository publisher writes the new location
through the opaque publication channel: the VM listings model and storefront,
and the bare-metal domain and storefront. `resource-pools`,
`resource-pools-contracts` and `pool-overrides` resolve and store a rate but
never place it in a listing, so they are unchanged. Round 1 implemented the
intermediate state — a top-level `rate_structure` beside a nested asking rate —
and round 2 moves both into `pricing`.

The neutral registry client carries domain terms as opaque extra listing terms
rather than acquiring a rate type; the domain's `publication_terms` carries
`{"pricing": {...}}`. VM publication omits absent optional capacity attributes
rather than emitting nulls the compute schema refuses; local stored views are
unchanged. Registry code never names or calculates rates.

The earlier locations — `listing_resource.asking_rate`, released in version 8,
and the top-level `rate_structure` round 1 and the changes up the stack
write — are refused at
publication, naming their place in `pricing`, as version 6 refuses its retired
names: admitted, a rate there would publish and match no rate bound, and its
seller would get no signal (review 16 F1). Dual-format reading was rejected: it
needs a precedence rule and temporary logic, and version 9 is unreleased.

Known upgrade gaps: rebuilt legacy rows carry no `pricing`, so they drop out of
asking-rate filters until their seller republishes. A version 8 registry keeps
only its named carriers, so it drops a new publisher's `pricing` with every
other unnamed term until it upgrades; no publisher reads a registry's
specification, and checking it would be a new interface across every domain.
Conversely a version 8 storefront's rated listings are refused by a version 9
registry until the storefront upgrades: the failure is visible, which is the
point, so registries and storefronts upgrade together. Closeout put whether
`docs/operator-handbook.md` needs that upgrade note to the owner, who chose to
add it: the supported topology deploys storefronts in releases apart from their
registry's, so a split upgrade is possible and its only symptom would otherwise
be refused publications. Reads of a top-level
`rate_structure` and retained pricing records up the stack move to
`pricing.rate_structure` in those changes; the stack merges together.

Revisit if a domain changes its rate vocabulary; that belongs to its
publication codec and schema, never a domain import into registry storage.

### D4 — Buyers price from the verified registry carrier

The resize change's buyer reads `pricing.rate_structure` from the registry
listing, verifiable against D2's seller publication. This supplies the authority and carrier answer
to `negotiation-driven-capacity-resize` gate 2.1a; its buyer accessor, shape
negotiation, open-ended periods and spot mechanics are outside this change. A
legacy row without seller evidence cannot satisfy the gate until its seller
republishes, and a buyer sees a local rate change only after republication.

### D5 — Migration ordering; downgrade is one-way

The registry's packaged Alembic chain starts at `v0_3_0_baseline`, adopts the
v0.3.0 revision without replaying its DDL, and runs through `registry-migrate`
before startup. Revision `20261106_001_registry_retained_publications`, named by
the dated convention the repository's migration chains use, follows that
baseline. Its three nullable columns preserve existing rows without inventing
seller evidence. Its downgrade refuses, as the baseline's does: dropping the
columns would discard every retained document and seller proof. Rollback is
restoring the pre-upgrade backup; an older image refuses the migrated database
as ahead. PostgreSQL inherits this additive revision under the campaign's
preferred order. Storefront startup migration behavior is unchanged.

This decision is sequencing only. The rate-structure digest pinned at a
negotiation's opening is a different decision, made in
`negotiation-driven-capacity-resize`.

### D6 — Registry repair republishes the domain's candidate

Registry convergence republishes a listing through the domain's own candidate,
as initial publication and reopen do: a stored view may hold local-only fields
or lack derived listing terms, and republication replaces the registry's whole
document (D1). The capacity-publication kit's `PublicationDomainHooks`
therefore requires `publication_candidate(listing)`, which every composing
domain implements from the candidate codec its publish path uses; where a
domain's candidate is its stored row, that is what repair sends. Repair checks
the binding and runs `validate_candidate` first, as publication does, so a
listing whose binding disagrees stays unrepaired rather than being republished.
Without the hook, VM repair sent JSON-null capacity attributes that full
validation refuses, and would have dropped the listing's pricing terms.

The API-credit filter schema declares the market's settlement option — required
`option_id` and `settlement`, optional `price` and `lifecycle` — which its own
mechanism and asset filters already read. Its earlier flat option shape had
never been enforced; full validation at publication (D1) made it refuse every
API-credit listing.

## Implementation cadence and validation

Round 1 implemented registry persistence, evidence and client transport, then VM
publication wiring, with focused validation and first-use evidence. Round 1's
triage makes the corrections and small fixes (the decision text, the migration
rename and refusing downgrade, D6, and the client docstring). One further
section implements D3's `pricing` move and the permanent tests at the levels
`docs/development/TESTING.md` assigns, reviewed as round 2. Validation runs every
part against each fixed `HEAD`, end-to-end included. Post-review closeout
performs promotion and archival.

## Alternatives declined during implementation

Suggestions from the fresh-context compliance checks and reviews that were
declined, with the reason, so a later reader does not reopen them unknowingly:

- A test of the publication revision's refusing downgrade: the baseline's
  refusal has none either, and the refusal is one statement.
- Taking each registry's schema into publisher tests through a packaged
  dependency: the API-credit specification is packaged nowhere, and installing a
  registry into a storefront's test environment to read one file is heavier than
  reading it by checkout path, as the registry's own tests do.
- Asserting the registry's reserved and retired names in publisher tests: those
  are the registry's own tested contract.
- Naming the replacement in the dry run's error for a retired price location:
  the dry run reports jsonschema's message, as it does for version 6's retired
  names; publication's refusal names it.
- A unit test of a prohibition clause without a `description`: it needs a
  hot-swapped specification to reach a fallback string.
- Retitling "Seller publication evidence is independently verifiable": it reads
  as verifiable apart from the registry's signature, which is what it requires.
- Recasting the storefront delta's "buyers can verify them" as "consumers": it
  states a capability, not an obligation.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 retained documents, replacement, reserved names, schema admission, legacy rebuild, filter parity | `openspec/specs/registry-discovery/spec.md` ("Accepted listing content is retained", "Legacy listing reads do not invent seller evidence", "Schema-driven listing validation", by the archive); `openspec/specs/registry-discovery/architecture.md#retained-publication-documents`, including that a refused republication leaves the last stored listing and the default deployment's open write admission as a current limit |
| D2 seller evidence wire contract and trust anchor | `openspec/specs/registry-discovery/spec.md` ("Seller publication evidence is independently verifiable", by the archive); `openspec/specs/registry-discovery/architecture.md#seller-publication-evidence` (the `publisher_publication` / `publisher_updates` shape, why bytes, historical verification, rotation) |
| D3 listing pricing object | `openspec/specs/registry-discovery/spec.md` ("The compute schema carries a listing's asking rate"), `openspec/specs/storefront-publication/spec.md` ("A listing's listing-level prices are published in one pricing object", "A listing's asking rate is declared per shape", "A shape-priced listing records the rates that could price a revised shape"), `openspec/specs/resource-pool-management/spec.md` ("Asking-rate hint validation"), all by the archive; `openspec/specs/registry-discovery/architecture.md#listing-pricing-and-the-resize-carrier` (refusal of the earlier locations, upgrade gaps); `openspec/specs/storefront-publication/architecture.md#asking-rates` and `#shape-pricing` |
| D4 verified registry carrier for resize | `openspec/specs/registry-discovery/architecture.md#listing-pricing-and-the-resize-carrier`, as the carrier and evidence a buyer can read, not as current buyer behaviour; the buyer obligation stays with the resize change's gate 2.1a |
| D5 migration ordering | `openspec/specs/registry-discovery/architecture.md#retained-publication-documents`: one sentence on why the revision's downgrade refuses and that rollback is the backup; the ordering itself is sequencing only |
| D6 repair through the domain candidate | `openspec/specs/storefront-publication/spec.md` ("Registry repair republishes the domain's candidate", by the archive); `openspec/specs/storefront-publication/architecture.md#registry-convergence` |
| D6 API-credit settlement option shape | No permanent destination — a schema correction in `domains/apicredits/registry/filter-spec.yaml`, guarded by the per-publisher schema tests (task 3.5); its registry test is cited in the registry specification's evidence |
| D3/D4 correction | `docs/development/ARCHITECTURE.md#discovery-and-negotiation`: resolved family rates are published in `pricing.rate_structure` rather than never reaching a registry |
| Closeout corrections to statements the change made false | Delta MODIFIED requirements, merged by the archive: `registry-discovery` "The filter grammar can compare exact decimal values" (a non-finite stored value reads as no value because rebuilt legacy rows were never validated, not because publication skips validation); `storefront-publication` "A shape-priced listing records the rates that could price a revised shape" (publication now carries `pricing.rate_structure`, not "no additional listing-level field") |
| Evidence | The evidence sections of `openspec/specs/registry-discovery/spec.md` and `openspec/specs/storefront-publication/spec.md` |
| D3 upgrade gaps, for operators | `docs/operator-handbook.md#what-the-upgrade-from-v030-changes`, "Registries and storefronts upgrade together" (owner's decision at closeout) |
| Roadmap currency | `docs/development/ROADMAP.md`, "Negotiate full compute capability" current state: family rates are published in `pricing` |
| Campaign index currency | `openspec/changes/README.md`, the change's row in "Registry productionization"; its graphs unchanged |

No principle is promoted to `docs/development/ARCHITECTURE.md`; the one edit
there corrects a statement this change makes false.

## Open questions

None.
