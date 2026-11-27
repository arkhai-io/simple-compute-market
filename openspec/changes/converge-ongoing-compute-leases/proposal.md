## Why

Both compute storefronts deliver and service rate deals, and on-demand and spot VM are
released in marketplace 0.4.0. Gaps remain in how a storefront services a deal whose
end did not go cleanly, and most of the rate qualification rows beyond the baseline
have never run in a lane.

**A changed `delivery_end` claim never reaches the dispute authority.** When evidence of
an earlier seller failure arrives after a different `delivery_end` was filed — the
seller's own, or the buyer's surrender case — end service selects the earlier end and
journals a filing for it (`kit/deal-servicing/src/market_deal_servicing/journal.py`,
`_filing`). The mediation adapter answers any `delivery_end` whose claim differs from
one already filed `repair required: delivery-end revision requires resolved prior
rulings and effects` (`kit/arkhai-mediation/src/market_arkhai_mediation/adapter.py`),
and a rejected filing is terminal, so the deal stays repair required and the buyer
keeps the smaller remedy. The dispute authority's contract allows a repeated case, but
rules only one `delivery_end` mechanically per Agreement and does not net the penalty
or once parts across cases.

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
authority client waits up to ten seconds by default, so with the authorities down a
deal's teardown is attempted only after every earlier deal's reads have timed out.

**The site's sends to a storefront are not steps a lane takes.** The provisioning
service delivers its lease-end report and capacity-released callback inline after a
command or a watchdog cycle, whether or not its event delivery is paused, and no lane
holds its event delivery timer or its capacity-reservation watchdog
(`provisioning/compute/src/compute_provisioning/lease_lifecycle.py`). A lane cannot
hold a site's report back from a storefront, so the rows written for a storefront that
has not heard from its site cannot run in production's order.

**The lanes.** Each compute lane runs the on-demand baseline ended by the buyer's stop,
funds running out, a spot preemption and the maximum term, and the buyer watchdog's
cases; the VM lane also rules a seller's filing and a buyer's contested case on rate
deals. No lane runs a spot seller's emergency filing, a buyer's end with the payment
authority unreachable, a deal that passes its delivery deadline, a seller that never
files, a revision of a filed end, or a case over a rate part already paid out, and the
bare-metal lane runs no dispute row on a rate deal at all.

## What Changes

- One change holds the remaining rate qualification rows and the fixes they need
  (design D1):
  - the storefront files a revised `delivery_end` at once, and the dispute authority
    rules a payee's earlier-end revision mechanically, net of earlier cases, identified
    from its own record; this change records what the authority owes (R1–R4, D6);
  - the seller's list names an unanswered filing of the deal's own with a fifth ending
    code, `filing_unanswered`, and never shows such a deal `ended` (D11);
  - each servicing cycle first drives the physical end of every deal on its page, so an
    end already recorded waits behind no read (D7);
  - the provisioning service's sends to a storefront become steps a lane takes: inline
    delivery respects the event-delivery pause, the capacity-reservation watchdog gains
    a pause and a step, and every compute lane holds both (D8).
- The remaining rows of the rate matrix are qualified against the lane doubles on lane
  time, each once in the VM lane and in the bare-metal lane where bare-metal code is on
  its path, with the bare-metal twins of the VM lane's two rate dispute rows (D9); the
  setup rows run on a lane-only setup declaration (D10).
- The revision's live verification scenario is written here, sharing row 3's assertion;
  a coordinator runs it against a dispute authority meeting R1–R4 and writes the
  evidence into this change, and closeout waits for it (D14).
- The rule that every delivery between services is a step the harness takes is written
  into the testing guidance (D8).
- The operator handbook's "A deal ending on a pending release", already landed (D3), and
  its drain procedure are kept current with the new code; it gains how to raise a deal
  a 0.4.0 storefront left repair required on a revision, and what pausing event
  delivery now holds.

## Capabilities

### Modified Capabilities

- `deal-lifecycle`: the servicing order's leading physical pass; the seller's list's
  fifth ending code; revised `delivery_end` filings sent at once, the authority
  identifying and netting them.
- `physical-provisioning`: the site's sends to a storefront are held while event
  delivery is paused, and the capacity-reservation watchdog is pausable and steppable.
- `test-compatibility`: the module holds gain event delivery and the
  capacity-reservation watchdog; the remaining rate rows; the revision's live
  verification.

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
- The other ungated sends between services the lanes meet — the VM settle and payments
  drive tasks, the introduction mail, loops unheld before a module's holds, the chain
  probe's thread, sends a route starts and only logs, the mediation double's ungated
  rulings. No change owns them; each change that meets one fixes it under the written
  rule (D8).
- Re-anchoring a running deal across a receipt key change. A key change is a drained
  cutover, and the gap is tabled in Goal 8's unowned work.
