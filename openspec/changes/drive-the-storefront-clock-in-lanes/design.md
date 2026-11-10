# Design: drive-the-storefront-clock-in-lanes

## Context

One of Goal 8's MVP changes; `offer-per-period-vm-terms`'s design states the set.

The repository prefers not to build test mechanisms into production code. This
change is the exception the lane needs: the e2e lane runs the storefront's real
container, which cannot be patched, and a wait on wall time for a funding
boundary is a wait on the system settling. The alternative of widening
`TESTING.md` to admit waits for instants an authority's records fix was rejected
for that reason.

What exists:

- The VM storefront's deal lifecycle already takes one injectable clock and
  passes it to the end service, the payment watch and the delivery path
  (`domains/vms/storefront/src/market_storefront/deal_lifecycle.py`;
  `kit/deal-servicing/src/market_deal_servicing/watch.py`).
- Other storefront modules read wall time directly, among them publication,
  negotiation, payment settlement and the admin controller.
- The doubles' perceived clock is wall time plus an offset moved by
  `POST /test/clock/advance` and reset by `POST /test/clock/reset`, in
  `tools/lane-double-controls`, a test-only distribution kept out of the release
  wheelhouse.

## Decisions

### D1 — A configured clock source, refused in production

The storefront's composition builds its clock from configuration. Wall time is
the default and the only value a production composition accepts. The perceived
clock's routes are mounted only when it is enabled.

### D2 — The lane moves every perceived clock together

One fixture advances the storefront's and both doubles' clocks by the same amount
and resets them together, so a stop the payments double records at an advanced
instant is not in the storefront's future.

## Open Questions

- **The site's clock.** Teardown at a stop's effective time reaches the site,
  which may judge a truncation instant or a lease end against its own wall clock.
  If it does, the funds-exhausted row needs the site's clock driven too, or a
  demonstration that the site never judges those instants itself.
- **Reach.** Whether the override covers only the deal lifecycle's clock, which
  makes the servicing decisions the MVP rows exercise, or every storefront module
  that reads time.
- **Where the perceived clock lives.** In a production kit the storefront already
  depends on, or by promoting the clock module of `tools/lane-double-controls` to a
  production distribution the doubles then share.
- **Monotonicity.** Whether reset may move the storefront's clock backwards while
  deals are journaled at advanced instants, or the fixture must instead discard
  the module's deals.
