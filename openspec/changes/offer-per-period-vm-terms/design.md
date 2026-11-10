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

Rejected: waiting for `negotiation-driven-capacity-resize`'s multiplier and its
pricing carrier, which is in implementation with its carrier decision open and
gates nothing an on-demand or spot buyer needs.

### D2 — Every started period is charged, and the default buyer accepts it

On-demand and spot settle through the started period on every entitlement and at
the term end. The default buyer accepts that and does not require a premature-stop
penalty. A spot preemption therefore charges the whole started period; with an
hourly period that is at most one hour.

Rejected: the full product's default of returning the unstarted remainder, which
needs `returned` treatment executed by the hosted payments service and the
mediation self-penalty — the automated remedies the MVP leaves to operators.

### D3 — VM only

Bare metal has no qualified real host, its term-end handling differs from VM's,
and its preset needs a setup fee whose return on non-delivery is a dispute
remedy. Bare metal follows the MVP.

### D4 — The delivery deadline stays seller-configured and storefront-enforced

The option's deadline is the seller's configured value, and the storefront's
servicing journal classifies a missed deadline as non-delivery
(`kit/deal-servicing/src/market_deal_servicing/journal.py`). The permanent
`deal-lifecycle` requirements "The delivery deadline is the site's availability
term" and "Lifecycle terms are part of the selected option" are amended to state
that, with the site safeguard owned by `renewable-compute-lease-deadlines`.

### D5 — Discovery by recipe over existing filters

No registry change. One local clause field, `arkhai_payments.period`, tells a
per-period option from a once-only one; documented recipes combine it with the
registry's existing lifecycle and asking-rate filters.

## Open Questions

- Which period and reserve ahead the presets ship (an hour and one period are the
  working assumption), settled jointly with `derive-rate-parts-in-the-payments-kit`'s
  first task.
- Whether `max_duration_seconds` alone is enough of a seller bound for the MVP, or
  the seller also needs a calendar end date before `available_until_utc` lands.
- Whether the spot notice is a seller setting or a fixed MVP value.
