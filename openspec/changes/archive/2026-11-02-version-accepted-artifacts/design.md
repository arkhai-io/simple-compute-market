# Design

## Context

Reverified against revision `6855f6de7087509cda10b776b0802ac258364848` on
2026-10-31. The settled scope is bare-metal retained portable-evidence correctness
and accurate evolution guidance, implemented in one coherent round.

### Current paths and corrected assumptions

- `domains/bare_metal/src/arkhai_bare_metal/evidence.py` defines binding, result,
  and portable evidence. Its digest properties and nested-result validator serialize
  current models instead of preserving proof input.
- Storefront `sqlite_client.py` already stores canonical evidence TEXT and digest
  once. Load selects by digest without hashing the returned text; save also returns
  a newly parsed model.
- Storefront `alkahest_lifecycle.py` uses that model's recomputed digest for its
  intent and publication. Domain `evidence_routes.py` signs a reserialized body.
  Fixing only the nested validator leaves both paths exposed.
- The former hosted lifecycle validator and hosted-contract module are gone.
  Hosted-fiat is no longer an installed recovery precedent. Domain identity
  `bare_metal.v1`, current payload kind `bare_metal.v2`, and portable-evidence
  v1 kinds are distinct discriminators.
- Negotiation retains exact `agreement_bytes` and opaque `settlement_data`.
  Arkhai stages consume those bytes and the stored mandate; payment identities
  use JCS rather than bare-metal evidence's sorted compact JSON grammar.
- API-credit evidence and generated payment models also need care during future
  evolution. They are outside this correction; this change claims no universal
  codec coverage. Existing contact deletion/tombstones and previous-wire mandate
  refusals remain authoritative.

An offline synthetic model-default reproduction demonstrates different digests
for unchanged stored bytes and a changed model dump. It establishes the codec
defect, not a failed live purchase or complete compatibility qualification.

## Decisions

### 1. Domain-owned immutable document and separate validated view

The domain owns an immutable evidence document containing original canonical
UTF-8 bytes, their verified digest, a separate validated application view, and
the original result representation with its verified nested digest. It exposes
`canonical_bytes`, `evidence_digest`, `canonical_json()`, `to_wire()`, and `value`.
The result document exposes its verified `result_digest` and validated fields.
`to_wire()` returns a fresh decoded JSON object: mutating it cannot change the
retained document. Bytes and digest cannot be accepted independently without
validation.

Reading starts from original bytes plus expected digest. Verify the outer digest
and the original result JSON's canonical digest before converting to views.
Keep strict v1 field, type, principal, selection, and timestamp validation;
retaining JSON does not authorize unknown fields or bypass the existing schema.

New production constructs one current-v1 canonical snapshot from validated binding
and result inputs. Keep that wire codec fixed separately from application-view
changes. Existing identity derivation uses those same v1 representations, never
an evolved view's dump. Binding construction stays where it is; no binding table
or reconstruction migration is added.

For example, this existing result remains the accepted document when an
application view changes. Layout here is readable; storage retains existing
sorted compact UTF-8 encoding and omission rules.

```json
{
  "kind": "bare_metal.lease-ready-result.v1",
  "site_id": "site-a",
  "offering_mode": "bare_metal",
  "resource_selection": "specific",
  "physical_resource_id": "resource-a",
  "capacity_reservation_ref": "reservation-a",
  "settlement_resource_ref": "settlement-resource-a",
  "fulfillment_ref": "fulfillment-a",
  "access_method": "ssh",
  "access_ready": true,
  "access_ready_at": "2030-01-01T00:40:00Z",
  "expires_at": "2030-01-01T00:50:00Z"
}
```

A view's new defaults do not add fields to this document, normalize its timestamps,
or remove original values. Changing accepted wire content requires its own
versioning decision; this correction produces only existing v1 kinds.

