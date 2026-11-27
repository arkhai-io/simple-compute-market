## Why

Both compute storefronts deliver and service rate deals, and on-demand and spot VM are
released in marketplace 0.4.0. Three gaps remain in how a storefront services a deal
whose end did not go cleanly, and most of the rate qualification rows beyond the
baseline have never run in a lane.

**A changed `delivery_end` claim never reaches the dispute authority.** When evidence of
an earlier seller failure arrives after a different `delivery_end` was filed, end
service selects the earlier end and journals a second filing
(`kit/deal-servicing/src/market_deal_servicing/journal.py`, `_filing`). The mediation
adapter answers any `delivery_end` whose claim differs from the one already filed
`repair required: delivery-end revision requires resolved prior rulings and effects`
(`kit/arkhai-mediation/src/market_arkhai_mediation/adapter.py`), and a rejected filing
is terminal, so the deal stays repair required and the buyer keeps the smaller remedy.
The dispute authority's contract allows a repeated case and nets its earlier ruling
itself; nothing sends one.

**A deal is listed `ended` while its own filing is outstanding.** The seller's list
calls a deal with a recorded end `ended` from its release, its payment parts and the
dispute authority's saved view (`kit/deal-servicing/src/market_deal_servicing/seller.py`,
`_outstanding`). It never reads the deal's own filings. A once-only deal ended as a
seller failure before its Agreement's start, with nothing dispatched, holds its filing
until that start, while a read of an Agreement nobody has filed on saves a view showing
no case: the deal is listed `ended`, and `ending` again once the filing lands. The
operator handbook's drain procedure waits for that `ended`.

**A physical end waits behind authority reads.** The kit's servicing cycle services a
page deal by deal, and reads each deal's authorities before its physical end
(`kit/deal-servicing/src/market_deal_servicing/servicing.py`, `ServicingCycle`). Each
authority client waits up to ten seconds by default. No step is skipped when an
authority is down, but a deal's teardown is attempted only after every earlier deal's
reads have timed out.

**The lanes.** Each compute lane runs the on-demand baseline ended by the buyer's stop,
funds running out, a spot preemption and the maximum term, and the buyer watchdog's
cases; the VM lane also rules a seller's filing and a buyer's contested case on rate
deals. No lane runs a spot seller's emergency filing, a buyer's end with the payment
authority unreachable, a deal that passes its delivery deadline, a seller that never
files, or a case over a rate part already paid out, and the bare-metal lane runs no
dispute row on a rate deal at all.

## What Changes

- This change holds the remaining rate qualification rows and three servicing fixes, as
  one change (design D1):
  - a revised `delivery_end` claim reaches the dispute authority;
  - the seller's list does not show a deal `ended` while a filing of its own is unsent
    or unanswered;
  - the order of work within a servicing page lets a physical end run without waiting
    for authority reads.

  How each fix is made is open in the design.
- The remaining rows of the rate matrix are qualified against the lane doubles on lane
  time. The design's scenario table names each row, what it needs, and what is still
  open about it.
- A storefront operator clears a deal ending on a pending release at the site, through
  the provisioning service's administrator API (D3). The operator handbook says how.

## Capabilities

### Modified Capabilities

- `deal-lifecycle`: a deal with a filing of its own outstanding is not listed `ended`.
  The requirements a revised `delivery_end` and the pass order change are named once
  the design settles them.
- `test-compatibility`: the remaining rate rows. Its delta is written once the design
  settles which lane runs which row and how a row holds a storefront back.

### New Capabilities

None.

## Non-Goals

- A funding timer, or any end of delivery calculated from what a deal has funded:
  `end-delivery-when-funding-runs-out` (D4).
- Operator recovery with the storefront stopped, its evidence export and its command
  envelope: `recover-deals-from-the-storefront-cli`, deferred (D2).
- A storefront command acknowledging a release the site has not proven (D3).
- The lane row that needs a delivery deadline the site enforces:
  `enforce-delivery-deadlines-at-the-site` (D5).
- Re-anchoring a running deal across a receipt key change. A key change is a drained
  cutover, and the gap is tabled in Goal 8's unowned work.
- Payment arithmetic, the mandate codec, authority policy and buyer acceptance policy.
- Live verification against hosted authorities:
  `qualify-per-period-bare-metal-and-setup-charges` adds the live twins of the rows
  here that reach an authority.

## Dependencies and Related Changes

- Nothing gates this change. It builds on the archived `serve-running-rate-deals`,
  `drive-the-storefront-clock-in-lanes` and `switch-on-hosted-per-period-vm`.
- `qualify-per-period-bare-metal-and-setup-charges` depends on it, for its design: that
  design names which of the rows landed here get a live verification twin, each sharing
  its row's assertion.
- `end-delivery-when-funding-runs-out` takes the funding timer and does not depend on
  this change. Both modify `deal-lifecycle`'s "Each deal's servicing steps run in one
  kit-owned order"; whichever lands second reverifies against the other.
- `enforce-delivery-deadlines-at-the-site` takes the late-anchor row.
- `recover-deals-from-the-storefront-cli` takes operator recovery.

## Impact

`kit/deal-servicing` (the servicing cycle, the seller's list), `kit/arkhai-mediation`
(a revised `delivery_end`), `kit/deal-lifecycle-contracts` and
`kit/deal-lifecycle-client` if the list names a new condition,
`tools/mediation-lane-double` if a row needs a second case on one Agreement, both lanes'
scenario stages, and `docs/operator-handbook.md`.

Compatibility is owed to `marketplace-v0.4.0`, the newest release tag, which carries
`kit/deal-servicing`, `kit/deal-lifecycle-contracts`, `kit/deal-lifecycle-client` and
`kit/arkhai-mediation` as they stand on the development branch.

- **Persistence.** No fix is known to need a record a 0.4.0 storefront did not write.
  If the design chooses persisted completion state, it is an additive migration
  appended to each storefront chain, and deals a 0.4.0 storefront ended read correctly
  with no backfill.
- **Wire.** The lifecycle wire models refuse an unknown field or code. A condition the
  seller's list newly names is therefore an incompatible step of
  `kit/deal-lifecycle-contracts`, shipped with the seller client that reads it; a
  released client is not owed reading a later storefront.
- **Configuration.** None.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `deal-lifecycle`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: no permanent destination — the scope of one change. What each fix does is promoted
  to `openspec/specs/deal-lifecycle/spec.md` and its companion, and the rows to
  `openspec/specs/test-compatibility/spec.md` and `docs/development/TESTING.md`, once
  the design settles them.
- D2: no permanent destination — a boundary between two changes.
- D3: `docs/operator-handbook.md`, "A deal ending on a pending release".
- D4: no permanent destination — a boundary between two changes;
  `openspec/specs/deal-lifecycle/architecture.md`, "Current limits", goes on saying a
  storefront runs no funding timer.
- D5: no permanent destination — a boundary between two changes.
