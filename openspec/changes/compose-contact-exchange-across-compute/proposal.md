## Why

`contact-exchange.v1` is composed on bare metal only. Nothing about the mechanism
is bare-metal-specific: its package-boundary test asserts it imports nothing
beyond `market_core`, `market_identity`, `market_settlement_runtime`, and
pydantic — no domain, no provider, no framework.

What is bare-metal-specific is the composition glue that installs accepted-state
interpretation into the reveal service. Reading it, almost none of that is
bare-metal either: it loads a negotiation thread, checks its terminal state,
validates a settlement plan carrying one obligation, re-derives `obligation_ref`,
and drives the obligation to collected. The only domain-specific parts are the
persistence client and its two payload methods.

Composing a second domain by copying that glue would put a second implementation
of mechanism-shaped logic in a domain, against the established rule that an
extracted concern leaves no domain-local copy and that domains retain only the
values and hooks that instantiate a kit mechanism. Doing it once is duplication;
doing it for every compute domain is a maintenance surface where the mechanism's
own invariants get re-derived inconsistently.

`docs/development/ROADMAP.md` records cross-domain contact-exchange composition
beyond bare metal as an unowned gap.

## What Changes

- Promote the domain-neutral part of the introduction composition glue out of the
  bare-metal storefront: accepted-state interpretation, obligation-ref
  re-derivation, and the obligation drive sequence, with persistence injected.
- Leave the bare-metal storefront holding only its persistence client and its
  configured values, matching how it composes every other kit mechanism.
- Compose the mechanism in the remaining compute-family storefront domains, so a
  seller in any of them can settle by introduction.
- Extend introduction delivery to those domains, so a revealed introduction
  reaches its owner rather than only being readable.
- State normatively that accepted-state interpretation for this mechanism has one
  implementation, and that a composing domain supplies persistence and values
  rather than lifecycle logic.

## Capabilities

### Modified Capabilities

- `contact-exchange-settlement`: accepted-state interpretation and the obligation
  drive sequence have one implementation; a composing domain supplies persistence
  and configured values.
- `introduction-delivery`: delivery is available to every composing domain rather
  than to bare metal alone.

### New Capabilities

None.

## Non-Goals

- Do not give the mechanism kit a persistence dependency. Its package boundary is
  asserted by test and is part of why the mechanism composes cleanly; persistence
  is injected, not imported. Where the promoted glue lands is an open question in
  `design.md`, constrained by this.
- Do not change the reveal surface, its authentication, its idempotency, or the
  option shape.
- Do not add scalar participation. The mechanism declines it, and
  `unbacked-listing-publication` publishes rates as listing attributes precisely
  so that decision holds.
- Do not couple composition to backing. A capacity-backed listing may settle by
  introduction and an unbacked listing may settle by another mechanism; this
  change must not assume either.

## Impact

- Affected code: the bare-metal storefront's introduction composition, the
  promoted glue's new home, the remaining compute-family storefront composition
  roots, and their delivery wiring.
- Affected specification: `openspec/specs/contact-exchange-settlement/spec.md`,
  `openspec/specs/introduction-delivery/spec.md`.
- Not affected: the mechanism kit's registration, option builder, settlement
  configuration, or migrations.

## Dependencies and Related Changes

- **Depends on `contact-payload-retention`.** Composing the mechanism more widely
  multiplies the number of deployments holding contact payloads, and the
  retention obligation is currently satisfied only in principle. The dependency is
  a gate, not a coordination note.
- Coordinate with `bare-metal-and-credits-domain-stacks` and
  `kit-storefront-composition-seam`, which own where kit-owned storefront runtime
  sits. The promoted glue's home should follow their seam rather than inventing a
  parallel one.
- Independent of `unbacked-listing-publication`. Either can land first; neither
  assumes the other.
- Discharges the remaining half of the recorded open gap for cross-domain
  contact-exchange composition in `docs/development/ROADMAP.md`.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — no change expected; the
      composition-from-kit principle is already recorded. Re-confirm rather than
      assuming.
- [x] Existing subsystem specification —
      `openspec/specs/contact-exchange-settlement/spec.md` and
      `openspec/specs/introduction-delivery/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Accepted-state interpretation and the obligation drive sequence have one
  implementation; a composing domain supplies persistence and configured values —
  `openspec/specs/contact-exchange-settlement/spec.md`.
- Delivery is available to every composing domain and remains non-authoritative —
  `openspec/specs/introduction-delivery/spec.md`.
