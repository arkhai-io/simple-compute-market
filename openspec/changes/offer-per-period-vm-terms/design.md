# Design: offer-per-period-vm-terms

## Context

Goal 8's MVP is a set of changes sequenced before the rest of the goal: a buyer
takes an on-demand or spot VM paid per hour from a prepaid Arkhai payments
balance; Arkhai operators handle disputes by hand through the dispute account's
stop and the payments service's reversal; VM only. It does not complete Goal 8.

The MVP set is this change, `derive-rate-parts-in-the-payments-kit` and
`drive-the-storefront-clock-in-lanes` in parallel, then
`serve-running-rate-deals-on-vm`, then `switch-on-hosted-per-period-vm`.

What exists that this change builds on:

- The option is already `{price, settlement, lifecycle}`, with `lifecycle` part of
  the option ID (`core/src/market_core/schemas.py`). The lifecycle codec already
  carries `early_termination`, entitlements with `notice_seconds` and
  `settles_through`, `premature_stop_penalty` and `delivery_deadline_seconds`
  (`kit/deal-lifecycle/src/market_deal_lifecycle/terms.py`).
- The registry stores settlement options whole and already filters the lifecycle
  terms with every predicate correlated to one option
  (`core/registry/src/core_registry/filter-spec.yaml`, `api/filter_eval.py`).
- The VM storefront already falls back to the listing's `max_duration_seconds`
  when no duration is requested (`domains/vms/storefront/src/market_storefront/negotiation_runtime.py`);
  the VM buyer's `buy` still requires `--duration-hours`
  (`domains/vms/buyer/src/arkhai_vms_buyer/buy_cli.py`).
- No buyer acceptance policy over `settles_through` or the penalty is coded; the
  refusals described in `negotiate-open-ended-compute-terms` are design only, so
  this change chooses the MVP defaults without rework.

## Decisions

### D1 — Fixed shape and flat price; the amount is an absolute per-period price

Per-period options are offered only on listings whose shape is fixed and whose
price is flat. The Agreement's amount is the per-period price in base units, and
a buyer can check it from the option alone. The accessor ships with only this
reading.

`negotiation-driven-capacity-resize`, which changes what `Agreement.amount` means
on shape-priced listings, owns every reader of that field: it adds the multiplier
reading and a discriminator (whether the accepted option binds a rate structure)
to whichever accessor exists when it lands, and guarantees an Agreement made under
the absolute reading stays absolute — the payment mandate hashes it.

Rejected: waiting for `negotiation-driven-capacity-resize`'s multiplier and its
pricing carrier, which is in implementation with its carrier decision open and
gates nothing an on-demand or spot buyer needs.

### D2 — Every started period is charged, and the default buyer accepts it

On-demand and spot settle through the started period on every entitlement and at
the term end. The default buyer accepts that and does not require a premature-stop
penalty. A spot preemption therefore charges the whole started period; with an
hourly period that is at most one hour.

Rejected: the full product's treatment of a seller's preemption, which returns the
unstarted remainder and needs `returned` executed by the hosted payments service.
The full product's default buyer refuses charged treatment on a seller's preemption
and at the term end and accepts it on its own stop
(`negotiate-open-ended-compute-terms`); an upgraded default buyer therefore refuses
MVP-era on-demand and spot offers until their sellers republish under the later
presets.

### D3 — VM only

Bare metal has no qualified real host, its term-end handling differs from VM's,
and its preset needs a setup fee whose return on non-delivery is a dispute
remedy. Bare metal follows the MVP.

### D4 — The seller-configured delivery deadline is a stopgap the MVP keeps

The option's deadline is the value the seller configures in its payments clause,
and the storefront's servicing journal classifies a missed deadline as
non-delivery (`kit/deal-servicing/src/market_deal_servicing/journal.py`). The
design the foundation settled is different: the deadline is the Resource Pool's
`delivery_deadline_seconds` tag, published as the option's term, carried with the
site commit and enforced by the site, which refuses a commit beyond the pool's
current value. The payments-clause value arose because that tag did not yet exist,
and it puts a lifecycle key in a payments mechanism's model, against
`deal-lifecycle`'s rule that no mechanism's model owns one.

The MVP keeps the stopgap and states it honestly: the permanent `deal-lifecycle`
requirements "The delivery deadline is the site's availability term" and
"Lifecycle terms are part of the selected option" are amended to describe the
seller-configured, storefront-enforced value as current behaviour, and the
mechanism-owned key as a known divergence. `renewable-compute-lease-deadlines`
replaces it with the pool tag and re-amends both requirements.

Rejected: making the seller-configured value permanent, which would set the
buyer's promise apart from how long the provider takes and keep the divergence.

### D5 — Discovery by recipe over existing filters

No registry change. One local clause field, `arkhai_payments.period`, tells a
per-period option from a once-only one; documented recipes combine it with the
registry's existing lifecycle and asking-rate filters.

### D6 — The servicing declaration lists qualified treatments

The VM composition declares the started-period treatments it has qualified.
Publication offers, and acceptance admits, only options whose every treatment is
declared; `derive-rate-parts-in-the-payments-kit` derives only declared
treatments. The MVP's list is `[charged]`. Each later qualification extends a
composition's list, so VM and bare metal advance independently and no deal is
ever offered on a treatment its composition has not qualified.

The permanent `deal-lifecycle` requirements "Started-period treatment is a
committed payment term" and "Term ends carry their own partial-period treatment"
are amended accordingly: a treatment is refused when its composition has not
declared it, not by what the vendored contract can express (the contract
expresses every treatment); the "interim" wording and scenario go; compute presets
use a declared term-end treatment, and `spot-deals-through-arkhai-payments` moves
the shipped presets to `last_boundary` once `returned` is declared.

Rejected: an on/off flag, which cannot express a composition qualified for some
treatments and not others.

### D7 — No per-period option without a maximum duration

The VM negotiation runtime resolves a horizon as the requested duration, else the
listing's `max_duration_seconds`, else one hour
(`domains/vms/storefront/src/market_storefront/negotiation_runtime.py`). A
per-period option on a listing with no maximum duration would bind a one-hour
Agreement nobody chose, so publication omits per-period options from such a
listing.

## Open Questions

- Which period and reserve ahead the presets ship (an hour and one period are the
  working assumption), settled jointly with `derive-rate-parts-in-the-payments-kit`'s
  first task.
- Whether `max_duration_seconds` alone is enough of a seller bound for the MVP, or
  the seller also needs a calendar end date before `available_until_utc` lands.
- Whether the spot notice is a seller setting or a fixed MVP value.
