# Market core extraction — decision record

> **Status: complete.** The extraction this doc planned has landed: the
> package graph expresses the core/kit/domain split, the boundaries are
> enforced by tests, and distribution names mirror the layers
> (`arkhai-{core,kit,vms}-*`). This file is kept as the record of the
> principle and the decisions made along the way — it is no longer an
> implementation plan. Remaining work is aggregated in `TODO.md` → "Core
> Stack"; the follow-on behavior work (settlement lifecycles,
> mechanism-neutral plan carrier, capacity/site authority) is planned in
> `design-settlement-lifecycle-and-capacity.md`. The current-state
> package layout lives in `ARCHITECTURE.md` → "Package layout".

## Principle (the filing test)

The core/kit/domain split is about **composition direction**, not only
universality. `core` is composed _from above_: it defines role shapes,
protocol boundaries, and the points where behavior is injected. `kit` is
composed _from below_: reusable implementations and utilities that can help
an injected dependency do its job. Domain packages are also from-below:
they implement the hooks for a concrete market shape and may depend on kit
packages, but they do not depend back up on `core` — only composition
roots (the domain executables) may import core.

Universality is a useful smell, but it is not the filing rule. A behavior
belongs in core when the core must require it as part of the role contract
or protocol skeleton. A behavior belongs in kit or a domain package when it
is an implementation of one of those requirements. "Requiring the hook" is
from above; "implementing it" is from below.

Negotiation is an exchange of opaque, schema-defined **messages**. The
core's universal surface is that the whole buyer pipeline is well-typed
end to end:

```
listings = discover(query)
terms    = aggregate(negotiate, listings)
receipt  = settle(terms)
```

The core knows only these shapes and how they compose: messages flow
between participants; a negotiation reduces its message history to
`Terms`; `settle(Terms) → Receipt`. It knows nothing about message
_content_ (offer / counter / bid / acceptance are schema vocabulary),
how a participant picks its next message, or floor/ceiling/whitelist
semantics — price and escrow shape are the same kind of thing, policy
over advertised listing data. Settlement verification needs both sides
to derive identical `Terms`, which holds because `negotiate` is a pure
reduction over a shared message history (the echo mechanism keeps the
histories shared). The schema-specific parts plug in from below: the
discovery query (filter-spec), the aggregation policy, the per-turn
negotiation policy, and the `settle` implementation.

> **Naming note (still open):** the code says `EscrowProposal` /
> `Decision.proposal` where this framing says message/terms. Aligning
> the concrete names rides the settlement-plan carrier work (lifecycle
> doc, work item I.1).

## Hook surface

The core owns the _structure_ of the exchange — the round loop, signed
transport, thread/history persistence, middleware-chain execution
semantics, the determinism contract — and exposes two behavior hooks:

| Core hook   | Type | Absorbed the legacy hooks |
| ----------- | ---- | ------------------------- |
| `negotiate` | per-turn message policy `respond(history) → message \| terms`, run by the core's engine | `chain`, `derive_prices` (policy input), `build_escrow_proposal` (opening message), `confirm_settlement` (final message) |
| `settle`    | `Terms → Receipt` | `build_escrow_terms` + `create_escrow` (materialize-then-submit is internal factoring) |

The merge-vs-separate rule: hooks merge when the core does nothing
between them; they stay separate when a core-enforced boundary sits in
the gap (the determinism contract lives between `negotiate` and
`settle`, so those are two phases with `Terms` as the typed handoff).
The round/chain engine itself stays in core until a structurally
different negotiation (sealed-bid auction, order book) is concrete —
factoring it out beforehand is a seam with one implementation.

On the seller side the same shape holds: `core_storefront`'s sync
negotiation owns protocol, persistence, and events, and delegates each
decision to an injectable seller round hook; the VM hook owns strategy
lookup, the capacity snapshot for the inventory guard, and the
configured middleware chain.

## Packaging decisions

The layout that landed (per-package detail in `ARCHITECTURE.md`):

```
core/        arkhai-core (carriers), buyer/, storefront/, registry/,
             registry-client/, storefront-client/
kit/         identity/, policy/, alkahest/, config/
domains/vms/ listings/, negotiation/, settlement/, provisioning/   (concept modules, no wheels)
             buyer/, storefront/, provisioning/service/            (executable packages)
```

