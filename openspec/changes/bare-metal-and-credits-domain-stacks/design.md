# Design

## Context

Verified 2026-08-06; re-verify before implementing.

- `domains/vms/compose.yml` and `domains/apicredits/compose.yml` exist;
  `domains/bare_metal/` has no compose file. (*2026-09-26:* it does now, with a
  standalone lane — see "Re-grounding".)
- No file under `e2e-tests/` references bare metal or API credits. Every e2e scenario is
  a VM deal. (*2026-09-26:* `scenarios/bare_metal/` and the API-credits path exist.)
- `test-compatibility`'s architecture already distinguishes contract and conformance
  fixtures from implementation tests, and names the API-credits middleware conformance
  session as the model for independent implementations agreeing on one observable
  protocol.
- API credits currently reimplements eight storefront concerns the kit extractions take
  over.

## Goals / Non-Goals

**Goals:** two domains that deploy and prove a full deal; the goal's completion test met.

**Non-Goals:** further extraction, new domains, buyer work, layout churn, VM changes.

## Decisions

### The completion test is a full deal per domain, not a smoke test

A stack that starts and a health check that passes prove neither negotiation nor
settlement nor delivery. The goal's value is that a domain built by composition actually
works, and only a complete deal path demonstrates that.

So each domain's scenario covers discovery, negotiation, settlement, delivery, and
teardown — the same span the VM scenarios already cover, which also means the existing
scenarios are the template rather than something to invent.

### E2E fixtures probably assume VM, and generalizing them is part of the work

Every existing scenario is a VM deal, so shared fixtures and helpers have had no reason
to be domain-neutral. Expect assumptions about listing shape, provisioning, and teardown
baked into helpers rather than into scenarios.

Stated as a decision because the natural response — copying the VM scenarios and editing
them per domain — reproduces the duplication this goal exists to remove, one layer up.
The fixtures generalize; the scenarios stay thin.

### API credits is recomposed, not merely made to pass

API credits already completes deals with its own implementations. It would pass an e2e
scenario today without any of this goal's work.

That is exactly why recomposition is in scope: the goal is not "API credits has a test,"
it is "API credits is a composition of kit." A passing e2e over a parallel implementation
would satisfy the letter of the completion test and none of its value.

### Whether bare metal stands alone or composes into a shared storefront is deferred

`multi-domain-storefront-composition` may make bare metal a second contract in the VM
storefront process rather than its own service. Either satisfies this change: what it
proves is a working deal path, not a deployment topology.

Deferring keeps this change independent of Goal 3's sequencing. The stack definition
should be written so the answer can change without rewriting the scenarios.

### Teardown is domain-defined, and bare metal proves access revocation

The shared lifecycle names a teardown boundary without imposing a VM payload.
API credits ends the purchased grant by consuming it to authoritative HTTP 402.
Bare metal requests teardown through the authenticated storefront, waits for the
selected-site lease-release result, and then proves the previously working SSH
access no longer works. Whole-host release is therefore not modeled as VM
destruction, and neither scenario reads a provisioning authority directly.

That SSH proof needs a real host, which the end-to-end pipeline never has. The
bare-metal deal that runs in the pipeline is mock-provisioned and owned by
`bare-metal-mock-provisioned-deal`; it observes teardown as far as the site's
returned capacity, and the SSH proof stays the protected lane's.

## Risks / Trade-offs

- **[Scenarios are copied per domain rather than fixtures generalized]** → The main risk,
  and it reproduces the duplication this goal removes.
- **[E2E requires a live service stack that CI cannot run]** → This repository has
  recorded exactly this before: e2e changes validated statically because no compose stack
  was available. Plan for a live run as an explicit gate rather than discovering it at
  merge.
