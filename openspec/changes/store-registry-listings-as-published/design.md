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
A is selected below. This is implementation for maintainer review, not promotion.

## Decisions

### D-a. Retain accepted documents; replace on republication

**Decided by webapp owner 2026-11-06, pending maintainer review.**

Store the complete publication body in a JSON column. Authenticate first and
validate against the configured `listing_shape` at publication, just as dry-run
validation does. Registry-owned response names (`publisher_id`,
`publisher_principals`, `created_at`, `updated_at`, `publisher_publication`, and
`publisher_updates`) are reserved and refused by name; otherwise every admitted
field, including nulls and unknown properties admitted by the schema, survives.
Full validation closes the existing dry-run/publish disagreement; publishers must
send a complete schema-valid document, not a partial patch.

Republication replaces the document whole. An omitted commercial field disappears;
null is retained, not a request to merge an old value. Publisher and listing IDs,
creation time, and lifecycle status remain stable; an explicitly supplied status
is honored. `PUT` remains a narrowly scoped status/oracle update, rejects other
keys instead of discarding them, and retains its own seller evidence. Status is
registry lifecycle metadata, not a promise that the publication remains open.

Existing rows have no retained body or seller proof. Synthesize their old discovery
shape from existing carriers on read, with null publication evidence. This avoids
a data rewrite and never invents a seller signature or a lost rate structure.
The next valid republication establishes the document and proof atomically. Old
columns remain for legacy synthesis only, not a second commercial source of truth.

Filters continue to evaluate the served document. `index-registry-filters` stays
deferred: when activated, its indexes must project paths from the document, plus
registry-owned lifecycle columns, and prove parity for synthesized legacy rows.
No indexes, SQL filtering, or runtime schema mutation are added here.

Alternatives rejected: per-field merge leaves withdrawn terms live; a backfill
cannot recover discarded data or signatures and unnecessarily rewrites rows;
immediate indexes have no measured activation evidence. Revisit on measured
query latency, or a demonstrated publisher need for a separately specified patch
protocol. Do not silently restore merge semantics.

### D-b. Publish rate_structure at listing level

**Decided by webapp owner 2026-11-06, pending maintainer review.**

The VM publication loop carries resolved rates through its listing model and the
shared opaque publication transport as top-level `rate_structure`. The neutral
registry client accepts arbitrary extra listing terms rather than acquiring a VM
rate type. VM publication omits absent optional capacity attributes rather than
emitting null values that violate the compute schema; local stored views remain
unchanged. The compute filter specification declares this optional object/null
field; flat-priced listings carry no rate structure. Registry code never names
or calculates rates. `asking_rate` stays in `listing_resource`; moving it is a
separate follow-up only if a consumer needs it, not a prerequisite here.

Example commercial content:

```json
{"listing_id":"example-listing","storefront_url":"https://seller.example/","listing_resource":{"region":"example"},"rate_structure":{"cpu":[{"asset":"usd","rate":"0.05","per":"hour"}]},"settlement_options":[{"option_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","settlement":{"schema":"example.payment.v1"}}]}
```

Revisit if a domain changes its rate vocabulary; that belongs to its publication
codec/schema, never a domain import into registry storage.

### D-c. Preserve seller evidence alongside registry response signatures

**Decided by webapp owner 2026-11-06, pending maintainer review.**

`publisher_publication` contains `body_base64` (the exact received HTTP body bytes)
and `request` (the complete authenticated v2 envelope, including seller principal,
operation, resource, request ID, timestamp, body hash and proof). The marketplace
signature binds the canonical JSON hash, not JSON whitespace; retaining exact
transport bytes also preserves the original representation without pretending
the protocol signs whitespace. The registry's ordinary response signature covers
the returned document and this evidence. No secrets are retained.

A buyer decodes the body, verifies its canonical hash and envelope signature,
checks listing identity and `listing.publish` context, and uses the terms from that
verified body. Historical verification uses the signed timestamp, not the live
request freshness window. It must separately establish seller trust/ownership;
a valid signature alone is neither current credential trust nor rate acceptance.
The live publisher principal set can change under rotation without rewriting old
publication evidence. Legacy rows explicitly have no seller evidence.

Lifecycle/oracle updates do not rewrite publication evidence. `publisher_updates`
retains the latest signed update for each mutable field, so an oracle change is
not misrepresented as part of the original signed publication. Republication
clears oracle update evidence and replaces commercial content; status evidence is
retained when publication omits status. Reserved metadata cannot be spoofed by a
published document.

Revisit if a versioned identity protocol changes the envelope or if consumers need
full mutation history rather than the latest field proofs. A registry-only copy
was rejected because it cannot prove what the seller published.

### D-d. Resize gate 2.1a consumes verified registry terms

**Decided by webapp owner 2026-11-06, pending maintainer review.**

The buyer reads `rate_structure` from the registry listing, verifying it against
D-c's seller publication. This supplies the authority/carrier answer to
`negotiation-driven-capacity-resize` gate 2.1a. Implementing its buyer accessor,
shape negotiation, open-ended periods or spot mechanics is outside this change.
Revisit only if maintainer review changes D-a through D-c. A legacy row without
seller evidence cannot satisfy this gate until its seller republishes.

### D-e. Follow the packaged registry migration chain

`add-database-migration-commands` is archived. The registry's packaged Alembic
chain starts at `v0_3_0_baseline`, adopts the v0.3.0 revision without replaying
its DDL, and runs through `registry-migrate` before startup. Add revision
`019_retained_publications` after that baseline. Its three nullable columns
preserve existing rows without inventing seller evidence. The baseline already
supplies `listing_resource`, demands and API-key storage; no pre-floor repair
revision is needed. PostgreSQL inherits this additive revision under the
campaign's preferred order. Storefront startup migration behavior is unchanged.

## Implementation cadence and validation

One implementation round: registry persistence/evidence and client transport,
then VM publication wiring, then focused validation and first-use evidence.
Existing tests are run and their fixtures may follow deliberate schema-validation
changes; no new permanent tests are added without maintainer approval.
Post-review closeout performs promotion and archival; neither is claimed now.

## Design promotion record

| Accepted decision | Permanent location (post-review) |
|---|---|
| D-a opaque documents, replacement, legacy synthesis, filter parity | `openspec/specs/registry-discovery/spec.md`; `openspec/specs/registry-discovery/architecture.md` |
| D-b listing-level family rates | `openspec/specs/storefront-publication/spec.md`; `openspec/specs/storefront-publication/architecture.md` |
| D-c seller evidence and metadata authority | `openspec/specs/registry-discovery/spec.md`; `openspec/specs/registry-discovery/architecture.md` |
| D-d verified registry carrier for resize | `openspec/specs/registry-discovery/architecture.md`; downstream resize design gate |
| D-e migration sequencing correction | Temporary: this design and `openspec/changes/README.md` |

## Open questions

None for implementation. D-a through D-e await maintainer review. Promotion and
archival remain post-review work.