**Executable entrypoints split by role.** The buyer executable is
core-owned: `arkhai-core-buyer` ships the `market` console script, the
verb skeleton, and schema-plugin discovery (`market.buyer_plugins`
entry-point group); domain buyer packages ship plugins, not competing
CLIs. The buyer is the distribution-sensitive role — one binary, many
registry schemas — and plugin inversion preserves the dependency
direction (core discovers plugins by contract; it never imports
`domains.*`). Without plugins the core binary offers only generic
`--filter` passthrough and raw listing output, never a concrete buy
experience. Storefront executables are the opposite: domain packages
own them, one storefront process per market schema domain — a
multi-domain operator runs parallel storefront processes sharing the
capacity layer underneath (site authority), not one multi-domain
process. The shared parts are libraries in `core_storefront`, not a
shared process; lifting the app assembly into core is revisited only
when a second domain shows what is actually invariant. The registry
stays a core executable with schema injected as config
(`filter-spec.yaml`).

**The carriers wheel survives.** `arkhai-core` (import name
`market_core`) is the protocol-carrier package for the
negotiation/settlement wire shapes (escrow proposals/terms, rate slots,
the opaque provision-terms envelope) that buyer and storefront must
derive identically from the same message history. It cannot fold into
either role package without inverting a dependency, and duplicating it
would break the determinism contract, so it stays a peer of the
protocol clients. Two rules, both enforced: zero domain vocabulary (the
`compute.v1` accessors live in `domains/vms/provisioning/terms.py`; the
only residue is the explicitly marked legacy wire shim that leaves with
the `storefront-client` wire bump), and zero dependencies beyond
pydantic (`core/tests/unit/test_carrier_purity.py`).

**Known divergence — settlement-mechanism vocabulary.** The purity
rules cover the resource/market axis and the import graph, but the
current escrow carriers bake one settlement *mechanism* into their
required fields: `EscrowTerms` is literally the alkahest
`doObligation(data, expirationTime)` call shape, and
`EscrowProposal`/`AcceptedEscrow` key on `(chain_name,
escrow_address)`. Alkahest must not be the only structurally supported
mechanism (fiat escrow is already customer-requested: same
payer/claimant/amount/expiration/conditions lifecycle, different
identifier scheme and verification semantics). The wheel's contract is
therefore *lifecycle universals + mechanism envelope*, not alkahest
shapes — each obligation carries a mechanism tag with opaque params
whose deterministic interpretation lives in kit codecs (`kit/alkahest`
first, fiat providers later), the same pattern as the `ProvisionTerms`
`{kind, payload}` envelope. Deliberately not fixed standalone: the
carrier reshape rides the settlement-plan generalization (lifecycle doc
work item I.1) so the `/negotiate/*` wire churns once, not twice.

**Distribution model (the why).** A registry centralizes a schema; the
per-schema instantiation is the _registry operator's_ deliverable. The
core repo ships the role shells plus the kit; an operator publishes a
schema (the filter-spec plus its typed client counterpart, versioned
together) and the storefront/buyer plugins. The first realistic driver
is two compute registries with incompatible listing shapes — not a
second asset class.

## Enforcement

Three boundary rules are tests, not documentation:

- `domains/vms/storefront/tests/unit/test_architecture_imports.py` —
  kit packages and VM concept modules import no core or composition
  packages; kit additionally imports no domains.
- `core/tests/unit/test_carrier_purity.py` — `market_core` imports
  nothing beyond stdlib + pydantic.
- `core/buyer/tests/unit/test_cli.py` + `domains/vms/buyer/tests/test_plugin_export.py`
  — the no-plugin core CLI has no concrete market behavior; the VM
  plugin is discovered through real entry-point metadata.

## What was deliberately deferred

- A second resource domain (storage, bandwidth) — validate with
  heterogeneous _compute_ schemas first.
- Shipping multiple schema plugins from this repo — the plugin
  mechanism is in place; a second schema package waits for a second
  schema.
- Generic aggregation beyond the current buyer aggregation policy.
- Settlement-mechanism generality in code (the decision is recorded
  above; the implementation rides the plan-carrier work).

## References

- `ARCHITECTURE.md` → "Organizing Principle" and "Package layout" —
  current state
- `TODO.md` → "Core Stack" — all remaining work, in one place
- `docs/development/design-settlement-lifecycle-and-capacity.md` —
  follow-on architecture: settlement lifecycles, mechanism-neutral plan
  carrier, shared capacity / site authority
- `docs/development/RELEASING.md` — distribution names + publishing
