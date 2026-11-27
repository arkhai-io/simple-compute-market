## Why

"Domain" means different things in different parts of the system, and the package layout encodes a notion of "market" that has no fixed meaning.

- **Registry.** A registry serves one listing schema, named by its descriptor's `schema` (`compute.market` v2, `api_credits` v1). `ARCHITECTURE.md` already treats the listing schema as the variation axis: "a behavior belongs in the market core when it is invariant across listing schemas".
- **Domain contract.** A `MarketDomainContract` bundles a schema's payload codecs with one way of delivering. VM (`compute.v1`) and bare metal (`bare_metal.v1`) are two domains publishing under one `compute.market` schema.
- **Family.** Sibling domains sharing a vocabulary, declared as a scope between `kit/` ("knows no market") and a domain. Compute's family shares a schema vocabulary across two delivery backends; the proposed `api` family (PR #299) shares a delivery backend across several schemas. Because `kit/` is defined as "knows no market", shared libraries that mention a market concept are pushed under `domains/` beside the domains, and a kit that supports some trades and not others has no clear home.

In a decentralized market there is nothing that realizes "a market" beyond its registries, storefronts, and buyer clients. The only grouping with a concrete, externally visible meaning is the set of those that interoperate, which federates around a registry's schema. Code two such sets share is a library relation, as two websites sharing a web framework are not one site.

`agreed-evidence-and-early-termination` (PR #296, D1) defines the protocol as discovery, negotiation, and the mechanism's commitment act; everything after commitment is lifecycle. Delivery is then lifecycle, yet the code makes the delivery backend part of what a domain is.

The repository also wants inference built by composing what API credits already has rather than copying it, as bare metal was copied from VM and is still being reconciled. That needs a placement rule under which shared code has an obvious home in `kit/` and a copy is a visible structural error.

## What Changes

This change settles definitions and a target shape for discussion. Implementation is split into follow-up changes once the definitions are accepted.

- **A domain is one listing schema** and the set of registries, storefronts, and buyer clients compatible with it. Payload kinds and contract versions are scoped under the domain.
- **Registry, storefront, and domain are interfaces, not servers.** One host may serve several interfaces, separated as shallowly as the router.
- **Whatever negotiation specializes on is a kit, and the listing advertises it.** Identity, payment with its dispute mechanism, and delivery are kit slots; compatibility is the same domain plus a usable choice in every slot.
- **Delivery is a kit, and a receipt is its negotiated detail.**
- **Folders claim the dependency order, and the code must not contradict the claim.** `core < kit < domains`; inside any folder, loose packages sit below its subfolders; sibling subfolders are incomparable unless an edge is declared. Domains are flat; kit is flat except for groups (`kit/api/`, `kit/compute/`, `kit/payments/`) that may claim more structure than exists yet. A contradiction means the folders or names are wrong. This one rule replaces layer and scope; kind is unchanged.
- **Parents define interfaces; children implement them.** Machinery that must work with any member of a group speaks an interface in the loose base, which the group's members implement and a domain's entry point wires.

## Capabilities

### New Capabilities

None proposed yet.

### Modified Capabilities

Expected once the design settles; spec deltas are not written yet.

- `market-composition`: the domain definition; the storefront as an interface over one schema; kit slots, their interfaces, and their dispatch.
- `negotiation-protocol`: compatibility as same domain plus a usable choice in every advertised kit slot.
- `storefront-publication`: listings advertise delivery, as they already advertise settlement options.
- `buyer-orchestration`: candidate selection by domain and kit compatibility.
- `deployment-state`: several registry or storefront interfaces on one host.

## Dependencies and Related Changes

- Builds on `agreed-evidence-and-early-termination` D1 (protocol ends at commitment), PR #296, not yet on `dev`.
- Restates the placement rules of `align-package-paths-with-layers` (in design) and the families of ARCHITECTURE.md; design.md lists the paths that change.
- Bears directly on `compose-api-family-kit` (PR #299 and its implementation stack) and the inference domain plan (PR #229): their package placement and the `[[families]]` entry are cheapest to change before they merge.
- Agrees with the structural work in flight: every dependency the new rule flags is already an `[[exceptions]]` row or owned by `kit-owned-storefront-shell` or `move-escrow-into-alkahest`.

## Non-Goals

- Changing negotiation messages, round sequencing, or the commitment act.
- Changing payment or dispute kits beyond how a listing advertises them and the interface they implement.
- Choosing container delivery, or designing any new delivery kit.
- Implementation in this change; follow-ups are named once the definitions are accepted.

## Impact

- **Vocabulary:** "domain", "family", "kit", "registry", "storefront", "layer", and "scope" are redefined across `ARCHITECTURE.md`, `ARCHITECTURE.toml`, and the market-composition capability.
- **Architecture check (follow-up):** `make check-architecture` reads the order from the folder tree and declared edges instead of scope atoms.
- **Packaging (follow-ups):** shared compute code moves to `kit/compute/`, the fork's `domains/api/*` to `kit/api/`, payment kits to `kit/payments/`; `domains/` holds only each domain's schema and entry points.
- **Wire (follow-ups):** listings gain a delivery advertisement; compute's registry schema follows Q1.
- **Deployment (follow-ups):** registry and storefront hosts that mount several interfaces; parallel processes remain valid.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

Destinations are provisional until the design is accepted.

- D1 domain definition, D3 kit slots → `docs/development/ARCHITECTURE.md` ("Composition from above and below", "Shared vocabulary and identities") and `openspec/specs/market-composition/spec.md` with its `architecture.md`.
- D2 interfaces and hosting → `docs/development/ARCHITECTURE.md` ("Deployment topology") and `openspec/specs/deployment-state/spec.md`.
- D3 compatibility and D4 delivery advertisement → `openspec/specs/negotiation-protocol/spec.md`, `openspec/specs/storefront-publication/spec.md`, `openspec/specs/buyer-orchestration/spec.md`.
- D5 folder order and D6 interfaces → `docs/development/ARCHITECTURE.md` ("Package and dependency layers", "Family kits" replaced) and `docs/development/ARCHITECTURE.toml`.
- Goals 3 and 4 restated → `docs/development/ROADMAP.md`.
