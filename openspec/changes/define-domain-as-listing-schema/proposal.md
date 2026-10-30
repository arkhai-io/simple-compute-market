## Why

"Domain" means different things in different parts of the system, and "family" groups domains along whichever axis the word "domain" left out.

- **Registry.** A registry serves one listing schema, named by its descriptor's `schema` (`compute.market` v2, `api_credits` v1). `ARCHITECTURE.md` already treats the listing schema as the variation axis: "a behavior belongs in the market core when it is invariant across listing schemas".
- **Domain contract.** A `MarketDomainContract` bundles a schema's payload codecs with one way of delivering. VM (`compute.v1`) and bare metal (`bare_metal.v1`) are two domains that publish under the one `compute.market` schema, told apart by `listing_resource.offering_mode`.
- **Family.** A permission scope between `kit/` and a domain. The compute family shares a **schema** across two delivery backends. The proposed api family (`compose-api-family-kit`, PR #299) shares a **backend** across several schemas (API credits, inference).

So compute's domains are backends and api's domains are schemas. Each new market has to pick an axis; container offerings and inference both meet the question.

`agreed-evidence-and-early-termination` (PR #296, D1) defines the protocol as discovery, negotiation, and the mechanism's commitment act; everything after commitment is lifecycle, visible to arbitration only as evidence. Delivery is then lifecycle, yet the code makes the delivery backend part of what a domain is.

Hosting has the same blur. Two registries are two Helm subcharts and two processes. The "multi-domain storefront" is one route set that picks a contract by offering mode. Neither separates the interface a party speaks to from the server that implements it.

## What Changes

This change settles definitions and a target shape for discussion. Implementation is split into follow-up changes once the definitions are accepted.

- **A domain is one listing schema.** A domain's identity is its registry schema identity. A registry's listings are exactly that schema's values; a registry "serving several schemas" serves their union, which is one schema. Payload kinds and contract versions are scoped under the domain, not peers of it.
- **Registry, storefront, and domain are interfaces, not servers.** A registry interface is the discovery routes and descriptor over one schema. A storefront interface is the negotiation routes over one schema. One host may serve several registry or storefront interfaces; the separation can be as shallow as the router: each interface keeps its own base URL, descriptor, principals, and record namespace, and nothing selects an interface from a payload.
- **Whatever negotiation specializes on is a kit, and the listing advertises it.** Identity, payment with its dispute mechanism, and delivery are kit slots. A buyer and a listing are compatible when they share the domain and the buyer can use one advertised choice in every slot. Each negotiation is specialized to {domain, selected kits}, and both sides dispatch the kits' operations.
- **Delivery is a kit, and a receipt is its negotiated detail.** Within the protocol, delivery appears only as the selected delivery kit and its parameters in the Agreement. Access information exchanged after commitment is lifecycle, and matters to the protocol only as evidence against a failure-to-deliver dispute.
- **No family scope.** Code shared between domains is kit code, scoped to the mechanism it is, never to a set of domains. A family vocabulary is either a domain's own schema package or a kit's vocabulary.

## Capabilities

### New Capabilities

None proposed yet.

### Modified Capabilities

Expected once the design settles; spec deltas are not written yet.

- `market-composition`: the domain definition; the storefront as an interface over one schema; kit slots and their dispatch.
- `negotiation-protocol`: compatibility as same domain plus a usable choice in every advertised kit slot.
- `storefront-publication`: listings advertise delivery, as they already advertise settlement options.
- `buyer-orchestration`: candidate selection by domain and kit compatibility.
- `deployment-state`: several registry or storefront interfaces on one host.

## Dependencies and Related Changes

- Builds on `agreed-evidence-and-early-termination` D1 (protocol ends at commitment), PR #296, not yet on `dev`. That change lists "Merging the VM and bare-metal domains" as a non-goal; this change takes the question up (design.md Q1).
- Reframes Goal 3 (one storefront serving several compute-family domains) and Goal 4 (a domain is a composition of kit). design.md, "Effect on in-flight changes", says what each active change would keep or adjust.
- Bears directly on `compose-api-family-kit` (PR #299 and its implementation stack) and the inference domain plan (PR #229): their package placement and the `[[families]]` entry are cheapest to change before they merge.

## Non-Goals

- Changing negotiation messages, round sequencing, or the commitment act.
- Changing payment or dispute kits beyond how a listing advertises them.
- Choosing container delivery, or designing any new delivery kit.
- Implementation in this change; follow-ups are named once the definitions are accepted.

## Impact

- **Vocabulary:** "domain", "family", "kit", "registry", and "storefront" are redefined across `ARCHITECTURE.md`, `ARCHITECTURE.toml`, and the market-composition capability.
- **Packaging (follow-ups):** family kits move under `kit/` as delivery kits (`provisioning/compute`; `domains/api/*` if #299 lands first); `[[families]]` retires; the compute schema moves out of `core/registry/` to its domain.
- **Wire (follow-ups):** listings gain a delivery advertisement; if compute becomes one domain, `listing_resource.offering_mode` becomes that advertisement and `compute.v1` / `bare_metal.v1` become delivery-kit identities.
- **Deployment (follow-ups):** registry and storefront hosts that mount several interfaces; parallel processes remain valid.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

Destinations are provisional until the design is accepted.

- D1 domain definition, D3 kit slots, D5 no family scope → `docs/development/ARCHITECTURE.md` ("Composition from above and below", "Package and dependency layers", "Family kits" replaced, "Shared vocabulary and identities") and `docs/development/ARCHITECTURE.toml` (`[[families]]` removed; delivery kits listed beside payment mechanisms).
- D2 interfaces and hosting → `docs/development/ARCHITECTURE.md` ("Deployment topology", "Capacity publication and multi-domain storefront composition") and `openspec/specs/deployment-state/spec.md`.
- D3 compatibility and D4 delivery advertisement → `openspec/specs/negotiation-protocol/spec.md`, `openspec/specs/storefront-publication/spec.md`, `openspec/specs/buyer-orchestration/spec.md`.
- D1, D3 → `openspec/specs/market-composition/spec.md` and its `architecture.md`.
- Goals 3 and 4 restated → `docs/development/ROADMAP.md`.
