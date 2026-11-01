## Why

Bare-metal Alkahest fulfillment stores canonical lease-ready evidence and publishes
its digest. Recovery nevertheless decodes the document through current models,
checks its nested result through model serialization, recomputes the outer digest
for publication, and signs a reserialized body when serving it. A new model default
can change the digest of unchanged accepted content. Selecting a row by its digest
also does not verify the retrieved body.

Accepted content and its application view need separate authority. Negotiation and
Arkhai payments already retain exact Agreement bytes. This change corrects the
concrete bare-metal portable-evidence path and records accurate evolution guidance
without changing payment protocols.

## What Changes

- Introduce a bare-metal-owned immutable evidence document containing retained
  canonical UTF-8 bytes, their verified digest, and a separate validated view.
- Verify the stored document against its expected digest before decoding, and
  verify its nested result from original JSON rather than a live-model dump.
- Carry the document through first-write-wins persistence, Alkahest recovery and
  publication, authenticated evidence resolution, signing, and both typed clients.
- Preserve existing v1 JSON, signed envelope, routes, canonicalization, identity
  derivation, and authorization. Preserve field-style Python reads with explicit
  read-only properties; version the nominal type change as a minor release of
  `arkhai-bare-metal`.
- Clarify preservation while retained, protocol-owned proof rules, and explicit
  reader support boundaries. Keep authorized deletion and unsupported-wire refusals.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: accepted-representation evolution and reader support boundaries.
- `storefront-publication`: retained-byte bare-metal evidence verification,
  publication, resolution, and client behavior.

## Non-Goals

- No generic envelope, decoder registry, fleet inventory, retirement-count endpoint,
  or cross-domain conversion project. No artifact kind is retired.
- No revival of retired bare-metal payloads or hosted-fiat recovery.
- No repair of API-credit issuance evidence or generated payment wire models.
- No new wire wrapper, canonicalization, hash, signature protocol, or accepted
  identity. Arkhai payments retains its JCS rules.
- No change to contact deletion/tombstoning, previous-wire mandate refusal,
  publication-uncertainty handling, or access privileges.

## Status

Design review at `112cc32306e2d6cc6e628a8ec3eadaaa6f695c2e` found no findings;
its triage advanced to planning. The checked plan is ready for implementation.
The settled cadence remains one coherent implementation round; intermediate
section commits are not independently deployable.

## Impact

- **Code:** bare-metal evidence codecs, route service and clients, exports,
  storefront evidence persistence, Alkahest lifecycle, thin HTTP binding, affected
  tests, and package metadata/locks.
- **Data:** reuse `lease_ready_evidence_json` and `lease_ready_evidence_digest`.
  No accepted-content rewrite, schema backfill, or database reset.
- **Wire:** unchanged v1 evidence and signed-response shapes. Unknown kinds remain
  unsupported; existing readers receive the same fields.
- **Python:** client method signatures and the named signed-response carrier stay.
  Its evidence document preserves field-style reads, nested result fields, and
  byte-derived digest operations. The nominal nested type changes, requiring a
  minor domain-distribution release and refresh of affected consumers.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — accepted representation versus decoded
  view, protocol-owned proof rules, and bounded schema-evolution guidance.
- [x] Existing subsystem specifications — `deployment-state` and
  `storefront-publication`, including architecture companions.
- [ ] New subsystem specification — none.
- [ ] No permanent documentation change — not applicable.

### Knowledge to promote

- Preservation during evolution, proof inputs, retention and compatibility floors —
  `docs/development/ARCHITECTURE.md`, `openspec/specs/deployment-state/spec.md`,
  and `openspec/specs/deployment-state/architecture.md`.
- Bare-metal documents, verification, first-write-wins recovery, signed JSON, and
  client compatibility — `openspec/specs/storefront-publication/spec.md` and
  `openspec/specs/storefront-publication/architecture.md`.
- Bounded correction and remaining inventory disposition —
  `docs/development/ROADMAP.md` and this change's campaign row at closeout.

## Dependencies and Related Changes

No prerequisite. The originating host-identity rename used an explicit
preproduction reset; that exception is not a recurring upgrade strategy.
Negotiated Agreement retention and payment servicing remain the existing contracts
in `openspec/specs/negotiation-protocol/spec.md` and
`openspec/specs/settlement-servicing/spec.md`.
