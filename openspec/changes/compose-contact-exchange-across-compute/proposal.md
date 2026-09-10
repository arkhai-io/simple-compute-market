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
- Compose the mechanism in the VM storefront, the one remaining compute-family
  domain, so a seller there can settle by introduction. Bare metal already
  composes it; API credits is a separate market family with its own registry
  schema identity and is out of scope.
- Extend introduction delivery to VM, so a revealed introduction reaches its owner
  rather than only being readable.
- Resolve the seller's contact payload per listing origin rather than per
  storefront. `ContactSettlementConfig.contact_payload` is one static value for a
  whole storefront, which is coherent only at one seller per storefront. Goal 7
  publishes listings from several seller sites through one storefront, so a
  storefront-wide payload would reveal the wrong seller's contact details. The
  payload becomes resolvable from the listing's origin site; a single-origin
  deployment resolves to the same value it configures today.
- State normatively that accepted-state interpretation for this mechanism has one
  implementation, and that a composing domain supplies persistence and values
  rather than lifecycle logic.

## Capabilities

### Modified Capabilities

- `contact-exchange-settlement`: accepted-state interpretation and the obligation
  drive sequence have one implementation; a composing domain supplies persistence
  and configured values.
- `introduction-delivery`: delivery is available to every composing domain rather
  than to bare metal alone, and reaches the seller at the origin the listing came
  from.
- `contact-exchange-settlement`: the seller's contact payload is resolved from a
  listing's origin rather than from one static storefront-wide value.

### New Capabilities

None.

## Non-Goals

- Do not give the mechanism kit a framework, HTTP client, or foreign-mechanism
  dependency. Its package boundary is asserted by test and is part of why the
  mechanism composes cleanly. The promoted glue lands in the kit and takes both
  domain reads as injected Protocols, so it adds no persistence type; the boundary
  test's deny list is unchanged and `uuid` is the only permitted root added.
- Do not change the reveal surface, its authentication, its idempotency, or the
  option shape.
- Do not build per-deal contact aliasing. Making the payload resolvable is the hook
  aliasing would also need, but choosing an alias per deal is a separate concern.
- Do not add scalar participation. The mechanism declines it, and
  `unbacked-listing-publication` publishes rates as listing attributes precisely
  so that decision holds.
- Do not couple composition to backing. A capacity-backed listing may settle by
  introduction and an unbacked listing may settle by another mechanism; this
  change must not assume either.

## Impact

- Affected code: the bare-metal storefront's introduction composition, a new
  module and one boundary-test line in `kit/contact-exchange`, and the VM
  storefront's settlement composition, introduction persistence, migration tuple,
  and delivery wiring.
- Affected specification: `openspec/specs/contact-exchange-settlement/spec.md`,
  `openspec/specs/introduction-delivery/spec.md`.
- Not affected: the mechanism kit's registration, option builder, settlement
  configuration, or migrations.

## Dependencies and Related Changes

- **Depends on `contact-payload-retention`.** Composing the mechanism more widely
  multiplies the number of deployments holding contact payloads, and the
  retention obligation is currently satisfied only in principle. The dependency is
  a gate, not a coordination note.
- No longer coupled to `bare-metal-and-credits-domain-stacks` or
  `kit-storefront-composition-seam` for placement. Those own where kit-owned
  *storefront* runtime sits; the promoted glue is mechanism-shaped and lands in the
  mechanism kit, so it does not need their seam. `kit/storefront` was rejected as
  a home because it declares hard Alkahest dependencies — see `design.md`.
- Independent of `unbacked-listing-publication` for the composition work. Either can
  land first; neither assumes the other. Per-origin contact resolution is what makes
  Goal 7's multi-seller value claim true, though, so Goal 7 is not complete for
  introductions until it lands — see `design.md`.
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