- Payment arithmetic, the mandate codec, authority policy and buyer acceptance policy.
  The dispute authority's own implementation of R1–R4 is outside this repository.
- Live verification of the rows other than the revision:
  `qualify-per-period-bare-metal-and-setup-charges` adds those live twins.

## Dependencies and Related Changes

- Nothing gates this change. It builds on the archived `serve-running-rate-deals`,
  `drive-the-storefront-clock-in-lanes` and `switch-on-hosted-per-period-vm`.
- Its closeout waits for the coordinator's live verification evidence, which needs a
  dispute authority meeting R1–R4 (D14). That is a capability the dispute authority
  owes, not another change.
- `qualify-per-period-bare-metal-and-setup-charges` depends on it, for its design: that
  design names which of the rows landed here get a live verification twin, each sharing
  its row's assertion. The revision's twin moved here (D14), and that change records
  D10's lane-only setup declaration.
- `end-delivery-when-funding-runs-out` takes the funding timer and does not depend on
  this change. Both modify `deal-lifecycle`'s "Each deal's servicing steps run in one
  kit-owned order"; whichever lands second reverifies against the other.
- `enforce-delivery-deadlines-at-the-site` takes the late-anchor row.
- `recover-deals-from-the-storefront-cli` takes operator recovery.

## Impact

`kit/deal-servicing` (the servicing cycle, the seller's list), `kit/deal-lifecycle-contracts`
and `kit/deal-lifecycle-client` (the fifth ending code), `kit/arkhai-mediation` (the
revision path and a `describe` client method), `provisioning/compute` (service,
contracts and client: paused delivery and the capacity-reservation watchdog's
controls), both compute lanes' holds and scenario stages and their lane configuration,
the VM live verification scenarios, `docs/guidance/engineering/system-tests.md`,
`docs/guidance/repository/deterministic-tests.md`, `docs/operator-handbook.md`, and
`openspec/changes/qualify-per-period-bare-metal-and-setup-charges/design.md`.

Compatibility is owed to `marketplace-v0.4.0`, the newest release tag, which carries
`kit/deal-servicing`, `kit/deal-lifecycle-contracts`, `kit/deal-lifecycle-client`,
`kit/arkhai-mediation` and the provisioning service as they stand on the development
branch, but for lockfiles.

- **Persistence.** None.
- **Wire.** The lifecycle wire models refuse an unknown code, so `filing_unanswered` is
  an incompatible step of `kit/deal-lifecycle-contracts`, shipped with the seller client
  that reads it; until 1.0 a released client is not owed reading a later storefront.
  The mediation filing is unchanged. The provisioning service's new routes are
  additive.
- **Behaviour.** Pausing the provisioning service's event delivery now also holds the
  inline delivery of commands and watchdog cycles; production does not pause it.
  Deals a 0.4.0 storefront left repair required on a revision stay so.
- **Configuration.** None.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `deal-lifecycle`, `physical-provisioning`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: no permanent destination — the scope of one change.
- D2: no permanent destination — a boundary between two changes.
- D3: `docs/operator-handbook.md`, "A deal ending on a pending release", already landed;
  kept current with D11's code.
- D4: no permanent destination — a boundary between two changes;
  `openspec/specs/deal-lifecycle/architecture.md`, "Current limits", goes on saying a
  storefront runs no funding timer.
- D5: no permanent destination — a boundary between two changes.
- D6: `openspec/specs/deal-lifecycle/spec.md`, the filing-identity and revised-case
  requirements; R1–R4 in `openspec/specs/deal-lifecycle/architecture.md`, "External
  authorities", and the roadmap's Goal 8 row; the line on 0.4.0-refused revisions in
  `docs/operator-handbook.md`.
- D7: `openspec/specs/deal-lifecycle/spec.md`, "Each deal's servicing steps run in one
  kit-owned order".
- D8: `openspec/specs/physical-provisioning/spec.md` and its companion;
  `openspec/specs/test-compatibility/spec.md`, the module holds; the rule in
  `docs/guidance/engineering/system-tests.md` and, with the holds,
  `docs/guidance/repository/deterministic-tests.md`; the event-delivery pause in
  `docs/operator-handbook.md`.
- D9: `openspec/specs/test-compatibility/spec.md` and `docs/development/TESTING.md`.
- D10: `openspec/specs/test-compatibility/spec.md` and `docs/development/TESTING.md`.
- D11: `openspec/specs/deal-lifecycle/spec.md`, "The seller half lists deals";
  `docs/operator-handbook.md`'s drain procedure and pending-release section.
- D12: no permanent destination of its own — each consequence is promoted with the
  decision it follows.
- D13: no permanent destination — the change's implementation cadence.
- D14: `openspec/specs/test-compatibility/spec.md`, the live verification requirement,
  and `docs/development/TESTING.md`.