Rejected: hidden snapshots inside existing Pydantic models, because nested
serialization and copy/update operations would have to maintain a second hidden
authority. Rejected: a generic document/decoder framework, because this correction
needs only the domain's concrete document and codec.

### 2. Existing persistence and one document through every proof-bearing caller

`lease_ready_evidence_json` TEXT already retains the canonical document. Its
UTF-8 encoding is the proof input; the existing digest column stays the lookup
key. No schema backfill, new column, content rewrite, or reset is needed.

Load hashes retrieved text against the expected digest before yielding a view.
Save keeps its first-write-wins transaction and returns the verified document
actually stored, including on retries proposing a different candidate. Corrupt
stored content fails explicitly: never normalize, overwrite, republish, or assign
it a replacement digest.

The Alkahest worker journals and publishes the document's verified digest, reusing
it after restart rather than rebuilding it from current state. Submission intent,
unknown-outcome parking, recorded attestation, and collection rules stay intact.

The route authorizes from validated buyer/claimant facts and existing configured
administrators. It signs `canonical_bytes` and emits original evidence JSON inside
the existing signed envelope. Incidental HTTP JSON layout is not the canonical
inner proof input. Neither privileges nor proof protocol changes.

Both clients retain the received evidence JSON until they canonicalize it under
the existing protocol and compare its digest with the requested digest. They then
validate and retain the document and view. Authenticated transport remains the
response-trust boundary; no independent portable-proof trust configuration is added.

| Caller | Required document operation |
|---|---|
| Evidence builder and binding/result helpers | Produce fixed v1 snapshot and existing identities |
| SQLite save/load | Retain and verify the actual stored document |
| Alkahest worker | Journal and publish retained verified digest |
| Route service readers | Read validated party facts |
| Route service response | Sign retained bytes and emit original JSON |
| Thin FastAPI binding | Preserve serialization and existing authentication |
| Async/sync evidence clients | Match requested digest before yielding a view |
| Domain/storefront tests and bare-metal e2e | Exercise the same document operations |

Each caller uses public document operations or its validated view, not private
snapshot state. Current buyer purchase/recovery commands do not resolve portable
evidence. Their exact payment inputs and run-log behavior get regression coverage
without a new migration.

### 3. Python attribute compatibility and explicit nominal type versioning

Both clients currently return `BareMetalSignedLeaseReadyEvidence`, whose
`evidence` field has nominal type `BareMetalLeaseReadyEvidence`. Keep the named
signed carrier and client method signatures. Its evidence field becomes the
domain document, with explicit read-only properties for every existing evidence
field. Its `result` exposes the result document with existing result-field
properties. These existing reads remain usable:

```python
signed.evidence.condition_anchor
signed.evidence.accepted_binding_kind
signed.evidence.buyer_principal
signed.evidence.result.access_ready_at
signed.evidence.result.result_digest
signed.evidence.evidence_digest
signed.evidence.canonical_json()
```

Digest and canonical JSON operations use retained content, not `value.model_dump()`.
The signed carrier's JSON still has `protocol`, `seller_principal`, `evidence`, and
`proof`; it gains no bytes field or wrapper. Existing v1 readers see the same
object, and unknown kinds or unsupported fields remain refused.

The nested nominal Python type changes despite property usability.
`arkhai-bare-metal` is currently 0.14.0: implementation takes the next minor
release under `docs/development/RELEASING.md`, refreshes affected consumer
requirements and locks, and requires that version wherever the new document API
is imported. The facade preserves field-style reads without claiming complete
Pydantic-model compatibility.

Rejected: adding a wire bytes field, since canonical JSON already carries the
proof input; returning only a current model, since it loses that input; and a new
artifact kind, since accepted wire content and interpretation do not change.

### 4. Accurate evolution guidance without retirement machinery

A change evolving retained signed or content-addressed state preserves its
accepted representation and identity. Verify using the owning protocol's
canonicalization and framing before converting to an application view. Derived
unsigned state may migrate without rewriting accepted content.

