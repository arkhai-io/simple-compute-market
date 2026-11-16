# Tasks — serve running rate deals

Each section names the decisions (`design.md`) and delta requirements (`specs/`) it
implements, the files it touches, and its verification at the levels
`docs/guidance/engineering/test-levels.md` defines. Every section bumps the version of
each package whose contents it changes and raises dependents' bounds
(`docs/guidance/repository/package-versions.md`, "A version changes when its contents
change"), refreshes the locks it affects with the repository's lock tooling
(`docs/guidance/repository/locks.md`), places the imports it adds at module level
(`docs/guidance/engineering/dependencies-python.md`, "Imports go at module level"), and
passes `scripts/change-workflow run pre-commit serve-running-rate-deals` before its
commit. Sections 10 and 11 need `drive-the-storefront-clock-in-lanes` archived and merged
into this branch first (D9).

## 1. Lifecycle contracts carry every field and the `ending` codes

Delivers the seller list's wire form: `DealSummary.ending`, a closed code list with each
code's text, and every model's fields carried at their defaults. Implements D7's wire
part; requirements "The seller half lists deals" and "Stop requests are distinct from
final stops" (`deal-lifecycle`). Touches `kit/deal-lifecycle-contracts`,
`kit/deal-lifecycle-client`.

- [ ] 1.1 In `kit/deal-lifecycle-contracts/src/market_deal_lifecycle_contracts/models.py`,
      add the closed `EndingCode` (`release_pending`, `payment_running`, `case_open`) with
      each code's text in one exported mapping, and `DealSummary.ending: list[EndingCode]`
      defaulting empty. Retire `ReleasedReadShape` from `PaymentEvent`, `AuthorityView`
      and `DealSummary`, so their dumps carry every field (D7). Take a version marking the
      change incompatible (0.2.0 → 0.3.0, pre-1.0, `package-versions.md`, "Before 1.0.0").
      Verify (unit, `tests/unit/test_models.py`): a once-only and a rate summary dump
      `parts`, `settles_through` and `ending` at their defaults; an unknown code is
      refused; every code has text.
- [ ] 1.2 Replace `tests/unit/test_released_reads.py` and `released_0_1_0.py` with a test
      that this release's models read once-only, rate, ending and ended reads and pages
      as the storefront dumps them (D7). Verify (unit): the new test passes, and no test
      validates against the 0.1.0 models.
- [ ] 1.3 `kit/deal-lifecycle-client`: raise its contracts bound, and expose each listed
      deal's `ending` codes with their text through `SellerLifecycleClient.list` and its
      sync variant, so a caller renders the text without interpreting codes (D7). Verify
      (unit, `kit/deal-lifecycle-client/tests/test_client.py`): a page with an ending
      deal yields its codes and their text.
- [ ] 1.4 Verification point: `kit/deal-lifecycle-contracts` and
      `kit/deal-lifecycle-client` suites (unit) pass; `make check-packaging` passes.
      End-to-end: no scenario asserts the new field yet; every scenario reading a seller
      lifecycle read through the typed client (`e2e_vm_recurring_purchase`,
      `e2e_bare_metal_recurring_purchase`, the `e2e_vm_dispute_*` scenarios) is pipeline
      evidence that the shipped client reads the new shapes.

## 2. End service asks the adapter for every deal, holds changed answers, and lists *ended* truly

Delivers delivery for rate deals and the seller list's meaning of *ended*. Implements D1,
D7's list part and D12's evidence; requirements "Delivery authorization delegates payment
interpretation", "The seller half lists deals" (`deal-lifecycle`), "Protected delivery
steps are authorized and admitted" (`compute-delivery`), "Payment settlement is retryable
and idempotent" (`settlement-servicing`). Touches `kit/deal-lifecycle`,
`kit/deal-servicing`, `domains/compute/delivery`, `e2e-tests`.

- [ ] 2.1 `kit/deal-servicing/src/market_deal_servicing/end.py`: remove `_unserviceable`
      and its call; in `_authorize_delivery`, when the phase's intent at this revision is
      already `done` and the new answer differs, return `pending` naming the changed
      answer and journal nothing (D1). Remove `DeliveryAuthorization.code`
      (`kit/deal-lifecycle/src/market_deal_lifecycle/delivery.py`), whose one value goes
      with the refusal. Update `journal.py`'s `_deadline_unobserved` docstring, which cites
      the removed requirement name. Verify (library integration,
      `kit/deal-servicing/tests/integration/`): replace `test_rate_refusal.py` with
      `test_changed_answer.py` — a rate deal's commit asks the adapter and an allow is
      journaled; `allow` then `pending` and `allow` then `refuse` at one revision return
      `pending` with the journal unchanged and nothing raised; a later identical `allow`
      proceeds; once a recorded end moves the revision, admission answers ended. Rewrite
      `test_deadline_barrier.py`'s refused-deal setups as undelivered rate deals, keeping
      its three scenarios.
- [ ] 2.2 `domains/compute/delivery/src/compute_delivery/path.py` and `outcome.py`: remove
      `RepairReason.RATE_SERVICING_UNAVAILABLE` and the code branch in `_authorized`;
      every refusal with no end due is `repair_required(no_accepted_deal)`. Verify
      (library integration, `domains/compute/delivery/tests/integration/test_drive_commit.py`):
      the refused-rate case is replaced by a changed-answer case that leaves the drive
      pending, and a rate deal commits.
- [ ] 2.3 `kit/deal-servicing/src/market_deal_servicing/seller.py`, `_list`: a deal with a
      selected end is `ended` only when `progress == "released"`, every part in the
      authority view has a `final_stop` or an `end_at` at or before now, and no case is
      open; otherwise `ending`, with `ending` naming each outstanding code (D7). Verify
      (library integration, `test_watch_and_seller.py`): a released rate deal whose part
      still runs is `ending` with `payment_running`; tearing down with an open case gives
      `release_pending` and `case_open`; all clear gives `ended` with no codes; a case
      filed after `ended` returns `ending`.
- [ ] 2.4 Verify D12 (library integration, `test_final_stop.py`): after the watch records a
      rate part's final stop, the servicing tables hold the stop and the selected end and
      no balance, funded amount or amount owed.
- [ ] 2.5 The two recurring-purchase scenarios
      (`e2e-tests/tests/e2e/roles/scenarios/vms/test_vm_recurring_purchase.py`,
      `.../bare_metal/test_bare_metal_recurring_purchase.py`, their stages in
      `e2e-tests/tests/e2e/roles/helpers/recurring_purchase_stages.py`) assert a refused
      commit. Until section 10 rewrites them on lane time, change only what the refusal's
      removal changes: the deal is delivered (activation, the payments double's rate
      `start` after it, availability), the buyer's own `end` stops it with the started
      period charged, and the seller's read shows the buyer's end; keep the waits they
      make today. Verify (unit, `e2e-tests/tests/unit/test_recurring_purchase_stages.py`)
      and by running both scenarios in their lanes.
- [ ] 2.6 Verification point: `kit/deal-lifecycle`, `kit/deal-servicing` and
      `domains/compute/delivery` suites (unit, library integration) pass; both storefronts'
      lifecycle suites (`domains/vms/storefront/tests/integration/test_lifecycle_*.py`,
      `domains/bare_metal/storefront/tests/integration/test_lifecycle_*.py`, application
      integration) pass. End-to-end: `e2e_vm_recurring_purchase`,
      `e2e_bare_metal_recurring_purchase`.

## 3. Every payment stop is classified

Delivers lawful classification of payment stops in both domains. Implements D2, D3;
requirement "Cause classification is owned by end service" (`deal-lifecycle`). Touches
`domains/compute` (`arkhai_compute`), `kit/deal-servicing`, both storefronts' watch
factories.

- [ ] 3.1 `domains/compute/src/arkhai_compute/end_classification.py`: add
      `classify_payment_stop(event, *, entitlements, term_end)` per D2's table, `terms`
      split by the Agreement's end (D3), returning a kind or `None` for pending. Verify
      (unit, `domains/compute/tests/test_end_classification.py`): each cause, an
      unentitled payer or payee stop pending, an unknown cause pending, `terms` one second
      before, at and after the end.
- [ ] 3.2 `kit/deal-servicing/src/market_deal_servicing/watch.py`, `_record_payment_stop`:
      when the stop's record exists with a pending classification and the classifier now
      classifies it, resolve it through `EndSession.resolve_correction` at the record's
      revision, lawful and with no filing (D2). Verify (library integration,
      `test_final_stop.py`): a pending stop recorded without a classifier is resolved on a
      later poll with one; the recorded end is unchanged; a resolved one is not resolved
      twice.
- [ ] 3.3 Pass `classify_payment_stop`, bound to `deal.entitlements` and the Agreement's
      start plus `duration_seconds`, through `DealWatch(classify_payment_end=...)` in
      `domains/vms/storefront/src/market_storefront/deal_lifecycle.py` (`watch`) and
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle.py`
      (`watch`). Verify (application integration,
      `test_lifecycle_ends.py` in each storefront): a delivered rate deal's buyer stop is
      classified an entitled stop, and a provisioning failure after it journals no
      `delivery_end` filing; a once-only deal's payment term end is classified the term
      end, and in bare metal a site withdrawal after it files nothing.
- [ ] 3.4 Verification point: `domains/compute` tests (unit), `kit/deal-servicing`
      (library integration), both storefronts' lifecycle suites (application
      integration) pass. End-to-end: `e2e_vm_payment_deal`, `e2e_bare_metal_payment_deal`
      and the two recurring purchases record classified ends; none asserts the
      classification.

## 4. Compositions build their payments stage and report deals they cannot service

Delivers D11 and D8; requirements "Each compute composition builds its payments seller
stage" and "A storefront reports deals its configuration cannot service"
(`market-composition`). Touches `domains/vms/storefront`, `domains/bare_metal/storefront`.

- [ ] 4.1 `domains/vms/storefront/src/market_storefront/settlement_composition.py`:
      `VmSettlementComposition` builds `arkhai_payments_stage` in `__post_init__` with
      `servicing_stage(..., rate_servicing=self.rate_servicing)`, as bare metal's does;
      `build_vm_settlement_composition` and `domains/vms/storefront/tests/recurring_world.py`
      stop building their own (D11). Verify (application integration,
      `domains/vms/storefront/tests/integration/test_servicing_composition.py`): a
      composition built from a configuration with the servicing fields has a stage over
      its declaration, with nothing supplied.
- [ ] 4.2 At startup each storefront lists its open deals whose mechanism has no adapter
      composed, logs them naming the missing section, and adds them to its readiness
      report; each such deal lists repair required naming the missing section (D8). Files:
      the startup paths of both storefronts (VM `server.py` startup, bare metal
      `runtime.py`), and `kit/deal-servicing/src/market_deal_servicing/seller.py`'s
      `_authority` reason. Verify (application integration, `test_degraded_startup.py`
      in VM and a new `test_unserviceable_startup.py` in bare metal): a storefront
      restarted with its payments section's servicing fields removed starts, reports the
      open once-only and rate deals, and lists them repair required.
- [ ] 4.3 Verify withdrawal (application integration, `test_servicing_composition.py` in
      each storefront): a running rate deal accepted under `returned` is still serviced
      after `returned` leaves the declaration, and no new option naming it publishes.
- [ ] 4.4 Verification point: both storefronts' suites pass. End-to-end: every lane starts
      both storefronts from their compositions; no scenario asserts the startup report.

## 5. What the buyer is shown

Delivers D13 and the D14 rewording; requirements "The buyer is shown the penalty's
collectible bound and why a funding stop is final" and "The buyer refuses seller ends that
keep the started period" (`buyer-orchestration`). Touches `kit/settlement-runtime`,
`kit/deal-lifecycle-buyer`, `domains/vms/buyer`, `domains/bare_metal/buyer`.

- [ ] 5.1 `kit/settlement-runtime/src/market_settlement_runtime/buyer_terms.py`: the
      on-demand premature-stop penalty row states the penalty is collectible only from the
      seller's earnings still held, nothing in the first period without a setup charge
      (D13). Verify (unit, the buyer-terms suite): the row's text for an on-demand option
      with and without a setup charge.
- [ ] 5.2 `kit/deal-lifecycle-buyer` (`lifecycle.py`, `watchdog.py`): take a payment-stop
      classifier slot; when a rate part's final stop classifies as exhaustion, the read
      composition and the watchdog's exit say the balance could not reserve the next
      period, a top-up cannot revive the deal, and a new deal is needed. Both buyers fill
      the slot with `arkhai_compute.classify_payment_stop` (D13). Verify (unit,
      `kit/deal-lifecycle-buyer/tests/unit/`; application integration, each buyer's
      `test_watchdog_rate_stop.py`): an exhaustion stop shows the message; a term-end stop
      does not.
- [ ] 5.3 D14's rewording is delta-only: confirm each buyer's existing waiver tests cover
      `--allow-charged-preemption` and `--allow-charged-term-end` as the reworded
      requirement states, adding a case where one is missing. Verify (unit): those suites
      pass.
- [ ] 5.4 Verification point: `kit/settlement-runtime`, `kit/deal-lifecycle-buyer` and both
      buyers' suites pass. End-to-end: the recurring purchases display the disclosure; no
      scenario asserts the new lines.

## 6. The kit's servicing step order, respondent port and page position

Delivers the kit helper and its kit-owned state. Implements D4's kit part and D6;
requirement "Each deal's servicing steps run in one kit-owned order" (`deal-lifecycle`).
Touches `kit/deal-servicing`.

- [ ] 6.1 Add `kit/deal-servicing/src/market_deal_servicing/servicing.py`: a helper that
      takes the seller half, end service, the domain's recovery steps and site-report
      classifier, a respondent port (`credential_available(authority)`,
      `dispute_adapter(binding)`), the signer and the clock, and runs one page: respondent
      discovery once per dispute authority, then per deal the authorities read (committed
      deals only), recovery steps, physical end, local reconciliation, site-report
      correction, filing dispatch, physical end again, each step isolated and logged with
      the domain, step and deal (D4). Local reconciliation admits a missed deadline and,
      once admission allows, records the term-end final request classified `terms`.
      Verify (library integration, new `test_servicing_order.py`): a failing physical end
      still runs reconciliation, correction and filing; the step order; the term end
      recorded at the Agreement's end and not while admission awaits an observation.
- [ ] 6.2 Respondent discovery in the helper: group the page's deals by dispute authority,
      leave out deals with none or with an unusable credential, own the one `resolve`
      (a differing Agreement digest raises into the respondent repairs), and build
      `RespondentPoller` per authority with its record derived from the authority alone
      (`respondent.py`) (D4). Verify (library integration, `test_respondent.py`): one
      discovery per authority whatever deal comes first, an Alkahest deal included; one
      authority's failure logged and the other's still run; an unusable credential leaves
      the deal out and its other steps run; a digest mismatch lands in the repairs.
- [ ] 6.3 Page position: add `servicing_page_position` (one row per loop) to
      `market_deal_servicing.schema` as its own schema set, created by an ordinary
      migration a storefront chain appends; the helper pages every registered deal and
      saves its position after each page (D6). Verify (library integration,
      `test_servicing_schema.py`): the set creates and the position survives a reopen.
- [ ] 6.4 Verification point: `kit/deal-servicing` suites (unit, library integration) pass.
      End-to-end: none until section 7 composes the helper.

## 7. Both storefront cycles run the kit's order

Delivers the unified cycles. Implements D4's domain part and D6's migrations;
requirement "Each deal's servicing steps run in one kit-owned order". Touches
`domains/vms/storefront`, `domains/bare_metal/storefront`.

- [ ] 7.1 VM: `VmDealLifecycle.cycle` (`deal_lifecycle.py`) calls the helper with its
      site-report recovery and classifier and its respondent port, dropping the cached
      pollers, the in-memory continuation and its own step order; VM thereby records its
      own term end. Append the servicing page-position migration to
      `domains/vms/storefront/src/market_storefront/utils/migrations.py`. Verify
      (application integration, `test_lifecycle_cycle.py`, `test_lifecycle_ends.py`): a
      physical failure does not skip filings; a once-only deal's term end is recorded and
      torn down; the page position survives a restart.
- [ ] 7.2 Bare metal: `BareMetalLifecycle.cycle` (`lifecycle.py`) calls the helper with
      `recover_site` and its classifier and its respondent port, dropping its own
      reconciliation's term-end record (now the kit's) and its delivery re-drive (section
      8 moves it). Append to `migrations.py` a migration that creates the page-position
      set and drops `bare_metal_lifecycle_cursor`. Verify (application integration,
      `test_lifecycle_dispatch.py`, `test_lifecycle_ends.py`): a failing `drive_physical`
      still dispatches the deal's filing in the same cycle; an uncommitted surrender gets
      its physical end; respondent discovery runs once per authority with an Alkahest
      deal first on the page.
- [ ] 7.3 Verify both migration chains (migration tests per
      `docs/guidance/repository/migration-chain-tests.md`): fresh and upgraded databases
      reach the same schema; bare metal's upgrade drops the old cursor table.
- [ ] 7.4 Verification point: both storefronts' suites pass. End-to-end:
      `e2e_vm_payment_deal`, the `e2e_vm_dispute_*` scenarios, `e2e_bare_metal_payment_deal`
      and the two recurring purchases step the servicing cycle.

## 8. One delivery re-drive routine

Delivers D5's shared re-drive; requirement "Unfinished deliveries are re-driven by one
routine" (`compute-delivery`). Touches `domains/compute/delivery`, both storefronts'
delivery ports.

- [ ] 8.1 `domains/compute/delivery/src/compute_delivery/recovery.py`:
      `recover_deliveries(path, domain, *, limit)` over a `DeliveryRecovery` port of
      `unfinished_deliveries`, `claim` (an async context answering whether it claimed) and
      `revalidate`, exported from the package (D5). Verify (library integration, new
      `tests/integration/test_recover_deliveries.py`): a claimed, revalidated deal is
      driven; an unclaimed or unrevalidated one is not.
- [ ] 8.2 VM fills the port with `list_incomplete_vm_deliveries`, its claim lease and its
      stage's `recover_evidence`, replacing `resume_incomplete_fulfillments_once`'s loop
      (`fulfillment_resume_runtime.py`); bare metal fills it with its lifecycle-row query,
      its lock and its settlement service's `verified_evidence`, replacing
      `BareMetalLifecycle.recover_delivery` (D5). Verify (application integration,
      `test_fulfillment_resume_runtime.py` in VM, `test_restart_recovery.py` in bare
      metal): a deal waiting for its start is claimed, revalidated and driven at the start;
      a deal another worker holds is skipped; a deal whose evidence fails is not driven.
- [ ] 8.3 Verification point: `domains/compute/delivery` and both storefronts' suites pass.
      End-to-end: every scenario that re-drives a delivery, among them
      `e2e_vm_payment_purchase`, `e2e_bare_metal_mock_deal` and the recurring purchases.

## 9. One loop layout, and restart recovery proven

Delivers D5's layout and D14's restart evidence; requirement "Both compute storefronts run
one loop layout" (`market-composition`). Touches both storefronts' loop registration,
their configuration, `e2e-tests`.

- [ ] 9.1 Register `deal-servicing`, `delivery-recovery`, `payment-reconciliation` and
      `settlement-servicing`, one job each, in
      `domains/vms/storefront/src/market_storefront/lifecycle_steps.py` and
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle_steps.py`;
      VM's `fulfillment-resume` splits, its `settlement-servicing` runs the worker alone
      (D5). Add interval keys for `deal-servicing` and `delivery-recovery`, each defaulting
      to the interval its job ran at before; released keys keep their meaning. Verify
      (application integration, `test_lifecycle_status.py` in VM and
      `test_app_composition.py` in bare metal): each reports the four loops; stepping
      `deal-servicing` runs one servicing cycle and re-drives no delivery; the new keys'
      defaults.
- [ ] 9.2 Rename the loops in the lane stages that pause and step them (the 11 files
      under `e2e-tests/tests/e2e/roles/` naming `fulfillment-resume`,
      `settlement-servicing` or `delivery-recovery`, and `held_loops.py` in bare metal's
      tests). Verify (unit, `e2e-tests/tests/unit/`): the stage modules pass; and by
      running the affected scenarios in their lanes.
- [ ] 9.3 Restart recovery (D14, application integration, `test_restart_recovery.py` in
      bare metal and a new `test_restart_recovery.py` in VM): restarting the composed
      storefront over the same database with a running rate deal, an ending deal and a
      pending seller stop resumes each — the running deal stays served, the ending deal
      ends when its stop is read, the pending stop takes effect at its instant.
- [ ] 9.4 Verification point: both storefronts' suites pass; `make check-packaging` passes.
      End-to-end: every scenario stepping a renamed loop, among them `e2e_vm_payment_deal`,
      the `e2e_vm_dispute_*` scenarios, `e2e_vm_payment_purchase`,
      `e2e_bare_metal_mock_deal`, `e2e_bare_metal_payment_deal`,
      `e2e_bare_metal_publication` and the two recurring purchases.

## 10. Rate deals qualified in both lanes on lane time

Delivers D9; requirements "A recurring purchase is delivered end to end in each compute
lane" and "Rate deals are qualified in both compute lanes on lane time"
(`test-compatibility`). Needs `drive-the-storefront-clock-in-lanes` landed. Touches
`e2e-tests`.

- [ ] 10.1 Rewrite both recurring purchases on the lane-time helper: set lane time to the
      Agreement's start, step `delivery-recovery`, assert activation, the rate `start` and
      availability; the buyer's `end`, step `deal-servicing`, assert the started period
      charged, the entitled stop recorded, the teardown and `ended` once released (D9).
      Verify: `e2e_vm_recurring_purchase`, `e2e_bare_metal_recurring_purchase` pass.
- [ ] 10.2 Add `e2e_vm_rate_servicing` and `e2e_bare_metal_rate_servicing`, one deal per
      row, shipped presets, default buyer, lane declaration `[charged, returned]`: funds
      running out (lane time past the funded boundary; exhaustion classified, teardown at
      the boundary, the buyer's message); spot preemption (`deals preempt`, lane time to
      the request plus the seller notice; the entitled stop, the unstarted period
      returned); the maximum term (lane time to the Agreement's end; `returned`, the term
      end classified, not exhaustion). Each labelled lane-double evidence. Verify: both
      markers pass in their lanes; `e2e-tests/tests/unit/` passes.
- [ ] 10.3 Verification point: both lanes' runs pass. End-to-end: the four markers above.

## 11. The buyer's watchdog against a delivered deal

Delivers D10; requirement "The buyer's watchdog is qualified against a delivered deal"
(`test-compatibility`). Needs `drive-the-storefront-clock-in-lanes` landed. Touches
`e2e-tests` and, if the mock fulfillment result cannot name an endpoint, the test-only
provisioning mock's result rules.

- [ ] 11.1 Harness fixtures: a TCP listener on the compose host that a stage opens and
      closes, the deal's mock fulfillment result disclosing it, and a fixture stopping and
      starting the storefront's Compose service, waiting for it to report healthy, from
      the lane's Compose arguments passed in the harness's environment by
      `e2e-tests/Makefile` (D10). Verify (unit, `e2e-tests/tests/unit/`): the fixtures'
      argument handling.
- [ ] 11.2 Add `e2e_vm_rate_watchdog` and `e2e_bare_metal_rate_watchdog`: `buy` with the
      watchdog from `available`; the storefront stopped and the listener closed for the
      threshold of probes yields one payer stop the double accepts; a killed command reads
      `unmonitored` once lane time passes its staleness bound; the resumed run reads
      `monitored`. Each labelled lane-double evidence. Verify: both markers pass in their
      lanes.
- [ ] 11.3 Verification point: both lanes' runs pass. End-to-end: the two markers above.

## 12. Closeout

Closes the change through `docs/guidance/workflow/closeout.md`'s parts in order, with this
repository's own parts (`openspec/README.md`, "This repository's closeout parts") after
campaign index currency.

- [ ] 12.1 Comment hygiene: run `make check-comment-hygiene`; a finding, or a comment this
      change added that names a change, a task or a review, returns the change to
      implementation.
- [ ] 12.2 Import placement: confirm every import this change added is at module level, or
      return the change to implementation.
- [ ] 12.3 Documentation compliance: re-check D1–D15 against
      `docs/guidance/workflow/openspec-documentation.md` and `openspec/README.md`,
      "Documentation placement", and that every permanent document written describes the
      current state.
- [ ] 12.4 Narrative compression: shorten completed tasks to final behaviour, evidence,
      deferred work and destinations, moving any rationale into `design.md` first.
- [ ] 12.5 Roadmap currency: in `docs/development/ROADMAP.md`'s Goal 8, remove this
      change's open-gap row; absorb into the current state that both storefronts deliver
      and service rate deals, classify payment stops, list *ended* and *ending*, share one
      servicing order and loop layout, and qualify the rate rows in both lanes as
      lane-double evidence; drop "VM/bare-metal respondent lifetime and term-end handling
      still differ"; name the edit in the design-promotion record.
- [ ] 12.6 Campaign index currency: update this change's row in
      `openspec/changes/README.md`; remove the unowned row "`VmSettlementComposition`
      builds no payments seller stage" (D11); run `make check-change-index`.
- [ ] 12.7 Packaging: run `make check-packaging`, then `make check-architecture-change
      CHANGE=serve-running-rate-deals`; resolve every failure or owned exception.
- [ ] 12.8 End-to-end pipeline: dispatch `make run-e2e` at the closeout's code and collect
      `make fetch-e2e-logs`; record the result and the scenarios exercising this change —
      `e2e_vm_recurring_purchase`, `e2e_bare_metal_recurring_purchase`,
      `e2e_vm_rate_servicing`, `e2e_bare_metal_rate_servicing`, `e2e_vm_rate_watchdog`,
      `e2e_bare_metal_rate_watchdog`, and the scenarios sections 7–9 name. A failed run
      returns the change to implementation; one that could not run is recorded as unrun
      with its cause.
- [ ] 12.9 Promotion: write the permanent documents below and complete the
      design-promotion record (`docs/guidance/workflow/changes.md`, "The design-promotion
      record"); the six `spec.md` files are written by the archive.
      - D1: `openspec/specs/deal-lifecycle/architecture.md`, "One end instant,
        transactional admission" (the refusal paragraph replaced by the changed-answer
        rule; the deadline barrier's "refused rate deal" wording) and "Current limits"
        (the "No storefront services a running rate deal" bullet);
        `openspec/specs/compute-delivery/architecture.md`, "Commit and hold adoption"
        (the `rate_servicing_unavailable` repair reason).
      - D2, D3: `deal-lifecycle/architecture.md`, "One end instant, transactional
        admission" (payment-stop classification and the `terms` split).
      - D4, D6: `deal-lifecycle/architecture.md`, "Package and counterpart boundaries"
        (the kit's servicing order, respondent port and page position) and "Current
        limits" (the respondent-lifetime and term-end bullet removed);
        `openspec/specs/vm-storefront-fulfillment/architecture.md`, "Evidence and delivery
        ownership" (its respondent-poller sentence);
        `openspec/specs/settlement-servicing/architecture.md`, "Current limits" (its
        respondent and term-end clause).
      - D5: `compute-delivery/architecture.md`, "Dispatch and recovery" and "Domain
        compositions" (the shared re-drive and its ports);
        `openspec/specs/market-composition/architecture.md`, "Storefront composition kit"
        (the four loops); `docs/development/ARCHITECTURE.md`, "Operator lifecycle
        controls" (the loop layout); `openspec/specs/storefront-publication/configuration.md`,
        "Durations are positive seconds" and "The settlement servicing interval" (the new
        interval keys).
      - D7: `deal-lifecycle/architecture.md`, "Seller notice and administrator
        interruption" (the routes' omission sentence removed) and "One end instant,
        transactional admission" (what *ended* means and the `ending` codes).
      - D8, D11: `market-composition/architecture.md`, "Settlement runtime composition".
      - D9, D10: `docs/development/TESTING.md`, "The canonical compute deal" (the
        recurring-purchase paragraph rewritten; the rate rows and the watchdog cases on
        lane time).
      - D12: the `settlement-servicing` spec, by the archive.
      - D13: `openspec/specs/buyer-orchestration/architecture.md`, "Compute terms before
        approval" (the penalty bound) and "The buyer's watchdog" (the funding-stop exit),
        beside the spec by the archive.
      - D14: the `buyer-orchestration` spec, by the archive;
        `openspec/specs/test-compatibility/architecture.md`, "Lifecycle contract evidence"
        (restart recovery's evidence).
      - D15: no permanent destination.
      - The owner's principles: `docs/guidance/workflow/changes.md`, "Defects found during
        a change" (a change taking on another change's work names the move in its proposal
        and that change's row Notes); `docs/guidance/repository/package-versions.md`,
        "Compatibility is owed to what a release has shipped" (a released client is not
        owed compatibility with a later storefront; the staged deprecation pattern stays
        available).
      Run `make check-spec-index CHANGE=serve-running-rate-deals`; no touched capability
      has an `index.md`, and `openspec/specs/README.md` needs no row.
- [ ] 12.10 Guidance placement: read the two guidance paragraphs promoted in 12.9 against
      the layer test, then run `make check-guidance`.
- [ ] 12.11 Documentation citations: run `make check-doc-citations
      CHANGE=serve-running-rate-deals` and resolve every match, then
      `scripts/change-workflow openspec validate serve-running-rate-deals --strict`.
- [ ] 12.12 Archival: `scripts/change-workflow openspec archive serve-running-rate-deals
      -y`, merging the deltas into `deal-lifecycle`, `compute-delivery`,
      `market-composition`, `settlement-servicing`, `buyer-orchestration` and
      `test-compatibility`; the index row then links the archive directory.