- **[Bare metal's first real deal path surfaces defects unrelated to composition]** →
  Likely, since it has never completed a deal. Those are bare-metal findings; they belong
  to its own change rather than being absorbed here.
- **[API-credits recomposition is treated as optional because it already works]** → Named
  above; it is the difference between satisfying the test and delivering the goal.

## Migration Plan

1. Generalize e2e fixtures away from VM assumptions.
2. API-credits recomposition and its deal-path scenario.
3. Bare-metal stack definition.
4. Bare-metal deal-path scenario.

API credits comes first: it has a working implementation to compare against, so a failing
scenario there is a recomposition defect rather than an unknown.

Rollback is per step; nothing here changes persisted state or wire contracts.

## Open Questions

- **Should the per-domain deal path become a shared conformance scenario rather than
  three separate suites?** Attractive — it would make "can this domain trade" a fixture a
  new domain runs. Deferrable: it is better designed against two real domains than
  predicted from one.

## Re-grounding (2026-09-26)

### What exists now

- **Stack.** `domains/bare_metal/compose.yml`, `compose.bare-metal.yml`,
  `compose.bare-metal-local.yml`, `dev-env/bare-metal/`, a Dockerfile, a Helm chart
  with render tests, and `dist-bare-metal-storefront`/`dist-bare-metal-buyer` targets.
  The bare-metal end-to-end lane (one mock-profile site, a bare-metal storefront, a
  registry, a dev chain) runs in the pipeline and proves publication.
- **Buyer.** `domains/bare_metal/buyer/` contributes `bare_metal.v1` through
  `market.buyer_domains`, with `list/show/buy/start/complete/status/result/access/
  teardown/reclaim` and the introduction commands, a plugin declaring
  `DomainCapability.BUYER`, and composition tests. Delivered by the parallel producer
  whose contribution `multi-domain-storefront-composition` recorded as commit
  `18083392`, since merged.
- **Seller.** The bare-metal storefront starts through the shared
  `StorefrontAppConfig`, contributes `bare_metal` through
  `market.storefront_contributions`, and composes kit publication
  (`publication_composition.py` over `market_capacity_publication`).
- **Scenarios.** `test_bare_metal_deal.py` (real host; protected lane) and
  `test_bare_metal_publication.py` (pipeline). The mock-provisioned deal is
  `bare-metal-mock-provisioned-deal`'s.

### What bare metal still copies

The one extracted concern with a bare-metal-local copy is negotiation.
`negotiation_service.py` (`BareMetalNegotiationService.open`, `_open_exact_selection`,
`_validate_physical_selection`, `_build_accepted_obligation`), `negotiation.py`
(`BareMetalSellerRoundHook`), the `/api/v1/negotiate/new` and
`/api/v1/negotiate/{id}` routes in `api.py`, and their thread persistence in
`sqlite_client.py` reimplement what `kit/negotiation-runtime` owns for VM and API
credits: round ordering, canonical-principal binding, acceptance, hold placement,
and artifact construction. `kit-owned-negotiation-runtime` 3.3 exposed
schema-opaque resolvers and `NegotiationDomainHooks` for exactly this consumer.

The listing routes in `api.py` are the second, smaller copy; the shared shell's
listing routes read the common binding that bare-metal publication now writes.

### Decision: composition onto the kit is this change's, not an extraction

The non-goal "do not extract further concerns" stands. Nothing is being extracted:
the kit exists, and bare metal is the last domain not composed onto it. The work is a
`NegotiationDomainHooks` implementation (opening validation of the closed
`bare_metal.v1` demand, physical selection, exact settlement option, hosted binding,
accepted-artifact construction) and the deletion of the parallel service, routes,
and persistence — the same shape `kit-owned-negotiation-runtime` 3.2 applied to VM
and API credits.

`multi-domain-storefront-composition`'s gate 3.7 (a `legacy_migration` adapter for
`derived_bare_metal_listings`) is void: the archived publication change dropped that
table and bare metal carries no upgrade path because it is not deployed.

### Migrated requirements (2026-09-26)

`bare-metal-buyer-domain` (0 of 41 tasks; the package it planned was delivered) and
`market-platform-bare-metal-10-storefront-composition` (implemented and promoted but
for verification) were archived rather than kept as audit-only changes. Each draft
requirement was checked against the permanent specs and dispositioned:

