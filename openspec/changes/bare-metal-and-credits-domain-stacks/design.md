# Design

## Context

Verified 2026-08-06; re-verify before implementing.

- `domains/vms/compose.yml` and `domains/apicredits/compose.yml` exist;
  `domains/bare_metal/` has no compose file.
- No file under `e2e-tests/` references bare metal or API credits. Every e2e scenario is
  a VM deal.
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
- **Does bare metal need teardown semantics distinct from VM's?** Whole-machine release
  differs from destroying a VM. Deferrable to the scenario, where the difference becomes
  concrete.
