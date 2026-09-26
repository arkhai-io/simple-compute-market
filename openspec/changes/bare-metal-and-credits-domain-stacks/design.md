# Design

## Context

Verified against the tree at planning time; re-verify before implementing.

- **Stacks.** `domains/vms/compose.yml`, `domains/apicredits/compose.yml`, and
  `domains/bare_metal/compose.yml` exist; `compose.bare-metal.yml`,
  `compose.bare-metal-local.yml`, and `dev-env/bare-metal/` stand up the bare-metal
  end-to-end lane (one mock-profile site, a bare-metal storefront, a registry, a dev
  chain), which runs in the pipeline and proves publication. Bare metal has a
  Dockerfile, a Helm chart with render tests, and `dist-bare-metal-storefront` /
  `dist-bare-metal-buyer` targets.
- **Buyer.** `domains/bare_metal/buyer/` contributes `bare_metal.v1` through
  `market.buyer_domains`, with `list/show/buy/start/complete/status/result/access/
  teardown/reclaim` and the introduction commands, a plugin declaring
  `DomainCapability.BUYER`, and composition tests.
- **Seller.** The bare-metal storefront starts through the shared
  `StorefrontAppConfig`, contributes `bare_metal` through
  `market.storefront_contributions`, and composes kit publication
  (`publication_composition.py` over `market_capacity_publication`).
- **What bare metal still copies.** Negotiation is the one extracted concern with a
  bare-metal-local implementation: `negotiation_service.py`
  (`BareMetalNegotiationService.open`, `_open_exact_selection`,
  `_validate_physical_selection`, `_build_accepted_obligation`), `negotiation.py`
  (`BareMetalSellerRoundHook`), the `/api/v1/negotiate/new` and
  `/api/v1/negotiate/{id}` routes in `api.py`, and their thread persistence in
  `sqlite_client.py` reimplement what `kit/negotiation-runtime` owns for VM and API
  credits: round ordering, canonical-principal binding, acceptance, hold placement,
  and artifact construction. The kit exposes schema-opaque resolvers and
  `NegotiationDomainHooks` for exactly this consumer. The listing routes in `api.py`
  are a second, smaller copy; the shared shell's listing routes read the common
  binding that bare-metal publication writes.
- **Scenarios.** `scenarios/bare_metal/test_bare_metal_deal.py` (real host; protected
  lane) and `test_bare_metal_publication.py` (pipeline) exist, as does the API-credits
  deal path. The mock-provisioned bare-metal deal that runs on every pipeline run is
  `bare-metal-mock-provisioned-deal`'s.
- **API credits** still carries local implementations of concerns the kit
  extractions own.
- `test-compatibility`'s architecture distinguishes contract and conformance fixtures
  from implementation tests, and names the API-credits middleware conformance session
  as the model for independent implementations agreeing on one observable protocol.

## Goals / Non-Goals

**Goals:** two domains that deploy and prove a full deal with no domain-local copy of
an extracted concern; the goal's completion test met.

**Non-Goals:** further extraction, new domains, building the bare-metal buyer or the
mock and lifecycle controls (`bare-metal-mock-provisioned-deal`), layout churn, VM
changes.

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

The shared shell can host bare metal as a second contract in the VM storefront
process rather than as its own service; the bare-metal lane runs it standalone. Either
satisfies this change: what it proves is a working deal path, not a deployment
topology. The stack definition is written so the answer can change without rewriting
the scenarios.

### Composing bare metal onto the kit is this change's, not an extraction

The kit negotiation runtime exists and bare metal is the last domain not composed onto
it. The work is a `NegotiationDomainHooks` implementation — opening validation of the
closed `bare_metal.v1` demand, physical selection, exact settlement option, hosted
binding, accepted-artifact construction — and the deletion of the parallel service,
routes, and persistence, the same shape the VM and API-credit compositions took. No
new concern is extracted; the non-goal against further extraction stands.

Bare metal carries no legacy listing population to migrate: it is not deployed and
its common binding is the only listing mapping, so no `legacy_migration` adapter is
owed.

`bare-metal-listing-shapes`, which lands first, adds a seller inventory guard to bare
metal's current opening path. Its substance is a pure domain function in
`arkhai_bare_metal` that rechecks a listing's shape and region against its site's
projection. The storefront only fetches the projection and maps the outcome to a
status. `validate_opening` calls the same function, so the move carries the fetch and
the mapping, not the check.

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

## Requirement ownership

The bare-metal buyer and seller requirements this change verifies (Section 4b) and
those `bare-metal-mock-provisioned-deal` verifies are split by where the behavior is
proven: negotiation ownership and resume, the clean wheel, independent authorities,
and the package boundary here, where bare metal composes the kit and the stack is
stood up; exact demand, strict result and evidence decoding, idempotent teardown, and
restart recovery in the mock-provisioned deal, which is the only bare-metal deal that
runs on every pipeline run. Requirements already stated generically for every buyer
domain — plugin composition, the shared conformance suite, profile-bound recovery,
secret-free configuration — are not restated per domain.