This is an evolution obligation, not a claim that every existing artifact path
has been audited and converted. Keep existing explicit compatibility floors and
disposable-data cutovers stated. The bare-metal evidence path corrected here
keeps existing v1 records readable without reset. Authorized deletion/tombstoning
remains the owning capability's operation and must not masquerade as replacement
accepted content under an old proof. Previous-wire mandates remain refused and
unchanged under the existing settlement contract.

A future reader-removal change accounts for every supported reference and promised
read, including terminal evidence and buyer recovery, before declaring a decoder
unused. Zero nonterminal seller contracts alone is insufficient. That future
change chooses its measurements and deployment evidence. This correction retires
no kind and adds no count endpoint, fleet gate, registry, or legacy decoder.

### 5. Implementation cadence and validation

One implementation round in one session covers document/codec, property
compatibility, persistence, worker, route/client plumbing, package version and
consumer refresh, and focused tests. These form one proof-preservation path;
there is no useful independently deployable intermediate stage. Planning follows
design-review triage and ends with the eleven-part closeout in `openspec/README.md`.

Focused validation pins current-v1 bytes and digests; proves changed view defaults
leave accepted bytes unchanged; rejects nested and outer tampering; proves real
SQLite first-write-wins and restart behavior; observes original-digest publication;
and verifies retained-body signatures, both typed clients through the real route,
field-style properties, and unchanged reader privileges. Outer corruption coverage
includes an otherwise valid nested result.

Affected suites: bare-metal domain evidence and evidence-route tests; storefront
persistence and Alkahest lifecycle tests; buyer payment run-log recovery regression.
Integration uses typed clients against the real application/database with controlled
external boundaries. Existing bare-metal mock-deal stages cover publication and
resolution across services. Local tests do not claim live-purchase qualification.

After refreshing built wheels and consumers, run relevant typing, comment hygiene,
architecture, and `make check-packaging`. Closeout records pipeline evidence,
promotes the named permanent knowledge, checks citations, and archives last.
Disclose every unrun check.

## Permanent knowledge and promotion

| Decision | Permanent destination |
|---|---|
| Accepted representation versus validated application view; proof input ownership | `docs/development/ARCHITECTURE.md#accepted-representations-and-application-views` |
| Evolution preservation, reader obligations, deletion and support-floor distinction | `openspec/specs/deployment-state/spec.md#requirement-evolution-preserves-retained-accepted-representations`; `openspec/specs/deployment-state/spec.md#requirement-preservation-respects-explicit-support-and-retention-boundaries`; `openspec/specs/deployment-state/architecture.md#compatibility-posture` |
| Bare-metal persistence, publication, signed resolution, typed clients and deliberate Python compatibility | `openspec/specs/storefront-publication/spec.md#requirement-bare-metal-evidence-retains-its-proof-representation`; `openspec/specs/storefront-publication/spec.md#requirement-evidence-persistence-verifies-and-preserves-the-first-document`; `openspec/specs/storefront-publication/spec.md#requirement-resolution-preserves-the-existing-signed-evidence-wire-contract`; `openspec/specs/storefront-publication/spec.md#requirement-evidence-clients-retain-field-style-python-usability`; `openspec/specs/storefront-publication/architecture.md#retained-bare-metal-evidence` |
| Roadmap and campaign readiness; no accepted-artifact gap row existed to remove, and no cross-domain completion is claimed | `docs/development/ROADMAP.md#goal-1--consolidate-physical-resource-authority-in-the-provisioning-service`; `openspec/changes/README.md` (Goal 1 row) |

Permanent promotion describes only resulting implemented behavior, without claiming
universal codec coverage or retirement tooling this change does not implement.

## Open Questions

None for this correction. Cross-domain conversion and concrete decoder retirement
require their own design when a change actually evolves those artifacts or retires
a supported kind.
