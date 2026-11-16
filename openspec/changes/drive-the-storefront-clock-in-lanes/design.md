# Design: drive-the-storefront-clock-in-lanes

## Context

One of Goal 8's three MVP changes: this one and `serve-running-rate-deals` in
parallel, then `switch-on-hosted-per-period-vm`.

The repository prefers not to build test mechanisms into production code. This
change is the exception the lane needs: the e2e lanes run the storefronts' real
containers, which cannot be patched, and a wait on wall time for a funding
boundary is a wait on the system settling. The alternative of widening the
scenario discipline to admit waits for instants an authority's records fix was
rejected for that reason.

What exists:

- The VM storefront's deal lifecycle already takes one injectable clock and
  passes it to the end service, the payment watch and the delivery path
  (`domains/vms/storefront/src/market_storefront/deal_lifecycle.py`;
  `kit/deal-servicing/src/market_deal_servicing/watch.py`).
- The bare-metal storefront's lifecycle takes its clock from its runtime's
  `lifecycle_clock` and passes it to the end service, the watch and site-report
  ingestion (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py`,
  `lifecycle.py`).
- Other storefront modules read wall time directly, among them publication,
  negotiation, payment settlement and the admin controllers.
- The doubles' perceived clock is wall time plus an offset moved by
  `POST /test/clock/advance` and reset by `POST /test/clock/reset`, in
  `tools/lane-double-controls`, a test-only distribution kept out of the release
  wheelhouse.

## Decisions

### D1 — A configured clock source, refused in production

Each compute storefront's composition builds its clock from configuration. Wall
time is the default and the only value a production composition accepts. The
perceived clock's routes are mounted only when it is enabled.

### D2 — The lane moves every perceived clock together

One fixture per lane advances its storefront's and both doubles' clocks by the
same amount and resets them together, so a stop the payments double records at an
advanced instant is not in the storefront's future.

### D3 — One mechanism, composed by both storefronts

The clock source and its routes are one mechanism both storefronts compose, not a
copy per domain. `serve-running-rate-deals` qualifies rate deals in both lanes,
including a funds-exhausted row in each, so both storefronts compose it here; this
takes `converge-ongoing-compute-leases`' task 4.1a.

## Open Questions

- **The site's clock.** Teardown at a stop's effective time reaches the site,
  which may judge a truncation instant or a lease end against its own wall clock.
  If it does, the funds-exhausted rows need the site's clock driven too, or a
  demonstration that the site never judges those instants itself.
- **Reach.** Whether the override covers only each lifecycle's clock, which makes
  the servicing decisions the MVP rows exercise, or every storefront module that
  reads time.
- **Where the perceived clock lives.** In a production kit both storefronts
  already depend on, or by promoting the clock module of `tools/lane-double-controls`
  to a production distribution the doubles then share.
- **Where the bare-metal routes are specified.** `vm-storefront-fulfillment` holds
  the VM operator API; the bare-metal storefront's operator routes have no
  equivalent specification.
- **Monotonicity.** Whether reset may move a storefront's clock backwards while
  deals are journaled at advanced instants, or the fixture must instead discard
  the module's deals.
