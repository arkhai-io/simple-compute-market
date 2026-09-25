## Why

Goal 7 exists so a seller whose capacity the marketplace cannot admit against —
typically whole machines arranged directly between the parties — can still be
discovered and introduced. Bare metal is that goal's primary target domain, and
bare metal cannot publish such a listing.

Every bare-metal listing is backed by construction. `BareMetalListing` declares
`capacity_backing: Literal["backed"]`, its binding writers record `backed`, and each
listing requires a `host_id` and `physical_host_id` from a Physical Resource's
publication view. `bare-metal-publication-reads-pool-declarations` makes that
explicit rather than lifting it: a pool declaring itself unbacked yields no
bare-metal listing, and unbacked bare metal is a recorded non-goal there.

The rest of what an unbacked listing needs already exists:

- VM derives unbacked listings from projected pool declarations, binds them with the
  capacity-publication kit's `UnbackedBinding`, keeps them out of every capacity
  path, and publishes only settlement options its domain does not fulfil through
  capacity;
- bare metal already composes `contact-exchange.v1`, the introduction mechanism
  unbacked supply settles through.

What is missing is bare metal using that machinery.

## What Changes

- Derive bare-metal listings from pools that declare themselves unbacked and
  advertise `bare_metal`, through the same kit publication runtime, declaration
  reader, and source reconciliation VM uses.
- Bind each with the kit's `UnbackedBinding` and publish `capacity_backing: unbacked`.
- Never reserve, hold, schedule, or fulfil an unbacked bare-metal listing.
- Publish only settlement options bare metal does not fulfil through capacity, so an
  unbacked bare-metal listing settles by introduction.
- Settle introductions through the domain-neutral composition
  `compose-contact-exchange-across-compute` promotes, revealing the contact of the
  listing's origin seller.
- Own the bare-metal system evidence for Goal 7: unbacked bare-metal discovery reaching
  a usable introduction in a running stack.

## Capabilities

### Modified Capabilities

- `storefront-publication`: bare-metal publication derives unbacked listings from
  unbacked pools under the same rules as VM.

### New Capabilities

None.

## Non-Goals

- Finite unbacked listings, or hosted settlement over unbacked supply. Both are
  anticipated and unowned in Goal 7.
- A bare-metal-specific introduction composition. Bare metal uses the promoted one.
- Asking rates, which `publish-indicative-listing-rates` adds for backed and unbacked
  listings alike.

## Impact

- `domains/bare_metal/src/arkhai_bare_metal/` listing schema and publication.
- The bare-metal storefront's publication, negotiation, and settlement composition.
- `openspec/specs/storefront-publication/spec.md`.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` — re-confirm at implementation time.
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

## Dependencies

- **Depends on `bare-metal-publication-reads-pool-declarations`** (complete), for
  projected pool declarations and the kit publication runtime. That change added the
  requirement that an unbacked pool yields no bare-metal listing, now promoted into
  `openspec/specs/storefront-publication/spec.md`; this change's delta removes it.
- **Blocked on `bare-metal-listing-shapes`**, so an unbacked bare-metal listing is
  discoverable by the compute schema's dimension filters.
- **Blocked on `compose-contact-exchange-across-compute`** Sections 1–3b, for the
  promoted introduction composition and the per-origin contact payload.
- **Unblocks** the bare-metal system evidence of `publish-indicative-listing-rates`.