| Draft requirement | Disposition |
|---|---|
| Bare-metal buyer commands use the generic role | Generic parts are `buyer-orchestration`'s "Plugin-composed buyer CLI" and "Domain-provided buyer integration". The bare-metal-specific scenario (a provisioning route offered to the buyer is rejected) → `bare-metal-mock-provisioned-deal`, `buyer-orchestration` delta |
| Bare-metal demand is exact and buyer-bounded | → `bare-metal-mock-provisioned-deal`, `buyer-orchestration` delta (private-key rejection, override rejection, terms mismatch) |
| Bare-metal settlement choice and recovery are immutable | Already promoted: "Bare-metal buyers preserve accepted hosted authority", "Buyer recovery binds public principal", "Hosted buyer action handling". Dropped as duplicate |
| Public lease result and private access retrieval are separate | Core scenario promoted ("Accepted buyer retrieves SSH coordinates"). Strict-decoding scenarios → `bare-metal-mock-provisioned-deal`, `buyer-orchestration` delta |
| Buyer teardown is authenticated and idempotent | → `bare-metal-mock-provisioned-deal`, `buyer-orchestration` delta, together with `bare-metal-10` 4.6's duplicate-call and exactly-once-release cases |
| Bare-metal negotiation preserves demand and authority ownership | → this change, `negotiation-protocol` delta; verified when bare metal composes the kit |
| Bare-metal negotiation resume is transcript-exact | → this change, `negotiation-protocol` delta (one scenario kept; the rest is `buyer-orchestration`'s generic resume rule) |
| Bare-metal buyer ships as a clean wheel contribution | → this change, `deployment-state` delta |
| Buyer configuration separates public routing, profile identity, access input, and mechanism secrets | Already promoted: "Buyer configuration references profiles without secrets", "Bare-metal hosted roles remain independently secret-scoped". Dropped |
| Buyer deployment does not invent a seller topology | → this change, `deployment-state` delta |
| Bare-metal buyer is an independently installable domain plugin | Already promoted generically: "Plugin-composed buyer CLI", "Shipped domains are loaded", "Unsupported contract version is installed". Dropped |
| Bare-metal buyer dependencies point downward and across public clients only | → this change, `test-compatibility` delta (package-boundary scenario) |
| Implementation is gated by accepted producer contracts | Process text about a change that no longer exists. Dropped |
| Bare-metal buyer passes shared and domain-focused conformance | Shared suite is "Shared domain conformance suite". Domain-focused strict decoding → `bare-metal-mock-provisioned-deal`; package boundary → this change |
| Recovery matrix proves exact profile, agreement, and operation reuse | Profile rotation is "Buyer recovery binds public principal". Restart-after-settlement and restart-after-teardown → `bare-metal-mock-provisioned-deal` (its pause/step controls make them deterministic) |
| Installed-artifact end-to-end evidence uses real whole-host effects | The protected lane: task 4.1 here and `add-bare-metal-hosted-settlement`'s release-qualified evidence; credential isolation is "Bare-metal hosted evidence is attributed by layer". Dropped as duplicate |
| Prerequisite evidence fails closed | Process. Dropped |
| *(bare-metal-10)* Deployable bare-metal storefront composition | Promoted under "Role-owned executable composition" ("Seller loads the bare-metal contribution in a shared shell") and "Independently deployable bare-metal seller role". The shared-provisioner scenario is `compute-40`'s. Dropped |
| *(bare-metal-10)* Truthful pre-fulfillment seller protocol | Superseded: fulfillment is composed. The pause-survives-restart scenario → `bare-metal-mock-provisioned-deal`'s lifecycle controls |
| *(bare-metal-10)* Trusted bare-metal resource projections | Promoted by the archived publication change as `site-capacity`'s "Physical inventory and grouped capacity are separate projections". Dropped |
| *(bare-metal-10)* Trusted selected-site routing | Promoted as `storefront-publication`'s "Site-pinned claim routing" and "Trusted listing mappings route to one site". Dropped |

`bare-metal-10`'s open verification (4.6, 5.4, 5.5, 6.1–6.4) is split: integration
cases → `bare-metal-mock-provisioned-deal`; render tests, operator examples, and
suite runs → this change's Section 3 and 5; the `compute-40` prerequisite note →
`compute-40` itself.
