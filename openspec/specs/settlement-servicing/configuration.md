---
tags: [repository, configuration]
---

# Seller servicing budget configuration

What a seller's servicing loop composition is given to diagnose its budget, and what
that diagnosis does not configure.

## Seller servicing budget diagnostics

`kit/deal-servicing` exposes `ServicingBudget` and `SellerBudgetDiagnostics` for
seller-side loop composition. All polling/watchdog/teardown inputs are finite,
nonnegative seconds. The diagnostic compares reserve-ahead and priced payer
notice, when supplied, with polling + max(configured watchdog, observed cycle)
\+ teardown. A shortfall logs a recommendation and possible unpaid-delivery
exposure; it neither stops a loop nor changes an accepted term. The wrapper
measures the injected step, not a second timer or a buyer watchdog.

These are library composition inputs, not `[Settlement]` configuration keys
or a buyer guarantee. Current compute role roots do not expose a budget table.
Use [the deterministic budget example](../../../kit/deal-servicing/examples/budget_first_use.py)
for a runnable warning-and-continue check. During storefront downtime, physical
service can continue until the lease maximum. A rate buyer's protection requires
its own authority stop/case, not a seller-advertised processing budget. See
[lifecycle authority limits](../deal-lifecycle/architecture.md#current-limits).
