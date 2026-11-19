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
into this branch first (D9); it is. Sections 9A and 9B, added when the change returned to
design from section 10's first lane run, deliver the tooling sections 10 and 11 run on.

## 1. Lifecycle contracts carry every field and the `ending` codes

Delivers the seller list's wire form: `DealSummary.ending`, a closed code list with each
code's text, and every model's fields carried at their defaults. Implements D7's wire
part; requirements "The seller half lists deals" and "Stop requests are distinct from
final stops" (`deal-lifecycle`). Touches `kit/deal-lifecycle-contracts`,
`kit/deal-lifecycle-client`.

- [x] 1.1 In `kit/deal-lifecycle-contracts/src/market_deal_lifecycle_contracts/models.py`,
      add the closed `EndingCode` (`release_pending`, `payment_running`, `case_open`) with
      each code's text in one exported mapping, and `DealSummary.ending: list[EndingCode]`
      defaulting empty. Retire `ReleasedReadShape` from `PaymentEvent`, `AuthorityView`
      and `DealSummary`, so their dumps carry every field (D7). Take a version marking the
      change incompatible (0.2.0 → 0.3.0, pre-1.0, `package-versions.md`, "Before 1.0.0").
      Verify (unit, `tests/unit/test_models.py`): a once-only and a rate summary dump
      `parts`, `settles_through` and `ending` at their defaults; an unknown code is
      refused; every code has text.
      Done: `EndingCode` and `ENDING_TEXT` (a read-only mapping) in `models.py`;
      `ReleasedReadShape` is gone, so `PaymentEvent`, `AuthorityView` and `DealSummary`
      dump every field; contracts 0.3.0 (`case_unobserved` added by section 2's 44 F1
      fix). Beyond the plan, a `DealSummary` validator lists each code once and only
      while the state is `ending`. Unit (`test_models.py`, 54 passed): once-only and
      rate summaries and an `AuthorityView` dump every field at its default; an unknown,
      misplaced or repeated code is refused; every code has text. Stored rows written
      before this release read back at their defaults (`design.md`, "Implementation
      findings").
- [x] 1.2 Replace `tests/unit/test_released_reads.py` and `released_0_1_0.py` with a test
      that this release's models read once-only, rate, ending and ended reads and pages
      as the storefront dumps them (D7). Verify (unit): the new test passes, and no test
      validates against the 0.1.0 models.
      Done: `tests/unit/test_shipped_reads.py` serializes a once-only, rate, ending and
      ended read and page as a storefront's lifecycle route does and validates each back
      as the seller client does (unit, passed). A round trip would pass at the base too;
      that every field is dumped is `test_models.py`'s evidence. Both 0.1.0 files are
      removed.
- [x] 1.3 `kit/deal-lifecycle-client`: raise its contracts bound, and expose each listed
      deal's `ending` codes with their text through `SellerLifecycleClient.list` and its
      sync variant, so a caller renders the text without interpreting codes (D7). Verify
      (unit, `kit/deal-lifecycle-client/tests/test_client.py`): a page with an ending
      deal yields its codes and their text.
      Done, differing from the plan in where the text is joined: `DealSummary` carries an
      unserialized `ending_reasons` property (each code with its `ENDING_TEXT`), so every
      reader of the contracts renders the same words and the client needs no wrapper
      type. Client 0.2.0, contracts `>=0.3.0`; its README names `ending` and
      `ending_reasons`. Unit (`test_client.py`, 3 passed): both list variants send the
      list route and return a page whose ending deal yields its codes and their text.
- [x] 1.4 Verification point: `kit/deal-lifecycle-contracts` and
      `kit/deal-lifecycle-client` suites (unit) pass; `make check-packaging` passes.
      End-to-end: no scenario asserts the new field yet; every scenario reading a seller
      lifecycle read through the typed client (`e2e_vm_recurring_purchase`,
      `e2e_bare_metal_recurring_purchase`, the `e2e_vm_dispute_*` scenarios) is pipeline
      evidence that the shipped client reads the new shapes.
      Done: both suites pass (unit); `make check-packaging` and `make test` pass in
      `scripts/change-workflow run pre-commit`, after `make lock`. End-to-end corrected:
      no scenario asserts `ending` or calls the seller client's `read` or `list`, so the
      list's new shape has no pipeline evidence; the VM scenarios (through the buyer
      `LifecycleClient`) and the bare-metal one (validating `LifecycleRead`) are
      evidence that this release's models read the `LifecycleRead` its storefronts
      serve.

## 2. End service asks the adapter for every deal, holds changed answers, and lists *ended* truly

Replanned when implementation found both storefronts' recurring test worlds unable to
deliver a rate deal: this section is the kit and compute-delivery slice, tasks 2.1–2.4;
the storefronts' rate-delivery evidence is section 2A, and 2.5's lane scenarios are
section 2B.

Delivers delivery for rate deals and the seller list's meaning of *ended*. Implements D1,
D7's list part and D12's evidence; requirements "Delivery authorization delegates payment
interpretation", "The seller half lists deals" (`deal-lifecycle`), "Protected delivery
steps are authorized and admitted" (`compute-delivery`), "Payment settlement is retryable
and idempotent" (`settlement-servicing`). Touches `kit/deal-lifecycle`,
`kit/deal-servicing`, `domains/compute/delivery`.

- [x] 2.1 `kit/deal-servicing/src/market_deal_servicing/end.py`: remove `_unserviceable`
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
      Done: a phase whose authorization at this revision is `done` and whose new answer
      differs by status returns `pending` naming both answers, journaling nothing;
      answers compare by status alone, and an end due by now at the same revision is
      admission's own `refuse`, unjournaled (`design.md`, "Implementation findings").
      `DeliveryAuthorization.code` and `RefusalCode` are removed with
      `test_delivery_authorization.py`, which tested only the code's omission. Library
      integration (`test_changed_answer.py`, replacing `test_rate_refusal.py`): the
      planned cases, plus an end due at the same revision and a once-only deal's
      unchanged answer; `test_deadline_barrier.py` keeps its three scenarios on an
      undelivered rate deal. `kit/deal-lifecycle` 0.5.0 (82 passed), `kit/deal-servicing`
      0.4.0, contracts `>=0.3.0` (114 passed).
- [x] 2.2 `domains/compute/delivery/src/compute_delivery/path.py` and `outcome.py`: remove
      `RepairReason.RATE_SERVICING_UNAVAILABLE` and the code branch in `_authorized`;
      every refusal with no end due is `repair_required(no_accepted_deal)`. Verify
      (library integration, `domains/compute/delivery/tests/integration/test_drive_delivery.py`,
      where the refused-rate cases are — corrected from `test_drive_commit.py`): the
      refused-rate cases are replaced by a rate deal that commits and is delivered, a
      changed answer while it waits for its start leaving the drive pending, and an
      undelivered rate deal past its deadline.
      Done as planned. Library integration (`test_drive_delivery.py`, 130 passed with
      the suite): the three planned cases, the deadline case waiting for a payment
      observation, and a deal first driven past its deadline pending with nothing begun.
      `domains/compute/delivery` 0.2.0.
- [x] 2.3 `kit/deal-servicing/src/market_deal_servicing/seller.py`, `_list`: a deal with a
      selected end is `ended` only when `progress == "released"`, every part in the
      authority view has a `final_stop` or an `end_at` at or before now, and no case is
      open; otherwise `ending`, with `ending` naming each outstanding code (D7). Verify
      (library integration, `test_watch_and_seller.py`): a released rate deal whose part
      still runs is `ending` with `payment_running`; tearing down with an open case gives
      `release_pending` and `case_open`; all clear gives `ended` with no codes; a case
      filed after `ended` returns `ending`.
      Done: `_outstanding` computes the codes; a repair-required deal lists none (the
      rule's two refinements are the round 1 fixes below). Library integration
      (`test_watch_and_seller.py`, through `SellerServicing.list`): the four planned
      cases pass. The kit README names the codes.
- [x] 2.4 Verify D12 (library integration, `test_final_stop.py`): after the watch records a
      rate part's final stop, the servicing tables hold the stop and the selected end and
      no balance, funded amount or amount owed.
      Done (library integration, passed): with the authority's view carrying an amount
      and a funded boundary, the watch records the stop as the selected end, and no
      `servicing_` table has a money-named column nor any journaled request, intent or
      delivery record a money-named key. Narrower than the task: the stored observation
      views keep the authority's view as read, which D12 admits, so the check leaves them
      out; and the deal is the rig's once-only registration with a rate-shaped part.
- [x] 2.5 (Moved to section 2B; not implemented here.) The two recurring-purchase scenarios
      (`e2e-tests/tests/e2e/roles/scenarios/vms/test_vm_recurring_purchase.py`,
      `.../bare_metal/test_bare_metal_recurring_purchase.py`, their stages in
      `e2e-tests/tests/e2e/roles/helpers/recurring_purchase_stages.py`) assert a refused
      commit. Until section 10 rewrites them on lane time, change only what the refusal's
      removal changes: the deal is delivered (activation, the payments double's rate
      `start` after it, availability), the buyer's own `end` stops it with the started
      period charged, and the seller's read shows the buyer's end; keep the waits they
      make today. Verify (unit, `e2e-tests/tests/unit/test_recurring_purchase_stages.py`)
      and by running both scenarios in their lanes.
      Done through section 2B, which carries this task resized (2B.1–2B.3).
- [x] 2.6 Verification point: `kit/deal-lifecycle`, `kit/deal-servicing` and
      `domains/compute/delivery` suites (unit, library integration) pass. The storefronts'
      suites are section 2A's verification point, which this section's work leaves
      failing four tests in each storefront until 2A rewrites them. End-to-end: none at
      this level; section 2B carries the recurring purchases.
      Done: `kit/deal-servicing` (114), `kit/deal-lifecycle` (82) and
      `domains/compute/delivery` (130) pass, unit and library integration; the
      functional hooks ran at 2A's commit, once the storefront suites passed. End-to-end:
      the recurring purchases (section 2B) are its pipeline evidence. Owed by validation:
      none. Comments left false by the refusal's removal were fixed in sections 2A and
      2B; the permanent documents describing it are 12.9's D1 entry.

Round 1 triage fixes, the list's rule (D7's settled notes; `reviews/32-implementation.triage.md`
F1, `reviews/44-implementation.triage.md` F1): `_outstanding` counts a deal that is not
once-only, whose saved payment view lists no part or that has none, as `payment_running`;
and a deal naming a dispute authority of which no accepted read is saved as
`case_unobserved`, a fourth code with its text in contracts 0.3.0, the delta's closed
list and the kit README. Neither the list nor `unserviceable()` calls such a deal ended.
A rate deal ended before its part started stays `payment_running` until that part's
terms end. `_observed` reads the authority view and whether the dispute view is missing
in one transaction, so a view saved meanwhile cannot leave them disagreeing. Library
integration (`test_watch_and_seller.py`): a released rate deal never observed, then
observed with no parts, lists `payment_running` and `case_unobserved`; a released
once-only deal lists `case_unobserved`, `repair_required` without its credential, the
same after a failed read, and `ended` after one accepted empty read; a deal naming no
dispute authority is `ended` with no read; the missing-adapter report keeps a released
deal until its authority is read. Unit (contracts): the served-page shapes include
`case_unobserved`. `make test-kits` (`kit/deal-servicing` 134, contracts 55, client 3,
every other kit suite passed); pre-commit passed with every functional hook (VM
storefront 1197 passed, 1 skipped, and 623; bare metal 663; e2e unit 911 passed,
1 skipped; release tooling 3123).

## 2A. Both storefronts deliver a rate deal in their recurring test worlds

Delivers each storefront's application-level evidence that a rate deal is committed,
activated, billed and made available once end service no longer refuses it, and that an
undelivered rate deal still meets the deadline barrier. Implements D1 at application
integration; requirements "Delivery authorization delegates payment interpretation"
(`deal-lifecycle`) and "Protected delivery steps are authorized and admitted"
(`compute-delivery`). Touches the two storefronts' test worlds and tests only
(`domains/vms/storefront/tests/`, `domains/bare_metal/storefront/tests/`). Sections 3.3
and 9.3 build their delivered rate deals on these worlds.

- [x] 2A.1 VM: make `domains/vms/storefront/tests/recurring_world.py`'s `settlement`
      deliver a rate deal — its fake site places and commits the deal's capacity, and the
      storefront's capacity runtime, which the end hand-off and the failure policy also
      use, resolves the world's site authority — so a committed recurring deal reaches
      activation, the payments fake's rate `start` and availability. Verify (application
      integration): a new case drives a recurring deal to `available` with its billing
      start journaled after the site's activation.
      Done, differing from the plan in which site: the world delivers against
      `tests.delivery_fakes.DeliverySite`, composed as the one site of a real
      `CapacityRuntime` (`delivery_capacity`) whose effects the coordinator and the end
      hand-off share (`design.md`, "Implementation findings"; the lifecycle takes them
      through 34 O1's U2 below). `DeliverySite` gains `list_reservations`, filtered by
      state and escrow, and an `unreachable` switch, a reserve failing before its effect.
      Application integration (`test_rate_delivery.py`): a settled recurring deal's
      commit is allowed, its reservation committed and activated, billing journaled once
      naming that activation, the payments engine holding the started rate (one
      `submit_event`), and the deal available no earlier than the activation; passed.
- [x] 2A.2 Bare metal: give `domains/bare_metal/storefront/tests/recurring_world.py`'s
      `_OneSite` capacity client what `fulfillment_service.py`'s `fulfill_bare_metal` needs
      (`site_names`, then whatever its dispatch needs, found by running it), so settle no
      longer answers 500 and a committed recurring deal reaches activation, the payments
      fake's rate `start` and availability. Verify (application integration): as 2A.1, in
      bare metal.
      Done: `_OneSite` became `WorldSite`, a subclass of `test_http_settlement.py`'s
      `_CapacityClient` that still serves the projection site and has the same
      `unreachable` switch; dispatch also needed a fulfillment client, now
      `WorldProvisioning`, scheduling the pool member's machine in the world's pool.
      `RecurringWorld` exposes both as `capacity` and `provisioning`. Application
      integration (`test_rate_delivery.py`): as 2A.1, with fulfillment begun once;
      passed. The case asserts availability from end service, since the lifecycle row's
      `state` is provisioning's as last read.
- [x] 2A.3 In each storefront, rewrite `tests/integration/test_rate_delivery_refusal.py` as
      `test_rate_delivery.py`: its refused-commit test becomes a rate deal delivered, with
      billing starting after activation; its three deadline-recovery tests keep their
      scenarios on a rate deal left undelivered (the storefront's evidence for the
      deadline barrier: a deadline admitted after a payment observation, a buyer's stop
      recorded while the storefront was down winning over the deadline, and an unreadable
      authority leaving the deal unended). Rewrite
      `test_watchdog_buy.py::test_a_watched_purchase_whose_commit_is_refused_is_never_watched`
      for the delivered deal: the watched purchase is monitored from `available` (D1;
      the watchdog requirement, `deal-lifecycle`). Verify (application integration): the
      rewritten tests pass in both storefronts.
      Done, correcting the plan's count: each file held two deadline-recovery tests, not
      three; both are kept on a rate deal left undelivered by an unreachable site (commit
      allowed and journaled, nothing placed). The third, the delta's "The payment
      authority is unreadable at the deadline", existed only in the kit, and each file
      adds it whole: the cycle asks the failing authority and journals nothing, and once
      it is readable records seller non-delivery with its one filing. In each storefront
      `test_rate_delivery.py` and
      `test_watchdog_buy.py::test_a_watched_purchase_is_monitored_from_available` pass
      (application integration). The watchdog case runs the production `buy --watchdog`
      against the served storefront, the buy command's `watchdog_probe` and `wait_clock`
      factories its seam: it probes, stops after two failures, the payments engine
      accepts the stop, and the read shows `stopped`; VM's checks the probe was built
      from the disclosed endpoint. VM's settlement wait then had no clock seam, so its
      case runs `buy` with the site unreachable and `--settlement-timeout 0` (exit 4,
      the opt-in journaled), re-settles through the typed client, and resumes with
      `buy --from`.
- [x] 2A.4 Verification point: both storefronts' suites (application integration) pass,
      among them `test_rate_delivery.py`, `test_watchdog_buy.py` and the
      `test_lifecycle_*.py` modules; `scripts/change-workflow run pre-commit` passes.
      End-to-end: section 2B.
      Done: `make -C domains/vms/storefront test` (unit 1194 passed, 1 skipped;
      integration passed), `make -C domains/bare_metal/storefront test` (passed), and
      `scripts/change-workflow run pre-commit` passed with every functional hook.
      End-to-end corrected: section 2B is this section's lane evidence. Owed by
      validation: none. Also in this commit, outside the plan: the comments in
      `domains/bare_metal/storefront/storefront.dev.toml`,
      `domains/vms/storefront/storefront.bob.lane.toml` and
      `domains/compute/delivery/pyproject.toml` that said end service refuses rate deals
      now describe the current system. D1's held answer itself is section 2's
      `test_changed_answer.py`; 2A's cases show delivery and the deadline barrier. This
      section recorded two seam gaps as unowned rows in `openspec/changes/README.md`:
      `VmDealLifecycle`'s capacity collaborator, closed by 34 O1's U2 below, and VM's
      settlement wait with no clock seam, whose gap section 10a closes (10a.2 replaces
      the resume flow above with a fresh `buy` waiting on a fake clock).

Round 1 triage fix, 34 O1's U2 (`reviews/34-implementation-owner.triage.md`), outside
the plan: `VmDealLifecycle` takes `capacity=` and `physical=`; its physical end and
site-report recovery are built over its capacity, and the release failure action uses
the lifecycle's runtime before building one. The composition root passes neither, so
production keeps the configured sites' cached runtime; the test worlds and
`examples/payment_smoke.py` construct with them rather than replacing
`lifecycle.end.physical`. Unit:
`test_failure_policy.py::test_the_release_uses_the_deal_lifecycles_capacity_runtime`. The
unowned row is removed.

## 2B. The recurring purchases are delivered in both lanes

Delivers the interim lane form of the recurring purchase, until section 10 moves it to
lane time: delivered rather than refused, under the waits the scenarios make today.
Implements D1 in the lanes; requirement "A recurring purchase is delivered end to end in
each compute lane" (`test-compatibility`), whose lane-time clause section 10 meets.
Touches `e2e-tests`.

- [x] 2B.1 Rewrite the refused-commit stages in
      `e2e-tests/tests/e2e/roles/helpers/recurring_purchase_stages.py` and their drivers in
      `e2e-tests/tests/e2e/roles/scenarios/vms/test_vm_recurring_purchase.py` and
      `.../bare_metal/test_bare_metal_recurring_purchase.py`, changing only what the
      refusal's removal changes: the deal is delivered (the site's activation, the
      payments double's rate `start` after it, availability), the buyer's own `end` stops
      it with the started period charged (the payer's balance down by one period, not
      restored), and the seller's lifecycle read shows the buyer's end and no
      `delivery_end` filing. Update the stage order
      `e2e-tests/tests/unit/test_recurring_purchase_stages.py` holds. Verify (unit,
      `e2e-tests/tests/unit/`): the stage modules pass.
      Done, more than the refusal's removal: every compute-lane module holds fulfillment
      convergence and the lease watchdog, so each module now composes the payment
      purchase's delivery and teardown stages around the recurring ones (the stage
      order is `test_recurring_purchase_stages.py`'s `EXPECTED_ORDER`).
      `Recurring04_MandateApproved` is read before `Stage09a`, so before delivery can
      start the rate part; the domain's `Stage09a2` runs because `Stage09b` requires it;
      `Recurring05_RateStartedAfterActivation` checks the double's part started no
      earlier than the lease's activation, to the whole second, and the read `active`
      with no end or filing; `Recurring07_BuyerEnds` checks the payer's stop with the
      started period charged, the payer's end with no filing read on the hint before any
      step, then `Purchase10`'s lease checks; `Recurring08_PayerChargedOnePeriod` checks
      the balance down by exactly `PERIOD_GROSS`. `Purchase05` is not run: its debit
      check is a once-only payment's. Each module's cleanup opens the gates, stops the
      buy, ends an unended deal by the buyer's stop and removes the mock rules (bare
      metal also drains provisioning and removes its pool override). The refusal's
      helpers are gone, and the stage, scenario, driver, README and marker texts
      describe delivery. Unit (`make -C e2e-tests test-unit`, 911 passed, 1 skipped),
      among them the order and handoff checks for both modules.
- [x] 2B.2 Run both scenarios in their lanes. Verify (system):
      `e2e_vm_recurring_purchase` and `e2e_bare_metal_recurring_purchase` pass, each
      leaving no payment hold, mock rule or held loop.
      Done (system, each lane's Compose stack with mock provisioning and the payments
      double, each stack taken down after): `make -C e2e-tests test-e2e-vm
      E2E_MODULE=e2e_vm_recurring_purchase` (28 passed) and `make -C e2e-tests
      test-e2e-bare-metal E2E_BARE_METAL_MODULE=e2e_bare_metal_recurring_purchase` (28
      passed), the second runs at the committed stages; cleanup removed every rule and
      override and every hold resumed. The double recorded the rate start in the same
      whole second as the activation, so the lane shows the order only to the second;
      the order itself is each storefront's `test_rate_delivery.py`. "No payment hold" is
      read as nothing reserved for the payer and nothing left running (`design.md`,
      "Implementation findings"). The lanes do not show which move began the teardown.
- [x] 2B.3 Verification point: the `e2e-tests` unit suite and both lane runs pass.
      End-to-end: `e2e_vm_recurring_purchase`, `e2e_bare_metal_recurring_purchase`.
      Done: as 2B.1 and 2B.2; `scripts/change-workflow run pre-commit` passed with every
      functional hook. End-to-end confirmed: `e2e_vm_recurring_purchase` and
      `e2e_bare_metal_recurring_purchase`, which `make run-e2e` also runs, are evidence
      for sections 2, 2A and 2B. Owed by validation: none. `test-compatibility/architecture.md`'s
      refusal passages are 12.9's D9 entry.

## 3. Every payment stop is classified

Delivers lawful classification of payment stops in both domains. Implements D2, D3;
requirement "Cause classification is owned by end service" (`deal-lifecycle`). Touches
`domains/compute` (`arkhai_compute`), `kit/deal-servicing`, both storefronts' watch
factories.

- [x] 3.1 `domains/compute/src/arkhai_compute/end_classification.py`: add
      `classify_payment_stop(event, *, entitlements, term_end)` per D2's table, `terms`
      split by the Agreement's end (D3), returning a kind or `None` for pending. Verify
      (unit, `domains/compute/tests/test_end_classification.py`): each cause, an
      unentitled payer or payee stop pending, an unknown cause pending, `terms` one second
      before, at and after the end.
      Done: the classifier reads the event through a `PaymentStop` protocol (`cause`,
      `at`), since the family package's allowlist admits only the shape kit, and returns
      a `ClassificationKind` string or `None`. Unit (`test_end_classification.py`, 24
      passed): every planned case. `arkhai-compute` 0.3.0; both storefronts take
      `>=0.3.0`.
- [x] 3.2 `kit/deal-servicing/src/market_deal_servicing/watch.py`, `_record_payment_stop`:
      when the stop's record exists with a pending classification and the classifier now
      classifies it, resolve it through `EndSession.resolve_correction` at the record's
      revision, lawful and with no filing (D2). Verify (library integration,
      `test_final_stop.py`): a pending stop recorded without a classifier is resolved on a
      later poll with one; the recorded end is unchanged; a resolved one is not resolved
      twice.
      Done: `EndSession.classification(negotiation_id, source_ref)` reads a recorded
      request's slot (`None` while pending); the watch resolves only a pending slot, at
      the record's revision read inside the observation's transaction. A non-lawful
      classification carries its failure filing as at record time (`_failure_filing`);
      the compute classifier returns only lawful kinds. The kit README says so. Library
      integration (`test_final_stop.py`, through `DealWatch.poll`): the planned cases,
      plus a classifier still answering `None` leaving slot and revision unchanged, and
      a stop resolved as a seller failure journaling its one `delivery_end` filing.
      `kit/deal-servicing` 117 passed.
- [x] 3.3 Pass `classify_payment_stop`, bound to `deal.entitlements` and the Agreement's
      start plus `duration_seconds`, through `DealWatch(classify_payment_end=...)` in
      `domains/vms/storefront/src/market_storefront/deal_lifecycle.py` (`watch`) and
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle.py`
      (`watch`). Verify (application integration,
      `test_lifecycle_ends.py` in each storefront): a delivered rate deal's buyer stop is
      classified an entitled stop, and a provisioning failure after it journals no
      `delivery_end` filing; a once-only deal's payment term end is classified the term
      end, and in bare metal a site withdrawal after it files nothing.
      Done, differing from the plan in bare metal's failure: each watch factory binds the
      classifier to the deal's entitlements and the Agreement's start (truncated to whole
      seconds, as each storefront registers its term end) plus `duration_seconds`, and
      wraps a kind in a `Classification` naming the stop's authority record. Application
      integration, on each recurring world (`test_lifecycle_ends.py`, two new cases
      each): a delivered on-demand deal's payer stop, read by a servicing cycle, is
      recorded `payer` and classified `entitled_stop`; a once-only payments deal, the
      storefront restarted past the Agreement's end, has its payment stop recorded and
      classified `terms`. The seller failure after the stop is, in VM, a provisioning
      failure through the failure policy, correlated to the stop with no filing; in bare
      metal, which records no provisioning failure for a delivered deal, the site's
      signed withdrawal through the lease-ended callback, classified
      `unentitled_withdrawal` with the stop still selected and no filing, and after the
      once-only term end likewise filing nothing. Both storefront suites pass (VM
      integration 607, bare metal 649).
- [x] 3.4 Verification point: `domains/compute` tests (unit), `kit/deal-servicing`
      (library integration), both storefronts' lifecycle suites (application
      integration) pass. End-to-end: `e2e_vm_payment_deal`, `e2e_bare_metal_payment_deal`
      and the two recurring purchases record classified ends; none asserts the
      classification.
      Done: `make -C domains/compute test` (24), `make -C kit/deal-servicing test` (116),
      `make -C domains/vms/storefront test-integration` (607) and `make -C
      domains/bare_metal/storefront test` (649) pass, and `scripts/change-workflow run
      pre-commit` passed with every functional hook. End-to-end corrected: neither payment
      deal records a payment stop, and the two recurring purchases record the payer's
      (now `entitled_stop`) without asserting its classification, so no scenario is
      evidence for this section. Owed by validation: none. The two storefronts'
      identical `classify` closures are kept (`design.md`, "Implementation findings").

## 4. Compositions build their payments stage and report deals they cannot service

Delivers D11 and D8; requirements "Each compute composition builds its payments seller
stage" and "A storefront reports deals its configuration cannot service"
(`market-composition`). Touches `domains/vms/storefront`, `domains/bare_metal/storefront`.

- [x] 4.1 `domains/vms/storefront/src/market_storefront/settlement_composition.py`:
      `VmSettlementComposition` builds `arkhai_payments_stage` in `__post_init__` with
      `servicing_stage(..., rate_servicing=self.rate_servicing)`, as bare metal's does;
      `build_vm_settlement_composition` and `domains/vms/storefront/tests/recurring_world.py`
      stop building their own (D11). Verify (application integration,
      `domains/vms/storefront/tests/integration/test_servicing_composition.py`): a
      composition built from a configuration with the servicing fields has a stage over
      its declaration, with nothing supplied.
      Done: `arkhai_payments_stage` is an `init=False` field the composition sets from
      its payments section, its new `payments_client_for_owner` (`None` builds one from
      the section, as bare metal's does) and its declaration;
      `build_vm_settlement_composition` builds the coordinator over the composition's
      stage, and the recurring world passes the in-process engine as the client. A
      `dataclasses.replace` builds an equal stage again (`design.md`, "Implementation
      findings"). `test_servicing_composition.py`: the served recurring world's
      composition, given no stage, holds one over its own declaration and the section's
      receipt identity — composition construction, narrower than application
      integration; the application evidence that this stage services deals is the
      recurring world's delivered cases, which run on it and pass.
- [x] 4.2 At startup each storefront lists its open deals whose mechanism has no adapter
      composed, logs them naming the missing section, and adds them to its readiness
      report; each such deal lists repair required naming the missing section (D8). Files:
      the startup paths of both storefronts (VM `server.py` startup, bare metal
      `runtime.py`), and `kit/deal-servicing/src/market_deal_servicing/seller.py`'s
      `_authority` reason. Verify (application integration, `test_degraded_startup.py`
      in VM and a new `test_unserviceable_startup.py` in bare metal): a storefront
      restarted with its payments section's servicing fields removed starts, reports the
      open once-only and rate deals, and lists them repair required.
      Done: `SellerServicing` takes `missing_adapters`, by mechanism the configuration
      that would compose an installed mechanism's adapter; a deal of such a mechanism
      with no adapter is `repair_required`, its reason `repair required:
      arkhai.payments.v1 has no lifecycle adapter; configure [Settlement].arkhai_payments
      service_url and service_identity`, ahead of a missing dispute credential; a
      mechanism not named keeps its earlier, non-repair outcome. `unserviceable()` lists
      each such deal still open, paging every registered deal (until the list's rule
      finds nothing outstanding, since 32 F2 below). Bare metal composes the payments
      adapter only while its composition builds a stage. Each startup (VM's
      `_start_vm_services`; bare metal's `server.py`, not `runtime.py` as planned) logs a
      warning per deal, and each status reports `unserviceable_deals` in both status
      response models, which the typed client reads in `extra`. Library integration
      (`test_watch_and_seller.py`, `kit/deal-servicing` 118 passed): such a deal lists
      `repair_required` with that reason and is reported; a composition composing the
      adapter, or naming no missing configuration, reports none; an ended, released deal
      is not reported. Application integration, one deal kind (rate, once-only) per case:
      VM (`test_degraded_startup.py`) settles the deal with its site unreachable, then
      starts the configured app over the same database with an Alkahest-only
      settlement: it starts, logs the deal with its reason, status reports it, and the
      typed `SellerLifecycleClient` lists it `repair_required` and reads its reason; bare
      metal (`test_unserviceable_startup.py`) shows the same by restarting its recurring
      world with `payments_section=False`, which replaces the test runtime's composition
      rather than loading a configuration, so is narrower than VM's. "Servicing fields
      removed" is read in both as no payments section.
- [x] 4.3 Verify withdrawal (application integration, `test_servicing_composition.py` in
      each storefront): a running rate deal accepted under `returned` is still serviced
      after `returned` leaves the declaration, and no new option naming it publishes.
      Done (application integration, passed): in each recurring world an on-demand deal
      naming `returned` is accepted and the declaration narrowed to `charged` in place;
      the deal then settles, is delivered, and its payer's stop is recorded and
      classified `entitled_stop`. "Serviced to its end" is shown as far as the recorded
      end, since the worlds' fakes do not tear down. That no new option naming
      `returned` publishes is the existing evidence: VM's
      `test_publication_loop.py::test_publication_omits_recurring_options_whose_treatments_are_undeclared`
      and bare metal's `tests/test_http_publication_rates.py`.
- [x] 4.4 Verification point: both storefronts' suites pass. End-to-end: every lane starts
      both storefronts from their compositions; no scenario asserts the startup report.
      Done: `make -C domains/vms/storefront test` (unit 1194 passed, 1 skipped;
      integration 611 passed) and `make -C domains/bare_metal/storefront test` (652
      passed); `make -C kit/deal-servicing test` (118). End-to-end confirmed: every lane
      starts both storefronts from their compositions, VM's now building its own stage,
      so any payments scenario (`e2e_vm_payment_deal`, the recurring purchases) is
      evidence that the composition's stage services; none asserts the startup report or
      `unserviceable_deals`. Owed by validation: none. `PAYMENTS_SERVICING_FIELDS` stays
      in each storefront (`design.md`, "Implementation findings").

Round 1 triage fix, 32 F2 (`reviews/32-implementation.triage.md`; D8's settled note):
`unserviceable()` reports a missing-adapter deal until the seller list's rule finds
nothing outstanding over its saved views (`_ended`), not only until its resource is
released; a deal whose views cannot be read stays reported, logged. Library
integration:
`test_watch_and_seller.py::test_a_released_rate_deal_still_billing_stays_unserviceable_until_its_part_stops`.
Both storefronts call `unserviceable()` unchanged, so 4.2's application cases stand.

## 5. What the buyer is shown

Delivers D13 and the D14 rewording; requirements "The buyer is shown the penalty's
collectible bound and why a funding stop is final" and "The buyer refuses seller ends that
keep the started period" (`buyer-orchestration`). Touches `kit/settlement-runtime`,
`kit/deal-lifecycle-buyer`, `domains/vms/buyer`, `domains/bare_metal/buyer`.

- [x] 5.1 `kit/settlement-runtime/src/market_settlement_runtime/buyer_terms.py`: the
      on-demand premature-stop penalty row states the penalty is collectible only from the
      seller's earnings still held, nothing in the first period without a setup charge
      (D13). Verify (unit, the buyer-terms suite): the row's text for an on-demand option
      with and without a setup charge.
      Done: the row (shown for any option with early termination, spot included) says
      the penalty "is collectible only from the seller's earnings still held: under this
      option's holds, what the deal has earned so far and not yet been paid, after
      refunds;" then "nothing in its first period, since it has no setup charge" or, for
      an option carrying `setup_amount`, "in its first period, only the earned setup
      charge". Unit (`kit/settlement-runtime/tests/unit/test_buyer_presentation.py`, a
      new case without and with a setup charge; 304 passed). `kit/settlement-runtime`
      0.8.1; its exact pins moved `kit/arkhai-payments` 0.8.1, `kit/contact-exchange`
      0.5.1, `kit/config` 0.6.1 and `core/buyer` 0.7.1 a patch step each, and their own
      dependents' pins with them.
- [x] 5.2 `kit/deal-lifecycle-buyer` (`lifecycle.py`, `watchdog.py`): take a payment-stop
      classifier slot; when a rate part's final stop classifies as exhaustion, the read
      composition and the watchdog's exit say the balance could not reserve the next
      period, a top-up cannot revive the deal, and a new deal is needed. Both buyers fill
      the slot with `arkhai_compute.classify_payment_stop` (D13). Verify (unit,
      `kit/deal-lifecycle-buyer/tests/unit/`; application integration, each buyer's
      `test_watchdog_rate_stop.py`): an exhaustion stop shows the message; a term-end stop
      does not.
      Done: `BuyerLifecycle(classify_payment_stop=...)` (`PaymentStopClassifier`, a kind
      or `None`) and `funding_stopped(view)`; `buyer_read` adds `funding_stop`, the
      exported `FUNDING_STOP` text or `None`, beside `watchdog` and outside the wire read;
      `WatchdogOutcome` gains `funding_stop`, set when the loop exits on a deal ended by
      another path whose authority view, read within the probe timeout, shows a
      funds-running-out stop, and `run_monitor` appends the text to its exit line. Each
      buyer's `buyer_lifecycle` binds `classify_payment_stop` to the Agreement's
      entitlements and its start (whole seconds) plus duration, and declares
      `arkhai-compute>=0.3.0`. The buyer's delivery output is `buyer_read` itself
      (`market delivery`, `market bare-metal delivery`), so the read, the delivery output
      and the watchdog's exit say it; `buy`'s own progress lines do not.
      `published-packages.md` names `arkhai-compute` among both buyers' internal
      dependencies. `kit/deal-lifecycle-buyer` 0.3.0; VM buyer 0.13.0, bare metal buyer
      0.9.0. Unit (`tests/unit/test_funding_stop.py`, a real `BuyerLifecycle` over mocked
      ports, 55 passed with the suite): an early `terms` stop carries the text in the
      read, the exit line and the outcome; a term-end stop, no classifier and no final
      stop carry none. Each buyer (`test_watchdog_rate_stop.py`, VM buyer 336 and bare
      metal buyer 86 passed): the buyer's own composed lifecycle reads a `terms` stop one
      period before the Agreement's end as funds running out and one at its end as not —
      a unit-level check of the term-end binding, not application integration as
      planned; it exercises neither the entitlements binding nor the whole-second
      truncation, and no engine is driven to exhaust a balance.
- [x] 5.3 D14's rewording is delta-only: confirm each buyer's existing waiver tests cover
      `--allow-charged-preemption` and `--allow-charged-term-end` as the reworded
      requirement states, adding a case where one is missing. Verify (unit): those suites
      pass.
      Done: the policy the reworded requirement states is the kit's
      (`kit/settlement-runtime/tests/unit/test_buyer_terms.py`: each refusal named,
      `test_each_flag_waives_exactly_its_refusal` showing `charged_preemption` admits its
      option while a charged term end is still refused). Each buyer named
      `--allow-charged-preemption` only through `--allow-unprotected-terms`, so VM's
      `test_buy_resume_cli.py` gains a case recording it alone, and bare metal's
      `test_cli_completion.py` a case recording it beside the deadline waiver its fixture
      option needs and carrying it to the approval policy's waivers;
      `--allow-charged-term-end` is recorded by its own flag in each already (unit,
      passed with the suites).
- [x] 5.4 Verification point: `kit/settlement-runtime`, `kit/deal-lifecycle-buyer` and both
      buyers' suites pass. End-to-end: the recurring purchases display the disclosure; no
      scenario asserts the new lines.
      Done: `make -C kit/settlement-runtime test` (304), `make -C kit/deal-lifecycle-buyer
      test` (55), `make -C domains/vms/buyer test` (336), `make -C domains/bare_metal/buyer
      test` (86). End-to-end confirmed: the recurring purchases' buy runs print the
      disclosure, the penalty row included, and no scenario asserts its new words or the
      funding-stop text, so none is evidence for this section. Owed by validation: none.
      The watchdog's exit reads the authority within the probe timeout, as every other
      read in its loop does; the buyer kit checks rate parts only (`design.md`,
      "Implementation findings").

## 6. The kit's servicing step order, respondent port and page position

Delivers the kit helper and its kit-owned state. Implements D4's kit part and D6;
requirement "Each deal's servicing steps run in one kit-owned order" (`deal-lifecycle`).
Touches `kit/deal-servicing`.

- [x] 6.1 Add `kit/deal-servicing/src/market_deal_servicing/servicing.py`: a helper that
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
      Done: `ServicingCycle(path, domain=, loop=, seller=, end=, respondents=, signer=,
      clock=, recovery=[(name, step)], resolve_site_corrections=)`, `cycle(limit=100)`
      returning the page's size; `RespondentPort` and `AgreementRespondent` (a respondent
      adapter carrying `agreement_digest`) beside it, all exported. The domain's
      site-report classifier enters as `resolve_site_corrections(session, negotiation_id,
      now)`, the correction step that applies it, since both domains' corrections wrap
      `arkhai_compute`'s, which the kit cannot import. The authorities read is
      `SellerServicing.read` for a committed deal, which polls the watch and dispatches no
      filing (`SellerServicing.watch` dispatches first, so the cycle does not use it).
      Reconciliation is bare metal's `reconcile_local` moved into the kit. Library
      integration (`test_servicing_order.py`): the step order, each step seeing what the
      ones before it recorded; a deal whose physical port raises still has its term end
      reconciled, corrections run and filing dispatched, two failures logged naming the
      domain, step and deal; a delivered rate deal records `term-end` at the Agreement's
      end, not a second before nor again later, classified `terms`, with no filing; an
      undelivered deal with an unreadable payment authority records nothing until a read
      succeeds, then the deadline (selected) and the term end; an uncommitted surrendered
      deal is paged and driven with neither authority read.
- [x] 6.2 Respondent discovery in the helper: group the page's deals by dispute authority,
      leave out deals with none or with an unusable credential, own the one `resolve`
      (a differing Agreement digest raises into the respondent repairs), and build
      `RespondentPoller` per authority with its record derived from the authority alone
      (`respondent.py`) (D4). Verify (library integration, `test_respondent.py`): one
      discovery per authority whatever deal comes first, an Alkahest deal included; one
      authority's failure logged and the other's still run; an unusable credential leaves
      the deal out and its other steps run; a digest mismatch lands in the repairs.
      Done: `RespondentPoller` takes no `account`; its record is
      `stable_ref("authority", "respondent", <authority identity>)`. An adapter that is
      not an `AgreementRespondent` is not discovered; resolution raises "respondent case
      differs from accepted Agreement" for a differing digest, as VM's did (bare metal's
      returned `None`). Beyond the plan: a resolved case clears its repair under any
      record (by case and commitment), since repairs held under the earlier
      account-and-authority record have no poller to clear them once the listing
      restarts. Library integration (`test_respondent.py`, five new cases, the four
      existing passing with the authority-only record): one listing per discoverable
      authority, before any deal's step, whatever deal sorts first; one authority's
      failed listing logged while the next still lists and every deal's steps run; an
      unusable credential leaves the deal out of discovery and listed `repair_required`;
      a digest mismatch keeps both cases as repairs and the matching adapter resolves
      them; a repair under an account-derived record clears once its case resolves.
- [x] 6.3 Page position: add `servicing_page_position` (one row per loop) to
      `market_deal_servicing.schema` as its own schema set, created by an ordinary
      migration a storefront chain appends; the helper pages every registered deal and
      saves its position after each page (D6). Verify (library integration,
      `test_servicing_schema.py`): the set creates and the position survives a reopen.
      Done: `PAGE_POSITION_SCHEMA` (`loop TEXT PRIMARY KEY, continuation TEXT`, no `IF
      NOT EXISTS`) and `create_page_position`, exported; the cycle pages with
      `committed_only=False` and saves the continuation once the page is serviced, `NULL`
      after the last page, so a storefront stopped mid-page services that page again
      rather than skipping its rest. Library integration (`test_servicing_schema.py`):
      the set creates, refuses a second application, and a position survives a reopen;
      (`test_servicing_order.py`) successive cycles over a reopened file page on and wrap,
      and another loop keeps its own row.
- [x] 6.4 Verification point: `kit/deal-servicing` suites (unit, library integration) pass.
      End-to-end: none until section 7 composes the helper.
      Done: `make -C kit/deal-servicing test` (typecheck clean; 130 passed), and
      `scripts/change-workflow run pre-commit` passed with every functional hook (its
      rerun once hit an unrelated child-reaping race in
      `scripts/tests/test_change_clone.py`, which passed on rerun, `make
      test-release-tooling` 3123 passed). The kit's README describes the cycle, the
      poller's record and the new set; two passages of `deal-lifecycle/architecture.md`
      the poller's record makes stale are 12.9's. The kit stays 0.4.0. End-to-end:
      none. Owed by validation: none. An adapter that lists no cases is kept out of
      discovery (tested).

## 7. Both storefront cycles run the kit's order

Delivers the unified cycles. Implements D4's domain part and D6's migrations;
requirement "Each deal's servicing steps run in one kit-owned order". Touches
`domains/vms/storefront`, `domains/bare_metal/storefront`.

- [x] 7.1 VM: `VmDealLifecycle.cycle` (`deal_lifecycle.py`) calls the helper with its
      site-report recovery and classifier and its respondent port, dropping the cached
      pollers, the in-memory continuation and its own step order; VM thereby records its
      own term end. Append the servicing page-position migration to
      `domains/vms/storefront/src/market_storefront/utils/migrations.py`. Verify
      (application integration, `test_lifecycle_cycle.py`, `test_lifecycle_ends.py`): a
      physical failure does not skip filings; a once-only deal's term end is recorded and
      torn down; the page position survives a restart.
      Done: `VmDealLifecycle.servicing()` builds a `ServicingCycle` per cycle (domain
      `vms`, loop `deal-servicing`, the lifecycle as its respondent port, its signer, one
      recovery step `recover_site_reports`, `resolve_site_corrections` as the correction);
      `cycle(limit=100)` runs it. `self.respondents`, `self.continuation`, the local
      `resolve` and the in-lifecycle deadline admission are gone. The authorities read is
      now `seller.read`, so VM's cycle no longer dispatches filings before its filing
      step. Migration `20261116_001_vm_servicing_page_position` (`create_page_position`).
      `test_lifecycle_cycle.py` (the composed lifecycle over the application's database,
      its cycle called directly — narrower than application integration, since a cycle
      of one deal is reachable only so): a deal whose physical port raises still has its
      journaled filing filed at the mediation fixture, the port called twice; a cycle of
      one saves its position, a newly built lifecycle over the same database services
      the next deal (its `term-end` recorded) and saves `NULL`, and the next cycle wraps
      to the first deal. Application integration (`test_lifecycle_ends.py`, the
      recurring world restarted past the Agreement's end, stepped through the typed admin
      client): the once-only case shows the payment stop and the storefront's own
      `term-end`, both classified `terms`, the selected end at the term end, no filing,
      and the deal `released`; the termination is commanded at the payment stop's
      instant, which the authorities read records first. `test_servicing_unreachable_authority.py`
      expects the kit's discovery log line.
- [x] 7.2 Bare metal: `BareMetalLifecycle.cycle` (`lifecycle.py`) calls the helper with
      `recover_site` and its classifier and its respondent port, dropping its own
      reconciliation's term-end record (now the kit's) and its delivery re-drive (section
      8 moves it). Append to `migrations.py` a migration that creates the page-position
      set and drops `bare_metal_lifecycle_cursor`. Verify (application integration,
      `test_lifecycle_dispatch.py`, `test_lifecycle_ends.py`): a failing `drive_physical`
      still dispatches the deal's filing in the same cycle; an uncommitted surrender gets
      its physical end; respondent discovery runs once per authority with an Alkahest
      deal first on the page.
      Done, differing from the plan in the re-drive: `BareMetalLifecycle.servicing()`
      builds the cycle (domain `bare-metal`, loop `deal-servicing`, the lifecycle as its
      port, `runtime.marketplace_signer`) with two recovery steps, `recover_delivery`
      then `recover_site`; the re-drive stayed a recovery step until section 8's routine
      took it, since no other bare-metal loop then re-drove a delivery. `reconcile_local`
      and `committed` are gone (the kit's); `dispute` is renamed `dispute_adapter`, the
      port's name. Migration `bare-metal-storefront-0020-servicing-page-position` creates
      the set and drops `bare_metal_lifecycle_cursor`. `test_lifecycle_dispatch.py` (the
      cycle called directly, narrower than application integration; the surrender
      through the buyer's typed client): a deal whose physical port raises still has its
      journaled filing filed, the port called twice; a surrender before commit whose
      route-time physical end fails is driven to `released` with no payment read; an
      Alkahest deal sorting first leaves one respondent listing and no discovery
      failure. Application integration (`test_lifecycle_ends.py`): the once-only case
      asserts the storefront's own `term-end` classified `terms` beside the payment stop.
- [x] 7.3 Verify both migration chains (migration tests per
      `docs/guidance/repository/migration-chain-tests.md`): fresh and upgraded databases
      reach the same schema; bare metal's upgrade drops the old cursor table.
      Done (library integration, real SQLite, no application): each chain's existing
      fresh-versus-adopted, rerun and refusal cases pass with the new migration last; an
      adopted VM database ends with the empty page-position table; bare metal's upgraded
      databases, the one holding a cursor row included, match a fresh one with no cursor
      table. `docs/development/DEPLOYMENT_AND_CONFIG.md`'s list of migrations after the
      floor names both.
- [x] 7.4 Verification point: both storefronts' suites pass. End-to-end:
      `e2e_vm_payment_deal`, the `e2e_vm_dispute_*` scenarios, `e2e_bare_metal_payment_deal`
      and the two recurring purchases step the servicing cycle.
      Done: `make -C domains/vms/storefront test` (unit 1194 passed, 1 skipped;
      integration 614 passed) and `make -C domains/bare_metal/storefront test` (655
      passed); `scripts/change-workflow run pre-commit` passed with every functional hook
      at the commit. End-to-end confirmed: those scenarios, and
      `e2e_bare_metal_mock_deal`, step the loop that runs the cycle, so a passing pipeline
      is evidence the kit's order services them; none asserts the order or the page
      position. Owed by validation: none. `vm-storefront-fulfillment/architecture.md`'s
      stale term-end sentences are 12.9's.

## 8. One delivery re-drive routine

Delivers D5's shared re-drive; requirement "Unfinished deliveries are re-driven by one
routine" (`compute-delivery`). Touches `domains/compute/delivery`, both storefronts'
delivery ports.

- [x] 8.1 `domains/compute/delivery/src/compute_delivery/recovery.py`:
      `recover_deliveries(path, domain, *, limit)` over a `DeliveryRecovery` port of
      `unfinished_deliveries`, `claim` (an async context answering whether it claimed) and
      `revalidate`, exported from the package (D5). Verify (library integration, new
      `tests/integration/test_recover_deliveries.py`): a claimed, revalidated deal is
      driven; an unclaimed or unrevalidated one is not.
      Done: `recover_deliveries` lists, then per deal claims, re-checks and drives,
      returning how many it drove; each deal runs in its own error handler, logged
      `[DELIVERY_RECOVERY] <id> was not re-driven`, so one deal's failure leaves the next
      recovered. `path` is a `DeliveryDrive` protocol (`drive(negotiation_id)`), which
      `ComputeDeliveryPath` satisfies, so a domain may pass its own entry around the
      path (VM's records the outcome, below). `DeliveryDrive`, `DeliveryRecovery` and
      `recover_deliveries` are exported. Library integration
      (`test_recover_deliveries.py`, the real path, the port a recording double, 4
      passed; the package 134): a waiting deal at its start is claimed, re-checked and
      driven inside the claim; a held deal is neither re-checked nor driven; one that
      does not re-check is released undriven; a raising re-check is logged and the next
      deal driven. The package stays 0.2.0.
- [x] 8.2 VM fills the port with `list_incomplete_vm_deliveries`, its claim lease and its
      stage's `recover_evidence`, replacing `resume_incomplete_fulfillments_once`'s loop
      (`fulfillment_resume_runtime.py`); bare metal fills it with its lifecycle-row query,
      its lock and its settlement service's `verified_evidence`, replacing
      `BareMetalLifecycle.recover_delivery` (D5). Verify (application integration,
      `test_fulfillment_resume_runtime.py` in VM, `test_restart_recovery.py` in bare
      metal): a deal waiting for its start is claimed, revalidated and driven at the start;
      a deal another worker holds is skipped; a deal whose evidence fails is not driven.
      Done, differing from the plan in each domain's drive, in bare metal's claim and
      test file, and (until 34 O1's U3 below) VM's test level. Both domains' `revalidate`
      answers `False` with a warning when the evidence does not re-check, an unreachable
      chain included; only an unexpected error raises, which the routine logs. Both list
      at most 50 deals a pass. VM: `VmDeliveryRecovery` (the incomplete-deliveries query,
      the `claim_vm_delivery` lease held across re-check and drive, the stage's
      `recover_evidence`) and `VmRecoveryDrive`, driving through `drive_vm_delivery` so
      the outcome is recorded and the failure policy runs once;
      `resume_incomplete_fulfillments_once` keeps its signature and now counts every
      drive it made, and a failure building the path is one deal's, not the cycle's.
      Bare metal (`delivery_recovery.py`): `BareMetalDeliveryRecovery` lists unreleased,
      undelivered deals (`list_unreleased_bare_metal_fulfillments`, new, with
      `recover_delivery`'s filter), re-checks through the new
      `BareMetalFulfillmentService.revalidate`, and drives through `redeliver`, so every
      delivery still enters through core's fulfillment hook; its claim only answers
      whether the deal's lock is free (`design.md`, "Implementation findings").
      `recover_delivery` is gone. Evidence — VM: see 34 O1's U3 below. Bare metal
      (`integration/test_delivery_path.py`, where the waiting deal's setup already is,
      rather than `test_restart_recovery.py`; application integration, the
      `delivery-recovery` loop stepped through the typed admin client): the waiting deal
      is re-checked twice (the routine's and `deliver`'s gate), driven under its lock,
      activated and available (`redriven` 1); a held lock re-drives nothing; a raising
      escrow verifier answers `False` with its warning and begins nothing; a deal whose
      end was recorded while it waited is listed no more. The four
      `test_lifecycle_dispatch.py` readiness-adoption cases step `delivery-recovery`
      rather than calling the cycle. Not exercised: an end recorded while the re-drive's
      drive holds the lock (the hook's unchanged `finally` physical end).
      `recovery_stages.py`'s docstrings name the re-drive.
- [x] 8.3 Verification point: `domains/compute/delivery` and both storefronts' suites pass.
      End-to-end: every scenario that re-drives a delivery, among them
      `e2e_vm_payment_purchase`, `e2e_bare_metal_mock_deal` and the recurring purchases.
      Done: `make -C domains/compute/delivery test` (134), `make -C domains/vms/storefront
      test-unit` (1194, 1 skipped) and `test-integration` (617), `make -C
      domains/bare_metal/storefront test` (657); `scripts/change-workflow run pre-commit`
      passed with every functional hook. End-to-end corrected: the scenarios that
      re-drive a delivery through the loops are evidence for the routine — `e2e_deal`
      (VM's delivery-timing phase) and `e2e_bare_metal_mock_deal` (its recovery stages);
      the recurring and payment purchases deliver through the settle task or `commit`,
      so are not. None asserts the routine's own order. Owed by validation: none.
      Passages of `compute-delivery/architecture.md` and
      `physical-provisioning/architecture.md` are in 12.9's D5 list.

Round 1 triage fix, 34 O1's U3 (`reviews/34-implementation-owner.triage.md`):
`vm_delivery_path` and `read_vm_credentials` default to the deal lifecycle's capacity
runtime and fulfillment client, so the `delivery-recovery` loop's re-drive reaches the
site a composition's lifecycle was given. 8.2's three VM cases are in the new
`tests/integration/test_delivery_recovery_loop.py`, application integration (the
recurring world's served storefront, `delivery-recovery` stepped through the typed
admin client): the waiting deal re-checked once, claimed by a `delivery-recovery:` owner
and released, activated, `redriven` 1; another worker's claim skipped, `redriven` 0; an
impostor-pinned stage's re-check refused with its warning, nothing begun. The older
direct callers (`test_vm_delivery_path.py`'s three, `test_fulfillment_resume_runtime.py`'s
four Alkahest cases) remain a narrowed unowned row in `openspec/changes/README.md`.

## 9. One loop layout, and restart recovery proven

Delivers D5's layout and D14's restart evidence; requirement "Both compute storefronts run
one loop layout" (`market-composition`). Touches both storefronts' loop registration,
their configuration, `e2e-tests`.

- [x] 9.1 Register `deal-servicing`, `delivery-recovery`, `payment-reconciliation` and
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
      Done. Loop names `deal_servicing`, `delivery_recovery`, `payment_reconciliation`,
      `settlement_servicing` (routes hyphenated). VM: `deal-servicing` runs
      `lifecycle.cycle()`, `delivery-recovery` `resume_incomplete_fulfillments_once`
      (reporting `redriven`), `payment-reconciliation` the coordinator's
      `reconcile_once`, `settlement-servicing` the worker alone; new keys
      `deal_servicing_interval_seconds` (unstated,
      `settlement_servicing_interval_seconds`) and `delivery_recovery_interval_seconds`
      (unstated, `fulfillment_resume_sweep_interval`), each refused unless positive
      seconds, as `fulfillment_resume_sweep_interval` now is too. Bare metal: the same
      two optional keys, unstated meaning `payment_reconciliation_interval`; the
      regenerated values schema takes the umbrella chart and `bare-metal-storefront` to
      0.5.0. Both storefronts' `payment-reconciliation` steps report `attempted` and
      `failed`, and both packaged `settings.toml` files say which interval each loop runs
      at. Beyond the plan, every servicing loop in both storefronts runs its first cycle
      one interval after its timer starts (VM's `fulfillment-resume` ran at once), and
      bare metal registers all four loops whatever it composes, each idle when its job
      has nothing composed. `docs/guidance/repository/deterministic-tests.md`'s loop
      table and `docs/configuration.md`'s failure-policy paragraph name the new loops.
      Evidence — VM application integration (`test_lifecycle_status.py`): the four loops
      reported paused through the typed client; a `deal-servicing` step reads the
      payment authority and delivers nothing; the registered intervals with old and new
      keys stated, and a zero key refused by name. VM unit
      (`test_lifecycle_advance_routes.py`, `test_loop_gate_wiring.py`): each step runs
      exactly its one job, `deal-servicing` neither the worker nor the re-drive, and the
      four are gated. Bare metal application integration
      (`integration/test_lifecycle_dispatch.py`, over the payments harness rather than
      `test_app_composition.py`, which has no deal): the four loops reported paused; a
      `deal-servicing` step reads the payment authority and leaves a ready fulfillment
      `unstarted`, which a `delivery-recovery` step re-drives to `active`;
      `test_app_composition.py` and `test_http_system.py`: the intervals unstated and
      stated, a zero key refused, all four listed, idle loops stepping with nothing to
      do.
- [x] 9.2 Rename the loops in the lane stages that pause and step them (the 11 files
      under `e2e-tests/tests/e2e/roles/` naming `fulfillment-resume`,
      `settlement-servicing` or `delivery-recovery`, and `held_loops.py` in bare metal's
      tests). Verify (unit, `e2e-tests/tests/unit/`): the stage modules pass; and by
      running the affected scenarios in their lanes.
      Done, correcting the plan's count: ten lane files name a loop, and bare metal's
      `held_loops.py` names none. Renamed by what each step needs: the servicing cycle
      is `deal-servicing`, VM's re-drive `delivery-recovery`; the Alkahest worker's steps
      stay `settlement-servicing` and bare metal's re-drive `delivery-recovery`. Unit
      (`make -C e2e-tests test-unit`): 911 passed, 1 skipped. System:
      `make -C e2e-tests test-e2e-vm` over `e2e_vm_payment_deal`,
      `e2e_vm_recurring_purchase`, `e2e_deal` and the six `e2e_vm_dispute_*` markers, 178
      passed, the stack taken down after; the bare-metal run is recorded in 9.4.
- [x] 9.3 Restart recovery (D14, application integration, `test_restart_recovery.py` in
      bare metal and a new `test_restart_recovery.py` in VM): restarting the composed
      storefront over the same database with a running rate deal, an ending deal and a
      pending seller stop resumes each — the running deal stays served, the ending deal
      ends when its stop is read, the pending stop takes effect at its instant.
      Done, one deal per case, in a new `tests/integration/test_restart_recovery.py` in
      each storefront (bare metal's flat `tests/test_restart_recovery.py` holds its
      once-only Alkahest restarts). Application integration: each recurring world
      delivers a rate deal, stops, and is composed again over the same database and
      payments engine, its loops held and stepped through the typed admin client.
      Running: the deal stays `active` in the buyer's typed read, no end, nothing
      re-driven. Ending: a payer's stop submitted while the storefront is down shows in
      the buyer's read only after the restarted `deal-servicing` step, classified
      `entitled_stop`. Pending seller stop: a spot deal's payee stop with 120 seconds'
      notice records no end before its instant and the `payee` stop at it,
      `entitled_stop`, read from the servicing journal, since the storefront's clock is
      then ahead of the typed reader's. Each restarted world's site is a fresh fake, so
      none asserts the teardown. VM 3 passed (integration 623), bare metal 3 passed.
- [x] 9.4 Verification point: both storefronts' suites pass; `make check-packaging` passes.
      End-to-end: every scenario stepping a renamed loop, among them `e2e_vm_payment_deal`,
      the `e2e_vm_dispute_*` scenarios, `e2e_vm_payment_purchase`,
      `e2e_bare_metal_mock_deal`, `e2e_bare_metal_payment_deal`,
      `e2e_bare_metal_publication` and the two recurring purchases.
      Done: `make -C domains/vms/storefront test` (unit 1196 passed, 1 skipped;
      integration 623 passed), `make -C domains/bare_metal/storefront test` (663 passed),
      `make check-packaging` (passed), `make -C e2e-tests test-unit` (911 passed, 1 skipped).
      System, each stack taken down after: the VM lane over `e2e_vm_payment_deal`,
      `e2e_vm_recurring_purchase`, `e2e_deal` and the six `e2e_vm_dispute_*` markers (178
      passed), and the bare-metal lane over `e2e_bare_metal_publication`,
      `e2e_bare_metal_mock_deal`, `e2e_bare_metal_payment_deal` and
      `e2e_bare_metal_recurring_purchase` (113 passed), before the fresh-context fixes,
      which changed nothing either lane runs but docstrings. End-to-end confirmed: those
      scenarios step the renamed loops (`e2e_vm_payment_purchase` steps none of them)
      and are the pipeline's evidence for the layout; none asserts the intervals or the
      restart cases, which are application integration only. Owed by validation: none.
      `scripts/change-workflow run pre-commit` passed with every functional hook. The
      `TESTING.md` and `vm-storefront-fulfillment/architecture.md` passages are 12.9's.

Round 1 triage fix, 34 O1's U4 (`reviews/34-implementation-owner.triage.md`), outside
the plan: `core/storefront-client`'s `admin_run_lifecycle_cycle` docstrings, sync and
async, list the loops the compute storefronts register; the client is 0.29.1, and
`provisioning/compute/service`, its one exact pin moved, 0.25.1. The unowned row is
removed.

Round 1 triage fixes' evidence (32 F1, 32 F2, 34 O1's U2, U3, U4): library integration,
`kit/deal-servicing` 133 passed; VM storefront unit 1197 passed, 1 skipped, and
application integration 623 passed; bare metal 663 passed;
`scripts/change-workflow run pre-commit` passed with every functional hook (e2e unit
911 passed, 1 skipped; release tooling 3123), and `make check-repository
CHANGE=serve-running-rate-deals CHANGE_BASE=dev` passed every check. The fix round's
fresh-context check found no correctness defect; `_ended` reports and logs a deal whose
view cannot be read.

## 9A. A deal nobody filed on is observed with no case

Delivers the mediation adapter's read of an Agreement the authority holds no record of
as an empty record, so such a deal can be listed *ended* and both halves' reads carry
an accepted dispute outcome. Implements D16 (and D7's 44 F1 rule resolving through it);
requirement "The seller half lists deals", its scenario "A deal nobody filed on is
observed with no case" (`deal-lifecycle`). Touches `kit/arkhai-mediation` and the tests
of `kit/deal-servicing`, both storefronts and the VM buyer.

- [x] 9A.1 In `kit/arkhai-mediation/src/market_arkhai_mediation/adapter.py`, `_read`
      answers a first-page `404 invalid_request` (no entries read yet) with an accepted,
      empty `AuthorityView` for every caller, so `read()` returns it; the
      `unregistered_for_filing` flag and its comment go, the delivery-end filing path
      reading through the same `_read` (D16). A `404` after a page was read, any other
      status, and every verification failure stay failures, as today. In
      `fixtures/authority.py`, `MediationContractFake`'s `/record` answers
      `404 {"code": "invalid_request"}` for an Agreement no filing has made known, as the
      authority and `tools/mediation-lane-double` do, instead of an empty page. Bump the
      kit 0.3.0 → 0.3.1 and raise the bounds and locks of its dependents
      (`package-versions.md`; `locks.md`). Verify (library integration,
      `kit/arkhai-mediation/tests/integration/`): a read of an Agreement with no record
      is accepted with no disputes and no cases; after a filing the next read shows the
      filed case; a `404` on a later page and a `5xx` stay failures;
      `test_semantic_filing.py`'s first read is now accepted, its one-case adoption
      unchanged; the delivery-end filing still files once and adopts.
      Done, differing from the plan in one name: `_read` is folded into `read()`, the
      one read path, which the delivery-end filing now calls, so the flag goes with the
      private method. A `404 invalid_request` before any page was read answers an
      accepted, empty `AuthorityView`; the comment states D16's unchecked premise and
      its limit. The fake's `/record` answers `404 {"code":
      "invalid_request"}` for an Agreement no entry names. Kit 0.3.1; the bounds of the
      two storefronts, the two compute buyers (each already bumped by this change) and
      `kit/deal-servicing`'s dev group raised to `>=0.3.1`; `make lock` moved every lock
      naming the kit. The kit README's paragraph on the initial `404` now describes the
      read (12.9's D16 entry notes it). Library integration
      (`tests/integration/test_unfiled_read.py`, new, against the contract peer): the
      first read of an unfiled Agreement is accepted with no dispute and no case, and
      after a filing the next read shows it; a `404` after a page, a `503`, `404
      authentication_required` and `403 invalid_request` stay failures.
      `test_semantic_filing.py`'s first read is accepted and empty, and both
      delivery-end callers still adopt one case with one POST. `make -C
      kit/arkhai-mediation test`: 121 passed, the contract, generated-model and mypy
      checks passing.
- [x] 9A.2 Prove the seller's and the buyer's sides over the kit's fake. In
      `kit/deal-servicing/tests/integration/test_watch_and_seller.py`, a deal naming a
      dispute authority with no record, released, its rate part stopped: the watch saves
      a dispute view with no case, the list shows it `ended` with no `ending`, and a
      filing then makes it `ending` with `case_open`. The buyer's read
      (`domains/vms/buyer/tests/test_lifecycle_adoption.py`) of such a deal carries an
      accepted outcome. Verify (library integration): those cases pass with each
      package's suite.
      Done. Library integration, `kit/deal-servicing`
      (`test_watch_and_seller.py::test_a_released_stopped_deal_nobody_filed_on_is_ended_until_a_party_files`,
      the real `MediationAdapter` over the contract peer): the released deal lists
      `ending ["payment_running", "case_unobserved"]` before any watch; one poll saves an
      accepted dispute view with no case, and the list shows `ended` and the seller's
      `read` an accepted outcome; after the payer files, the next poll makes it `ending
      ["case_open"]`. `make -C kit/deal-servicing test`: 135 passed. VM buyer
      (`test_lifecycle_adoption.py::test_the_buyers_read_of_a_deal_nobody_filed_on_carries_an_accepted_outcome`,
      narrower than library integration, having no storage): the kit's `BuyerLifecycle`
      composed as `buyer_lifecycle()` composes it, over the real adapter and the peer,
      carries an accepted outcome with no case. `buyer_lifecycle()` itself is not
      exercised, since `_MediationPort` has no transport seam — an unowned row in
      `openspec/changes/README.md`. `make -C domains/vms/buyer test`: 337 passed.
- [x] 9A.3 One application-integration case per storefront: the composed storefront,
      read through its typed lifecycle client, lists a released, stopped deal whose
      authority holds no record of its Agreement `ended`
      (`domains/vms/storefront/tests/integration/test_lifecycle_cycle.py`,
      `domains/bare_metal/storefront/tests/integration/test_lifecycle_dispatch.py`).
      Verify (application integration): both cases pass, with each storefront's
      integration suite.
      Done, on each storefront's payments harness, not the recurring world, whose
      dispute policy holds no credential: a once-only payments deal, the Agreement
      pinning the contract peer's authority, its end service's physical end releasing
      at once. In each, the deal is settled, the buyer ends it through the typed buyer
      client, the typed seller list shows `ending ["case_unobserved"]`, a servicing cycle
      reads the peer's record (VM's `cycle()` called directly, since that harness mounts
      no loop route; bare metal's `deal-servicing` step through the typed admin client,
      its harness injecting the peer's client and the credential's availability), and
      the list shows `ended` with no open case and the typed `read` an accepted outcome
      with no case. Both pass with their modules (VM 6, bare metal 11) and each
      storefront's whole suite (VM unit 1199 passed, 1 skipped, integration 633; bare
      metal 676).
- [x] 9A.4 Verification point: `kit/arkhai-mediation`'s, `kit/deal-servicing`'s, the VM
      buyer's and both storefronts' suites pass, and `scripts/change-workflow run
      pre-commit serve-running-rate-deals` passes. End-to-end: the recurring purchase's
      final `ended` check (`e2e_vm_recurring_purchase`,
      `e2e_bare_metal_recurring_purchase`, section 10) and every lane deal naming the
      mediation double read through it; the VM dispute scenarios (`e2e_vm_dispute_*`)
      file first, so the change reaches them only through reads after their filings.
      Done: `make -C kit/arkhai-mediation test` (121 passed), `make -C
      kit/deal-servicing test` (135), `make -C domains/vms/buyer test` (337), and
      `scripts/change-workflow run pre-commit serve-running-rate-deals` with every
      functional hook — every package's suite, among them the VM storefront (unit 1199
      passed, 1 skipped; integration 633), bare metal (676), the bare-metal buyer,
      the API-credits packages whose locks moved, and the e2e unit suite (991 passed,
      1 skipped) — passed. End-to-end confirmed: section 10's final `ended` check is
      the lane evidence; the `e2e_vm_dispute_*` scenarios meet the read only after their
      filings. Owed by validation: none. `settlement-servicing/architecture.md`'s
      "Initial missing mediation history permits the first filing only" is 12.9's D16
      entry.

Pre-closeout fix (`reviews/88-pre-closeout.triage.md`, F1): since D16 a saved dispute view
can come from the adapter's unverified initial-`404` read, so `seller.py`'s `_observed`,
`_outstanding` and `unserviceable()` docstrings, and, outside the plan, `watch.py`'s
`_observe`, say "saved" and "accepted" rather than "verified", leaving what an accepted
read assures to its adapter. Docstrings only, no version step. `make -C
kit/deal-servicing test`: 135 passed; `scripts/change-workflow run pre-commit
serve-running-rate-deals` passed with every functional hook at 8df52d8fe (VM storefront
unit 1199 passed, 1 skipped, integration 634; bare metal 676).

## 9B. The scenario programs the payments double's further reservation

Delivers the payments double's reservation control and its typed client, so a lane row
reaches instants past a rate part's first reservation. Implements D17; requirement "Lane
double controls are typed deterministic steps", its scenarios "A rate part's further
periods are reserved", "A reservation is refused when no rate part runs" and "A rate
part is not reserved unasked" (`test-compatibility`). Touches `kit/arkhai-payments`,
`tools/lane-double-controls`, `tools/payments-lane-double`.

- [x] 9B.1 In `kit/arkhai-payments/src/market_arkhai_payments/fixtures/authority.py`, give
      `PaymentsAuthority` a public reservation method: for a transaction, bring it to the
      clock as a read does, then reserve each running rate part (started, not stopped)
      through a named instant, as far as the part's end and the payer's balance allow, on
      `_refill`'s arithmetic with the named instant as its lead; answer each such part's
      index, its reserved-through instant and the periods added; refuse a transaction with
      no running rate part, changing nothing. `advance`, the reads and the reservation at
      `start` are unchanged (D17). The kit is already one step past dev (0.8.1); no
      further bump. Verify (library integration, a case beside the engine's in
      `kit/arkhai-payments/tests/`): a payer funded one period beyond the first
      reservation is reserved one period further, the snapshot's `fundedThrough` moves to
      it and a read at that instant shows the `terms` stop; reserving through the part's
      end stops at the end; an unstarted, a once-only and a stopped part are refused with
      nothing changed; without the method, time past the first reservation still stops
      the part there.
      Done: `PaymentsAuthority.reserve(transaction, through)` runs `advance(...,
      refill=False)`, refuses `PaymentsAPIError(409, "no_running_rate_part")` before
      any change when no rate part is started and unstopped, and otherwise reserves
      each such part through `_reserve_to`, the per-part body `_refill` now calls
      with its own lead, so the reservation at `start` is unchanged; each answer is
      `{"part", "reserved_through", "periods_added"}`, `reserved_through` from
      `_reserved_through`, which the snapshot's `reservedThrough` now shares. Like
      `_refill`, a lead reserves to cover 60 seconds past it, so a `through` on a period
      boundary short of the part's end reserves the next period too. The kit README's
      engine paragraph names the method and the slack (12.9's D17 entry). Differing
      from the plan, the kit takes 0.9.0, a minor step for new public API
      (`versioning.md`; `design.md`, "Implementation findings"), and the bare-metal
      storefront's and buyer's exact pins move to `==0.9.0`. Unit
      (`kit/arkhai-payments/tests/test_rate_reservation.py`, the engine on an injected
      clock, unit rather than the planned library integration since it owns no storage):
      the planned cases, with the reservation through or past the end capped there, an
      unknown transaction `404 transaction_not_found`, and refusals leaving the snapshot
      and balance unchanged. `make -C kit/arkhai-payments test`: 362 passed, the vector,
      generated-model and mypy checks passing.
- [x] 9B.2 In `tools/lane-double-controls`, add the reservation route,
      `POST /test/transactions/{transaction}/reserve`, to the payments party in
      `routes.py`, its request (`through`) and answer (`transaction`, `parts` with
      `part`, `reserved_through`, `periods_added`) to `models.py`, the refusal code
      `no_running_rate_part` beside the controls' typed codes, and the typed client's
      `reserve(transaction, through)`; bump 0.1.0 → 0.1.1. Verify (unit,
      `tests/unit/test_models.py`, `test_routes.py`): the models refuse a malformed body
      and the route is the payments party's alone.
      Done: `RESERVE` in `routes.py` (payments alone); `Reservation` (`through`, a
      strict instant held to the time component's range), `ReservedPart` and
      `Reserved` (`transaction` a transaction id, `parts` at least one, so an answer
      reaching nothing cannot parse) in `models.py`; `no_running_rate_part` and,
      beyond the plan, `transaction_not_found` among the control codes, the second
      for 9B.3's `404`; `ControlClient.reserve(transaction, through)`. Version 0.2.0,
      not the plan's 0.1.1, for new public API (as 9B.1). Unit (`test_models.py`,
      `test_routes.py`): malformed bodies and answers are refused; the route is the
      payments party's alone. `tests/integration/test_client.py` gains `reserve`'s
      request and answer. `make -C tools/lane-double-controls test`: 149 passed, the TLS
      and strict mypy checks passing.
- [x] 9B.3 In `tools/payments-lane-double/src/payments_lane_double/app.py`, serve the
      route over the engine's method, authenticated by the control token: `200` with the
      answer, `409 no_running_rate_part` for a transaction with no running rate part,
      `404` for an unknown transaction, both changing nothing. Bump 0.2.0 → 0.2.1, which
      also covers section 10's second payer in `fixtures/accounts.toml`; refresh the
      lock. Verify (application integration,
      `tools/payments-lane-double/tests/integration/test_controls.py`, through the typed
      client over HTTP, the payments kit's client reading): the three delta scenarios —
      reserved one period further with the signed snapshot's funded boundary at the
      answer and the `terms` stop there once injected time reaches it; refused for an
      unstarted, a once-only and a stopped part with the snapshot unchanged; not
      reserved unasked.
      Done: `PaymentsDouble.reserve` under the double's lock — a transaction it never
      approved is `ControlError(404, "transaction_not_found")`, the engine's refusal
      `ControlError(409, "no_running_rate_part")`, both before any change — and the
      control handler registered from `controls.RESERVE`, refusing a malformed
      transaction id or body `422 invalid_request`; the double's check that it serves
      exactly the routes the contract gives it holds. Version 0.3.0, not the plan's
      0.2.1, for the new control route (`versioning.md`, as 9B.1); it also covers
      section 10's second payer in `fixtures/accounts.toml`. Its bounds are raised
      to the payments kit `>=0.9.0` and the controls `>=0.2.0`; `make lock` moved
      every lock naming the three packages. Application integration
      (`tests/integration/test_controls.py`, the app in process behind the typed
      control client, read through the payments kit's client): the three delta
      scenarios — a part reserved one period further, the verified snapshot's
      `fundedThrough` at the answer and the `terms` stop there once time is set; the
      three refusals with the snapshot unchanged; no reservation unasked — plus `404
      transaction_not_found` and hand-sent malformed requests `422 invalid_request`.
      `make -C tools/payments-lane-double test`: 101 passed.
- [x] 9B.4 Write the double's `README.md` "Controls" (the reservation control: what it
      reserves, its bounds, its refusal; nothing reserved unasked) and "What it claims",
      and `tools/lane-double-controls/README.md`'s "The controls" (the route).
      Done: the double's "Controls" gains the reservation control (what it reserves,
      its arithmetic, its 60-second slack and bounds, nothing reserved unasked, its
      two refusals) and its refusal list the two codes; "What it claims" names the
      three scenarios its suite drives through the typed control client. The
      controls' README gains the route's row, a paragraph on the control, its slack
      and its answer, and three refusal rows.
- [x] 9B.5 Verification point: `kit/arkhai-payments`', `tools/lane-double-controls`' and
      `tools/payments-lane-double`'s suites pass, and `scripts/change-workflow run
      pre-commit serve-running-rate-deals` passes. End-to-end: section 10's rate rows
      and section 11's watchdog cases, each of whose reservation stages calls it.
      Done: `scripts/change-workflow run pre-commit serve-running-rate-deals` passed
      with every functional hook after the fresh-context fixes and the version
      change — among its suites the payments kit (362 passed), the controls (149),
      the payments double (101), the mediation double (78), both storefronts and
      the bare-metal buyer, whose exact pins moved, and the e2e unit suite (991
      passed, 1 skipped). End-to-end: sections 10 and 11's reservation stages are its
      lane evidence. Owed by validation: none.

## 10. Rate deals qualified in both lanes on lane time

Replanned against the reviewed design (D16–D19, design review 60) after the first lane
run returned the change to design; the tasks below replace the earlier 10.1–10.3.

Delivers the recurring purchase and the three rate rows on lane time in both Compose
lanes, labelled lane-double evidence. Implements D9 and D19, consuming D16 (9A) and D17
(9B); requirements "A recurring purchase is delivered end to end in each compute lane"
and "Rate deals are qualified in both compute lanes on lane time" (`test-compatibility`).
Needs `drive-the-storefront-clock-in-lanes` landed (it is archived and merged). Touches
`e2e-tests`, and `tools/payments-lane-double`'s fixture (the second payer, already
committed, its version bumped in 9B).

- [x] 10.1 Finish both recurring purchases on the lane-time helper, as written in the
      work in progress: set lane time to the Agreement's start, step `delivery-recovery`,
      assert activation, the rate `start` and availability; the buyer's `end` a minute
      into the first period, step `deal-servicing`, assert the started period charged,
      the entitled stop recorded, the teardown, and `Recurring10_SellerListsTheDealEnded`
      showing `ended` once released, which 9A's read makes reachable (D9, D16). Verify
      (system): `e2e_vm_recurring_purchase`, `e2e_bare_metal_recurring_purchase` pass.
      Done: the recurring stages run on lane time — `Recurring05_DeliveryRecoveredAtTheStart`
      after `Stage09a2`; the buyer's stop `STOP_INTO_PERIOD_SECONDS` into the first
      period, since the double charges nothing for a stop at the start itself;
      `Recurring10_SellerListsTheDealEnded` stepping `deal-servicing` and paging the
      typed seller list, its docstring naming D16's unchecked premise. System (each
      lane's Compose stack, mock provisioning, both doubles, injected lane time): VM's
      passed in the 10.5 run, `Recurring10` listing the deal `ended` with its part's
      final stop present. Bare metal's first run failed at `Recurring10` alone, the deal
      `repair_required`: the lane's secret overlay held no `[[DisputeCredential]]` for
      the mediation double. Fixed outside `e2e-tests`, small and understood:
      `dev-env/identities/bare-metal.storefront.secrets.toml` gains the seller's
      credential, `scripts/tests/test_committed_stack_values.py`'s restated-credential
      check covers both compute lanes, and `dev-env/identities/README.md` names it; the
      whole bare-metal lane then passed (10.5).
- [x] 10.2 Add the reservation stage to
      `e2e-tests/tests/e2e/roles/helpers/rate_servicing_stages.py`: a stage of its own,
      declared only in the lane modules (`test-doubles.md`, "Shared stages never depend
      on a double"), calling 9B's `reserve` through the harness's typed control client
      and failing on any refusal; it records the answer's `reserved_through` for the
      stages after it (D17). Remove `move_lane_time_through`; each row sets lane time
      straight to its instant (D9). Verify (unit, `e2e-tests/tests/unit/`): the stage
      order check (`ORDERS`) holds every row with its reservation before the lane-time
      set it serves.
      Done: `Reservation06_ThroughTheAgreementsEnd` calls
      `ControlClient.reserve(settlement_id, ceil(agreement_end))`, asserts the answer
      and the snapshot's `reservedThrough` and `fundedThrough` agree, and records
      `first_reserved_through` and `reserved_through`. A refusal fails the stage; off
      injected lane time or a lane-owned payments target it is a blocked skip, as
      `Exhaustion00`'s funding is (`_require_lane_double`). The funds-running-out and
      maximum-term rows declare it before their lane-time set; the preemption row
      declares none, since its 120-second notice takes effect inside the two periods
      the part holds once started, which `Preemption07` asserts.
      `move_lane_time_through` is gone. `e2e-tests` takes `lane-double-controls>=0.2.0`.
      Unit (`make -C e2e-tests test-unit`, 999 passed, 1 skipped): the order and handoff
      checks hold every module (`ORDERS`), and a new case holds the reservation before
      the stages listed in the hand-kept `SETS_PAST_THE_FIRST_RESERVATION`.
- [x] 10.3 Rewrite the rows in `scenarios/{vms,bare_metal}/rate_servicing/` on the stage:
      funds running out funds `rate_payer` one period beyond its first reservation,
      reserves through the Agreement's end, sets lane time to the reserved boundary,
      steps `deal-servicing`, and asserts the `terms` stop there — after the first
      reservation's end, before the Agreement's end — its consequences (cause, instant,
      no filing, teardown) and the buyer's `delivery` read's `funding_stop`; the maximum
      term reserves the shared buyer's part through the Agreement's end, sets it, and
      asserts `returned`, the term-end consequences and no exhaustion; preemption
      reserves through the stop's effective time where the seller's notice runs past the
      first reservation, then as before. Shipped presets, default buyer, lane
      declaration `[charged, returned]`, each labelled lane-double evidence (D9, D19).
      Verify (unit, `e2e-tests/tests/unit/`): `make -C e2e-tests test-unit` passes.
      Done: the rows (a conftest, a stages module and three row modules per lane) run on
      a second payer in the payments double's fixture, `rate_payer`, funded with nothing
      and given its own key, restated in `config-payments-lane.yml` and held equal by
      `test_lane_env.py`. Funds running out funds it to `FUNDED_PERIODS`
      (`FIRST_RESERVATION_PERIODS` plus one; `design.md`, "Implementation findings")
      and `Exhaustion07` asserts the reserved boundary between the first reservation's
      end and the Agreement's end, sets lane time to it and asserts the stop's
      consequences, since no route reads a storefront's classification. The maximum term
      sets lane time to the reserved `ceil(agreement_end)`. Module docstrings, the two
      row markers and `e2e-tests/README.md` describe the reservation. Unit: as 10.2.
- [x] 10.4 Diagnose why the registry answered `404` for the funds-running-out and
      preemption rows' listings, which the storefront created open, while the maximum
      term's and the recurring purchase's published; fix it in the harness, or, if the
      cause is a defect in a storefront or the registry, fix it here when small and
      understood, recording the evidence, and otherwise stop and report it
      (`docs/guidance/workflow/changes.md`, "Defects found during a change"). Verify: the
      rows' listings publish in 10.5's runs.
      Done, a harness defect: the two rows' GPU models, "RTX 4060" and "RTX 4060 Ti"
      (`scenarios/vms/host_registry.py`), are not among the models the registry's
      filter spec admits (`core/registry/src/core_registry/filter-spec.yaml`), whose
      publication route refuses such a listing, while the maximum term's "RTX 4070 Ti"
      and the recurring purchase's "RTX 4070" are. The rows now use "RTX 4080 Super"
      and "RTX 4070 Super", admitted and used by no other scenario, and the constants'
      comment says why. The 10.5 VM run published all three rows' listings.
- [x] 10.5 Run both lanes. Verify (system): `make -C e2e-tests test-e2e-vm
      "E2E_MODULE=e2e_vm_recurring_purchase or e2e_vm_rate_servicing"` and `make -C
      e2e-tests test-e2e-bare-metal "E2E_BARE_METAL_MODULE=e2e_bare_metal_recurring_purchase
      or e2e_bare_metal_rate_servicing"` pass, each leaving no payment hold, mock rule
      or held loop, each stack taken down after; `e2e-tests/README.md` and the Makefile's
      lane lists describe the modules as run.
      Done (system, each lane's Compose stack, mock provisioning, both doubles,
      injected lane time; lane-double evidence, each module logging the label and the
      doubles' contract hashes): `make -C e2e-tests test-e2e-vm "E2E_MODULE=e2e_vm_recurring_purchase
      or e2e_vm_rate_servicing"` 121 passed, none skipped. Bare metal's run of the two
      markers had 120 passed and `Recurring10` failed (10.1); after the credential fix,
      `make -C e2e-tests test-e2e-bare-metal` over every default module of the lane,
      the two markers among them, 219 passed. Each stack taken down after. In both
      lanes: funds running out reserved one period further (first reservation
      start+1800, boundary start+2700, Agreement end start+3600), the `terms` stop and
      recorded end at the boundary, no filing, teardown, and the buyer's read giving
      `FUNDING_STOP`; the maximum term reserved to the end, the `returned` stop and term
      end there, no funding stop; preemption's notice held 120 seconds, the `payee` stop
      at its effective time, the payer's started first period returned under the spot
      preset. Cleanup removed every rule and hold ("no payment hold" read as in 2B.2).
      The Makefile's lane lists name both row markers; `e2e-tests/README.md` describes
      the rows as run.
- [x] 10.6 Verification point: the `e2e-tests` unit suite and both lanes' runs pass.
      End-to-end: `e2e_vm_recurring_purchase`, `e2e_bare_metal_recurring_purchase`,
      `e2e_vm_rate_servicing`, `e2e_bare_metal_rate_servicing`.
      Done: as 10.2 and 10.5. End-to-end confirmed: those four markers, which the
      lanes' default module lists and validation's pipeline (`make run-e2e`) select,
      are the pipeline's evidence for this section; the two recurring purchases'
      `Recurring10` is its evidence for 9A's unfiled-Agreement read (the deal listed
      `ended`; no rate row reads the seller's list), and the funds-running-out and
      maximum-term rows' `Reservation06` for 9B's reservation control. Owed by
      validation: none. `scripts/change-workflow run pre-commit` passed with every
      functional hook (the e2e unit suite 999 passed, 1 skipped; the release tooling
      3208 passed, so the parametrized credential check rendered both lanes' Compose).
      The documents the credential left stale (`DEPLOYMENT_AND_CONFIG.md`, `TESTING.md`,
      `compose.bare-metal-local.yml`'s comments) were corrected. Changes after the lane
      runs touched only stage guards, one snapshot assertion, docstrings, comments and
      documents; the lanes were not run again.

## 10a. Every wait of VM's `buy` on the command's wait clock

Delivers VM's commit loop and settlement wait paced by the `buy` command's `wait_clock`,
as bare metal's commit and availability waits already are, so a clock the harness
programs paces every wait `buy` makes. Implements D20 (75 F1); requirement "The buyer's
watchdog is qualified against a delivered deal" (`test-compatibility`: every wait `buy`
makes stepped). Touches `core/buyer` (`core_buyer/orchestration.py`) and
`domains/vms/buyer` (`arkhai_vms_buyer/arkhai_payments.py`, `settlement_stages.py`,
`buy_cli.py`), and their tests. `arkhai-core-buyer` (0.7.1) and `arkhai-vms-buyer`
(0.13.0) are already one step past the development branch on this branch, so neither
takes a further version (`docs/guidance/repository/package-versions.md`, "Versioning
policy"); `arkhai-vms-buyer`'s lower bound on `arkhai-core-buyer` rises to `>=0.7.1`.

- [x] 10a.1 `core_buyer.orchestration.wait_for_settlement` takes a `monotonic` callable
      beside its `sleep`, defaulting to `time.monotonic`, and measures its deadline on
      it, so a caller's clock paces the whole wait (D20). Verify (unit,
      `core/buyer/tests/`): with a fake `monotonic` advanced only by the fake `sleep`,
      the wait polls until a terminal status and times out after `total_timeout` of
      fake time, never sleeping real time.
      Done: `wait_for_settlement(..., monotonic=time.monotonic)` measures its deadline
      on `monotonic` and pauses on `sleep`. Differing from the plan's level: the status
      is read through the module's own `poll_settlement_status`, which no seam replaces,
      so the two new cases sit in `tests/integration/test_settlement_progress_privacy.py`
      against a loopback seller (integration over real HTTP, no application). On a fake
      clock: `pending`, `pending`, `ready` returns after two 30-second fake pauses;
      always `pending` with a 90-second total polls four times and raises
      `TimeoutError`. `make -C core/buyer test`: 190 passed.
- [x] 10a.2 VM's settle path runs on the command's clock: `settle_payment`'s commit loop
      reads the clock's `monotonic` and awaits its `sleep` where it reads
      `time.monotonic` and `asyncio.sleep` today, and its `wait_for_settlement` call,
      and `settlement_stages.py`'s other one (the resumed settle), pass the clock's
      `monotonic` and a synchronous adapter of its `sleep`. The clock reaches the payment
      stage from `buy_cli.wait_clock()` as bare metal's reaches its stage
      (`arkhai_bare_metal_buyer/cli.py`, the settlement stage built with
      `clock=wait_clock()`; `settlement_stages.py`'s `clock: WaitClock` parameter), so
      the one factory paces commit, settlement and watchdog alike; the stage's default
      stays `WaitClock()` (D20). Verify (application integration through the typed
      client, `domains/vms/storefront/tests/integration/test_watchdog_buy.py`): a fresh
      `buy --watchdog` whose `wait_clock` is a fake clock, its `monotonic` advanced
      only by the sleeps it is given, waits for delivery while the composed storefront's
      site holds it back, sleeping no real time and timing out in fake time when the
      deal never arrives; and, once the site delivers, the same command enters its
      watchdog from `available`. The existing VM buyer tests that replace `wait_clock`
      (`domains/vms/buyer/tests/test_buy_resume_cli.py`) still pass.
      Done: `settle_payment` takes `clock: WaitClock = WaitClock()`; its deadline,
      commit retries and settlement wait read `clock.monotonic` and pause on
      `clock.sleep`, the settlement wait through `sync_sleep(clock)`, which runs the
      clock's sleep on `run_sync`'s own loop. `make_payment_settle_hook`,
      `BuyerStageContext`, `BuyerResumeContext` (`clock` defaulting to `WaitClock()`),
      `make_legacy_settle_hook` and `run_settle_from_log` carry it; the Alkahest
      resumed settle's `wait_for_settlement` takes the context clock's `monotonic`
      and `sync_sleep`. `buy` and `buy --from` build one `wait_clock()` and hand it
      to the settle and to `_watch`, so one clock paces commit, settlement and
      watchdog. Beyond the plan, the Alkahest fresh settle's wait also takes the clock
      (core's `make_escrow_settle_hook` gains `monotonic`); waits still on real time are
      named in `design.md`, "Implementation findings". Versions, differing from the plan:
      the new `monotonic` keywords are new public API, so `arkhai-core-buyer` goes 0.7.1
      → 0.8.0, `arkhai-vms-buyer` takes `>=0.8.0` and `arkhai-bare-metal-buyer`'s exact
      pin moves to `==0.8.0`. Application integration (`test_watchdog_buy.py`, the
      composed storefront on loopback, the shipped `buy` on a `FakeWaitClock`): with the
      site unreachable, `buy --watchdog --settlement-timeout 600 --poll-interval 30`
      polls 21 times on fake pauses and ends `timeout` (exit 4), opted in and unprobed;
      with the site answering after the second pause, the same command reads `ready`,
      enters its watchdog from `available`, probes the disclosed endpoint on the same
      clock and ends `stopped`. This replaces 2A.3's resume flow; the resume's re-entry
      stays proven by `test_buy_resume_cli.py` (unit), which also shows the resumed
      settlement given the command's clock. `make -C domains/vms/storefront test`: 1199
      passed, 1 skipped, and 634 passed.
- [x] 10a.3 Verification point: `make -C core/buyer test`, `make -C domains/vms/buyer
      test` and `make -C domains/vms/storefront test` pass, and
      `scripts/change-workflow run pre-commit serve-running-rate-deals` passes.
      End-to-end: `e2e_vm_recurring_purchase`, `e2e_vm_payment_purchase` and every other
      VM lane module running `market buy` exercise the changed waits on the default
      clock; section 11's `e2e_vm_rate_watchdog` exercises them on the harness's clock.
      Done: `make -C core/buyer test` 190 passed; `make -C domains/vms/buyer test` 337
      passed; `make -C domains/vms/storefront test` passed (see 10a.2); `run
      pre-commit` passed with every functional hook. End-to-end confirmed: the VM lane
      modules running `market buy` as a subprocess run the changed waits on the default
      `WaitClock`; `e2e_vm_rate_watchdog` (section 11) runs them on the harness's
      clock. Owed by validation: none.

## 10b. Bare metal's probe built from the access its caller read

Delivers bare metal's `watchdog_probe` taking the access the storefront disclosed,
read by its caller, as VM's takes its delivery's connection details, so the harness's
probe sees the disclosed endpoint while the buyer's own read of the access runs.
Implements D20 (75 F2). Touches `domains/bare_metal/buyer`
(`arkhai_bare_metal_buyer/cli.py`) and the tests that replace its probe factory.
`arkhai-bare-metal-buyer` (0.9.0) is already one step past the development branch, so it
takes no further version.

- [x] 10b.1 `watchdog_probe` takes the access mapping `fulfillment.access` serves, and
      `_deliver_and_watch`, the one caller, which `buy` and its resume both reach, reads
      it through `_recovered_transports` before building the probe; a disclosure naming
      no host or port still raises the `ValueError` the caller reports as "Watchdog not
      running". The fakes replacing it take the new argument:
      `domains/bare_metal/buyer/tests/test_run_log_recovery.py`,
      `domains/bare_metal/buyer/tests/test_watchdog_cli.py` and
      `domains/bare_metal/storefront/tests/integration/test_watchdog_buy.py` (D20).
      Verify (application integration through the typed client,
      `domains/bare_metal/storefront/tests/integration/test_watchdog_buy.py`): the probe
      factory receives exactly the access the composed storefront's access route serves
      for the deal; (unit, `domains/bare_metal/buyer/tests/test_watchdog_cli.py`): a
      disclosure without host or port leaves the deal unmonitored with that message.
      Done: `watchdog_probe(access)` reads the mapping's `host` and `port`;
      `_deliver_and_watch` reads `fulfillment.access(deal.negotiation_id)` through
      `_recovered_transports` inside the same `try` that reports a `ValueError` as
      "Watchdog not running", so a run that cannot be recovered is reported as
      before. The three fakes take the access. The unit tests also replace
      `_recovered_transports`, a factory the command module defines;
      `docs/guidance/repository/test-placement.md`'s list of the bare-metal buyer CLI's
      seams names it. Unit (`test_watchdog_cli.py`, `make -C domains/bare_metal/buyer
      test` 87 passed): a resume's probe is built from the access the transport served;
      an access naming no host or port leaves the deal unmonitored with that message,
      probing nothing and sending no stop. Application integration
      (`test_watchdog_buy.py`, the shipped `buy --watchdog`): the probe factory is given
      one access naming the endpoint the provisioning double delivered. Differing from
      the plan: it is compared with that endpoint rather than a second read of the
      route, which serves only while the lease is active and is closed by the
      watchdog's stop. `make -C domains/bare_metal/storefront test`: 676 passed.
- [x] 10b.2 Verification point: `make -C domains/bare_metal/buyer test` and `make -C
      domains/bare_metal/storefront test` pass, and `scripts/change-workflow run
      pre-commit serve-running-rate-deals` passes. End-to-end:
      `e2e_bare_metal_recurring_purchase` and the bare-metal lane's other buy modules run
      the changed factory only where a deal opted into the watchdog, which none does;
      section 11's `e2e_bare_metal_rate_watchdog` exercises it.
      Done: both suites pass (10b.1); `run pre-commit` passed with every functional
      hook over this section's and 10a's edits. End-to-end confirmed: no bare-metal
      lane module opts into the watchdog, so none reaches the changed factory;
      `e2e_bare_metal_rate_watchdog` (section 11) does. Owed by validation: none.
      `arkhai-bare-metal-buyer` stays 0.9.0; its exact pin on `arkhai-core-buyer` moved
      with 10a's bump.

## 11. The buyer's watchdog against a delivered deal

Replanned twice — from a fixture stopping the storefront (D10, D18, design review 60),
then from a harness listener no mock-provisioning rule can disclose (D20, design review
75); the tasks below are the second replan's.

Delivers the buyer watchdog's four delivered-deal cases in both Compose lanes on one deal
each, the shipped `buy` run in the harness's process with its probe and every wait it
makes programmed by the harness, labelled lane-double evidence. Implements D10, D18, D19
and D20; requirement "The buyer's watchdog is qualified against a delivered deal"
(`test-compatibility`). Consumes 10a and 10b. Needs `drive-the-storefront-clock-in-lanes`
landed (archived and merged). Touches `e2e-tests` only.

- [x] 11.1 An in-process buyer helper in `e2e-tests/tests/e2e/roles/helpers/`, with D20's
      mock layer:
      - it runs the shipped command — `buy`, `buy --from` and the buyer's read — through
        its Typer app with `CliRunner` in a worker thread, as
        `domains/vms/storefront/tests/integration/test_watchdog_buy.py` does, entering at
        the `market` root so its callback reads the buyer's configuration;
      - it replaces the domain CLI's `watchdog_probe` (VM
        `arkhai_vms_buyer.buy_cli`, bare metal `arkhai_bare_metal_buyer.cli`, each with
        its own signature after 10b) with a probe answering as the stage programs it,
        reachable or not, making no network call and recording the endpoint it was built
        for;
      - it replaces the CLI's `wait_clock` with a `WaitClock` whose `now` is the
        harness's installed lane-time source, whose `sleep` is a gate the stage releases
        one interval at a time, and whose `monotonic` advances by each interval
        released; a stage can wait until `buy` is parked at the gate, release one
        interval, or deliver an interrupt at the gate, which ends the command as a
        buyer's interrupt does;
      - it writes the buyer's configuration with no `[time]` table, so the callback
        installs no source and the harness's lane-time source stays installed (75 F3);
      - it scopes the buyer's environment — its `XDG_*`, `HOME` and credential
        variables — for the module with a module-scoped `pytest.MonkeyPatch` context,
        undone when the module ends (75 F3);
      - it refuses a read unless `buy` is parked at the gate or no command runs, so
        `CliRunner`'s stream swaps nest (75 F3).
      `e2e-tests/tests/e2e/roles/buyer_cli.py`'s docstring names the in-process watchdog
      cases as the exception to driving the binary as a subprocess, and why (D20).
      Verify (unit, `e2e-tests/tests/unit/`): one release advances `monotonic` by one
      interval and lets exactly one sleep return; an interrupt at the gate ends the
      command; the probe answers as programmed and records its endpoint; the written
      configuration has no `[time]` table; the environment is restored when the context
      ends; a read while `buy` is between gates is refused.
      Done: `e2e-tests/tests/e2e/roles/helpers/in_process_buyer.py` — `WaitGate` (a
      thread condition: each sleep parks; `release` advances `monotonic` by the
      parked sleep's seconds and lets it return; `interrupt` makes it raise
      `KeyboardInterrupt`), `ProgrammedProbe` (one factory for both domains, each
      taking one endpoint argument after 10b), `InProcessRun` (a `MarketRun`, so
      `Purchase03` and the recurring purchase's cleanup take it unchanged) and
      `InProcessBuyer`, entered through `in_process_buyer(cli, command_module=…)`,
      which refuses a configuration stating `[time]`, sets the buyer's environment
      (`BuyerCli.environment()`, now shared with the subprocess runner) and both
      factories with a `pytest.MonkeyPatch` context, and on exit interrupts a command
      still running and clears the `--config` path the callback set.
      `create_profiled_buyer_cli` and both purchase-CLI builders take
      `lane_time_file=False`. Beyond the plan, found in the first VM lane run: a
      foreground command runs with logging held (`_logging_held`), and the stages read
      a background command's outcome from its exit status and run log
      (`watchdog_started`, `watchdog_exited`), since pytest's stream swaps take its
      output (`design.md`, "Implementation findings"). `e2e-tests/pyproject.toml` takes
      `typer` and raises its three buyer bounds to this change's versions.
      `buyer_cli.py`'s docstring names the exception and why. Unit
      (`tests/unit/test_in_process_buyer.py`, 8 passed, a small Typer app standing in
      for `market` and a domain CLI): every planned case, plus a foreground command's
      output kept under re-pointed streams, a command still running at the end
      interrupted, and a second background command refused. Differing from the plan:
      "no `[time]` table" is shown by the context's refusal of a configuration stating
      one, which every lane module passes through; no unit test drives
      `create_profiled_buyer_cli` under an injected profile, since it reads the run's
      settings.
- [x] 11.2 Add `e2e_vm_rate_watchdog` and `e2e_bare_metal_rate_watchdog` under
      `scenarios/{vms,bare_metal}/rate_watchdog/`, each one module on one deal with its
      own registered host, taking its lane's hold fixtures as every lane module does
      (`docs/guidance/repository/deterministic-tests.md`), so the storefront's loops are
      the paused ones D18 names. In order (D20):
      1. the in-process `buy` of a recurring on-demand option under the shipped preset,
         default buyer, lane declaration `[charged, returned]`, with
         `--watchdog --watchdog-interval 1 --watchdog-threshold 2`, parked at the gate
         while it waits for delivery; the stage sets lane time to the Agreement's start
         and steps `delivery-recovery` (and, in each lane, what the recurring purchase's
         delivery stages step), then releases the wait; the command enters its watchdog
         from `available`; one interval released with the probe reachable; the buyer's
         read shows `monitored`, and the probe was built for the endpoint the deal
         disclosed (VM's delivery's connection details; bare metal's access route);
      2. lane time set a minute into the first period (`STOP_INTO_PERIOD_SECONDS`, as
         `Recurring08`), so the later stop charges the started period;
      3. an interrupt at the gate; lane time set past the last probe by one interval, the
         probe timeout and `GRACE_SECONDS`, as the opt-in's settings give them; the read
         shows `unmonitored`;
      4. the in-process `buy --from`; one interval released with the probe reachable; the
         read shows `monitored`;
      5. the probe unreachable and the threshold's intervals released: the watchdog sends
         one payer stop and hint, the command exits with the outcome `stopped`; the
         signed snapshot read through the payments kit (`transaction_snapshot`) shows the
         part started and stopped by `payer`, charged, and no other stop, so nothing from
         the storefront came between; the storefront's lifecycle read shows the recorded
         end with cause `payer` and no filing, recorded on the hint (D18);
         `deal-servicing` stepped and the teardown begun (`begin_teardown`, as
         `Recurring08`).
      No instant passes the part's first reservation, so the modules declare no
      reservation stage (D17's requirement binds only rows that do). Each module logs
      the lane-double evidence label and the doubles' contract hashes, and is blocked off
      injected lane time or a lane-owned payments target, as the rate rows are (D19).
      Markers in `e2e-tests/pyproject.toml`, the Makefile's lane lists
      (`E2E_MODULE`, `E2E_BARE_METAL_MODULE`) and `e2e-tests/README.md`. Verify (unit,
      `e2e-tests/tests/unit/`): the stage order check (`ORDERS`) holds both modules,
      with no reservation stage; the lane-holds check
      (`test_scenario_lane_holds.py`) and the cleanup-order check hold them.
      Done: `e2e-tests/tests/e2e/roles/helpers/rate_watchdog_stages.py`
      (`RateWatchdogState`, the `RateWatchdogDriver` protocol, `Watchdog01`–`05`)
      and one module per lane, `scenarios/{vms,bare_metal}/rate_watchdog/test_rate_watchdog.py`
      with its `conftest.py`: the recurring purchase's stages through `Recurring06`,
      `buy` parked at the gate in its wait for delivery while delivery is stepped; then
      `Watchdog01`–`05` run the planned steps in order, with the teardown stages around
      `Watchdog05`. `Watchdog05` asserts the loops and lease watchdog held, the
      double's events exactly `start`, `stop`, the part stopped by `payer` and
      `charged`, the payer's end with no filing before any step, and the teardown begun.
      Beyond the plan's step 2: `Watchdog02` releases one interval at the new instant,
      so `Watchdog03`'s staleness rests on a probe stamped there (without it, the read
      would be `unmonitored` before any kill). The drivers read VM's connection details
      from the typed settle status's unmodelled fields and bare metal's access route;
      VM's module has its own host, pool, resource and GPU model (`RTX 4070 Ti Super`),
      bare metal's driver seeds its own machine. Each takes its lane's holds and
      cleanup, plus ending the in-process command still running;
      `require_watchdog_lane` blocks it off injected lane time or a lane-owned payments
      target (`lane_double_run`, shared with the rate rows, and `buyer_read` moved to
      `recurring_purchase_stages.py`). Markers, both Makefile lane lists and
      `e2e-tests/README.md`. Unit (`make -C e2e-tests test-unit`, 1024 passed, 1
      skipped): `ORDERS` holds both modules to `WATCHDOG_ORDER` with no reservation,
      and the lane-holds, cleanup-order and holds checks pass both.
- [x] 11.3 Run both lanes. Verify (system, each lane's Compose stack, mock provisioning,
      both doubles, injected lane time): `make -C e2e-tests test-e2e-vm
      E2E_MODULE=e2e_vm_rate_watchdog` and `make -C e2e-tests test-e2e-bare-metal
      E2E_BARE_METAL_MODULE=e2e_bare_metal_rate_watchdog` pass, each leaving no payment
      hold, mock rule, held loop or running in-process command, each stack taken down
      after.
      Done (system, each lane's Compose stack, mock provisioning, both doubles,
      injected lane time; lane-double evidence, each module logging the label and the
      doubles' contract hashes). The first VM runs failed at `Watchdog01` on the two
      defects fixed in 11.1 and 11.2 (the settle status's unmodelled connection details;
      pytest's live logging taking the read's output). Then `make -C e2e-tests
      test-e2e-vm E2E_MODULE=e2e_vm_rate_watchdog` 30 passed, the probe built for
      `127.0.0.1:2222`, and `make -C e2e-tests test-e2e-bare-metal
      E2E_BARE_METAL_MODULE=e2e_bare_metal_rate_watchdog` 30 passed, for
      `198.51.100.7:22`; after the fresh-context fixes each lane ran again with its
      watchdog and rate servicing markers, VM 121 passed, bare metal 121 passed. In
      each, the read went `monitored` at the Agreement's start and a minute in,
      `unmonitored` eight seconds after the killed command's last probe, and
      `monitored` on resume; the watchdog's stop was accepted, the end recorded with no
      filing, the teardown completed. Each command had ended at the stop, and cleanup
      removed every rule and hold. Each stack taken down after.
- [x] 11.4 Verification point: `make -C e2e-tests test-unit` and both lanes' runs pass, and
      `scripts/change-workflow run pre-commit serve-running-rate-deals` passes.
      End-to-end: `e2e_vm_rate_watchdog`, `e2e_bare_metal_rate_watchdog`, which the
      lanes' default module lists and validation's pipeline (`make run-e2e`) select.
      Done: as 11.1–11.3; `run pre-commit` passed with every functional hook before
      the fresh-context check's fixes and again after them. End-to-end confirmed:
      `e2e_vm_rate_watchdog` and `e2e_bare_metal_rate_watchdog` are in the lanes'
      default module lists, which validation's pipeline selects; the rate servicing
      and recurring purchase markers also run the moved `buyer_read` and
      `lane_double_run`. Owed by validation: none.

## 12. Closeout

Closes the change through `docs/guidance/workflow/closeout.md`'s parts in order, with this
repository's own parts (`openspec/README.md`, "This repository's closeout parts") after
campaign index currency.

- [x] 12.1 Comment hygiene: run `make check-comment-hygiene`; a finding, or a comment this
      change added that names a change, a task or a review, returns the change to
      implementation.
      Done: `make check-comment-hygiene` passed (no change ids, task numbers or change
      names in code). The comments the change added were read at the pre-closeout
      review (88), whose one finding, two docstrings calling a saved dispute view
      "verified", was fixed in its triage round. Noted, not returned: VM storefront
      comments older than the change still say "the resume pass"
      (`delivery_ports.py`, `domain_runtime.py`, `payment_repository.py`,
      `payment_settlement.py`, `settlement_composition.py`) and
      `e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal.py`'s docstring a "resume-pass step"; the
      routine they name, `resume_incomplete_fulfillments_once`, still exists and is what
      the `delivery-recovery` loop runs, so they are not false, though the loop's name
      differs. Left for the closeout review to weigh.
- [x] 12.2 Import placement: confirm every import this change added is at module level, or
      return the change to implementation.
      Done: the change's Python diff against `origin/dev` adds no indented `import` or
      `from … import`.
      Order note: `openspec/README.md`, "End-to-end pipeline", says closeout dispatches
      `make run-e2e`; the closeout skill takes that evidence from the latest passing
      validation and runs none, which 12.8 follows.
- [x] 12.3 Documentation compliance: re-check D1–D20 against
      `docs/guidance/workflow/openspec-documentation.md` and `openspec/README.md`,
      "Documentation placement", and that every permanent document written describes the
      current state.
      Done: each decision's destination (the promotion record in `design.md`) is the
      owning capability's spec and companion, the cross-system description documents,
      a project README or the guidance file for its subject; D15 has none. The promoted
      text was scanned for wording relative to the change ("no longer", "now" outside
      the clock's, change names, decision or review numbers) and holds none.
- [x] 12.4 Narrative compression: shorten completed tasks to final behaviour, evidence,
      deferred work and destinations, moving any rationale into `design.md` first.
      Done: sections 1–11's notes shortened (the file from 3013 to about 1800 lines);
      fresh-context fix lists, superseded handoffs and repeated `run test-before`
      explanations removed; lasting findings — deviations' reasons, test-world
      composition, lane readings, version steps beyond D16/D17's wording — moved to
      `design.md`, "Implementation findings".
- [x] 12.5 Roadmap currency: in `docs/development/ROADMAP.md`'s Goal 8, remove this
      change's open-gap row; absorb into the current state that both storefronts deliver
      and service rate deals, classify payment stops, list *ended* and *ending*, share one
      servicing order and loop layout, and qualify the rate rows in both lanes as
      lane-double evidence; drop "VM/bare-metal respondent lifetime and term-end handling
      still differ"; name the edit in the design-promotion record.
      Done: Goal 8's open-gap row removed; its current state says both storefronts
      deliver and service rate deals (changed answers held, every payment stop
      classified, *ended*/*ending*, one servicing order and loop layout, the startup
      report), the buyer's display, and the lane rows and watchdog cases as lane-double
      evidence; the respondent/term-end sentence dropped; "the first two are the MVP
      changes" now names one; recorded in the promotion record.
- [x] 12.6 Campaign index currency: update this change's row in
      `openspec/changes/README.md`; remove the unowned row "`VmSettlementComposition`
      builds no payments seller stage" (D11) and "The VM buyer's settlement wait has no
      clock seam" (D20, 75 F1); run `make check-change-index`.
      Done: the row is `in closeout` with its Notes rewritten; both unowned rows
      removed; the Goal 8 prose's "dark, because end service refuses …" made current;
      the dependency graph and every other row's `Depends on` and status unchanged.
      `make check-change-index` passed.
- [x] 12.7 Packaging: run `make check-packaging`, then `make check-architecture-change
      CHANGE=serve-running-rate-deals`; resolve every failure or owned exception.
      Done: `scripts/change-workflow run pre-archive` ran both at `21afffcba`: passed,
      exit 0 (every packaging rule OK; the change owns no architecture row). The change
      touched no `.agents/`, `.claude/` or `.codex/` path, so `make check-agent-skills`
      is not owed here; it runs among `run pre-commit`'s defaults.
- [x] 12.8 End-to-end pipeline: dispatch `make run-e2e` at the closeout's code and collect
      `make fetch-e2e-logs`; record the result and the scenarios exercising this change —
      `e2e_vm_recurring_purchase`, `e2e_bare_metal_recurring_purchase`,
      `e2e_vm_rate_servicing`, `e2e_bare_metal_rate_servicing`, `e2e_vm_rate_watchdog`,
      `e2e_bare_metal_rate_watchdog`, and the scenarios sections 7–9 name. A failed run
      returns the change to implementation; one that could not run is recorded as unrun
      with its cause.
      Done, from the latest validation (`reviews/93-validation.md`, passed) at
      `21afffcba`, the pre-closeout commit this closeout's documents sit on; closeout
      changes no code and dispatches no run. Pipeline: `e2e.yml` run 44313410524,
      success — e2e-vm 444 passed, e2e-bare-metal 249 passed, e2e-apicredits 4 passed.
      The change's scenarios ran in those lanes and passed with them:
      `e2e_vm_recurring_purchase`, `e2e_vm_payment_purchase`, `e2e_vm_payment_deal`,
      `e2e_vm_rate_servicing` (funds exhausted, maximum term, preemption),
      `e2e_vm_rate_watchdog`; `e2e_bare_metal_recurring_purchase`,
      `e2e_bare_metal_payment_deal`, `e2e_bare_metal_rate_servicing`,
      `e2e_bare_metal_rate_watchdog`; the record gives lane totals, not each marker's
      line. Local (`check-packaging`, `test`) and Helm passed too; no scenario the change
      adds runs against Helm. No section owed an observation to validation (every
      `Owed by validation` reads none).
- [x] 12.9 Promotion: write the permanent documents below and complete the
      design-promotion record (`docs/guidance/workflow/changes.md`, "The design-promotion
      record"); the six `spec.md` files are written by the archive.
      - D1: `openspec/specs/deal-lifecycle/architecture.md`, "One end instant,
        transactional admission" (the refusal paragraph replaced by the changed-answer
        rule; the deadline barrier's "refused rate deal" wording) and "Current limits"
        (the "No storefront services a running rate deal" bullet);
        `openspec/specs/compute-delivery/architecture.md`, "Commit and hold adoption"
        (the `rate_servicing_unavailable` repair reason). Also describing the removed
        refusal, found by section 2's fresh-context check: `docs/development/ARCHITECTURE.md`,
        "Settlement servicing"; `openspec/specs/settlement-servicing/architecture.md`,
        "Charge-first payment settlement" and "Current limits";
        `openspec/specs/settlement-servicing/configuration.md`, "Seller servicing budget
        diagnostics"; `openspec/specs/settlement-configuration/configuration.md`,
        "Settlement consumer configuration and cutover";
        `openspec/specs/storefront-publication/architecture.md`, "The servicing
        declaration and its three doors".
      - D2, D3: `deal-lifecycle/architecture.md`, "One end instant, transactional
        admission" (payment-stop classification and the `terms` split).
      - D4, D6: `deal-lifecycle/architecture.md`, "Package and counterpart boundaries"
        (the kit's servicing order, respondent port and page position) and "Current
        limits" (the respondent-lifetime and term-end bullet removed, and its "account
        discovery continues"); "Buyer surrender and cases" ("advancing its account
        cursor": the respondent cursor is the authority's, found by section 6's
        fresh-context check);
        `openspec/specs/vm-storefront-fulfillment/architecture.md`, "Evidence and delivery
        ownership" (its respondent-poller sentence, and its term-end sentences — bare metal
        recording term ends while VM relies on site expiry — found by section 7's
        fresh-context check);
        `openspec/specs/settlement-servicing/architecture.md`, "Current limits" (its
        respondent and term-end clause).
      - D5: `compute-delivery/architecture.md`, "Dispatch and recovery", "The Agreement
        window and the future-start wait" ("VM's periodic resume pass, bare metal's
        lifecycle cycle") and "Domain compositions" (the shared re-drive and its ports;
        the table's VM entry, which names the resume pass among the hook's callers
        though it drives through `drive_vm_delivery`, bare metal's entry, whose callers
        now include the re-drive, and both recovery-worker rows);
        `openspec/specs/physical-provisioning/architecture.md`, its sentence naming
        payment settle and the Alkahest ready step as the callers that build a
        `StorefrontFulfillmentContext` (the re-drive's `redeliver` is one more) and "The
        lifecycle cycle drives waiting and pending deals" (now the re-drive's, through
        `deliver`), found by section 8's fresh-context checks;
        `openspec/specs/vm-storefront-fulfillment/architecture.md`, "Evidence and
        delivery ownership" (its "periodic resume pass", now the `delivery-recovery`
        loop) and `docs/development/TESTING.md`'s "dispatched only by a resume-pass
        step", found by section 9's fresh-context check;
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
        lane time). Also describing the recurring purchase as refused, found by
        section 2B's fresh-context check: `openspec/specs/test-compatibility/architecture.md`,
        "The in-lane payments double" ("no lane delivers a rate deal yet") and
        "Ordinary Arkhai purchase evidence" (the recurring purchase "through commit
        and no further", its balance restored).
      - D12: the `settlement-servicing` spec, by the archive.
      - D13: `openspec/specs/buyer-orchestration/architecture.md`, "Compute terms before
        approval" (the penalty bound) and "The buyer's watchdog" (the funding-stop exit),
        beside the spec by the archive.
      - D14: the `buyer-orchestration` spec, by the archive;
        `openspec/specs/test-compatibility/architecture.md`, "Lifecycle contract evidence"
        (restart recovery's evidence).
      - D15: no permanent destination.
      - D16: the `deal-lifecycle` spec, by the archive;
        `deal-lifecycle/architecture.md`, "One end instant, transactional admission"
        (*ended*'s dispute half: the authority's first-page `404` read as no case, its
        unchecked premise and its limit); `openspec/specs/settlement-servicing/architecture.md`,
        "Charge-first payment settlement" (its "Initial missing mediation history permits
        the first filing only" sentence); `kit/arkhai-mediation/README.md`, "Composition"
        (its initial-`404` paragraph, "not a verified empty history for ordinary reads"),
        already rewritten with the code in 9A.1.
      - D17: the `test-compatibility` spec, by the archive;
        `openspec/specs/test-compatibility/architecture.md`, "The in-lane payments double"
        and "Lane time and the doubles' controls" (the reservation control);
        `docs/development/TESTING.md`, "Private Service Dependencies" (the doubles'
        controls paragraph); `kit/arkhai-payments/README.md`, "Installed contract and
        authority fixture" (the reservation method beside `advance`), already written
        with the code in 9B.1; the double's and the controls' READMEs, written in 9B.4.
      - D18, D19: `docs/development/TESTING.md`, "The canonical compute deal" (the
        watchdog cases with the storefront paused; the rate rows and watchdog cases as
        Compose-lane, lane-double evidence), beside the `test-compatibility` spec by the
        archive.
      - D20 (75 F5): the `test-compatibility` spec, by the archive;
        `docs/development/TESTING.md`, "The canonical compute deal" (the watchdog cases
        running the shipped `buy` in the harness's process, its probe and every wait it
        makes programmed); `e2e-tests/README.md` (the watchdog modules);
        `e2e-tests/tests/e2e/roles/buyer_cli.py` (its note naming the in-process watchdog
        cases as the exception and why); `openspec/specs/buyer-orchestration/architecture.md`,
        "The buyer's watchdog" (VM's commit and settlement waits on the command's wait
        clock; bare metal's probe built from the access its caller read).
      - The owner's principles: `docs/guidance/workflow/changes.md`, "Defects found during
        a change" (a change taking on another change's work names the move in its proposal
        and that change's row Notes); `docs/guidance/repository/package-versions.md`,
        "Compatibility is owed to what a release has shipped" (a released client is not
        owed compatibility with a later storefront; the staged deprecation pattern stays
        available); `docs/guidance/engineering/test-doubles.md`, "A double mirrors its
        producer" (a producer's scheduled actions, such as reserving ahead, are answers a
        scenario programs; a double gains no internal behaviour a scenario could
        program); `docs/guidance/repository/deterministic-tests.md`, "Pause the loop, then
        advance it explicitly" (a local end-to-end test holds a party's time-based signals
        by pausing it, never by stopping it; external-topology tests handle time
        differently); `docs/guidance/engineering/system-tests.md`, "A system test reaches
        services only through their interfaces", as a qualification of that rule (a CLI
        used by an end-to-end test is controlled by the principles applied to services, a
        mock layer overriding its outbound IO and time, applied in the harness's process
        so no test functionality ships with the CLI; D20, 75 F4).
      Run `make check-spec-index CHANGE=serve-running-rate-deals`; no touched capability
      has an `index.md`, and `openspec/specs/README.md` needs no row.
      Done: every document above written, each checked against the code; the
      design-promotion record in `design.md` names each decision's sections. Where the
      code differs from the design's words the documents follow the code: the startup
      report shows in system status (`unserviceable_deals`), not a readiness report;
      bare metal's claim port answers whether its lock is free, the hook taking it;
      bare metal's new interval keys default to `payment_reconciliation_interval`.
      Beyond the list, found while promoting: `compute-delivery/spec.md`'s "Delivery is
      driven one deal at a time and reports where it stands", which no delta touches,
      lost `rate_servicing_unavailable` from its reasons by hand; the
      `tools/mediation-lane-double/README.md` sentence saying no lane runs a rate part;
      the deal-lifecycle companion's payments-adapter row (once and rate parts) and its
      "not a verified empty ordinary read"; `TESTING.md`'s and the buyer companion's
      lane-time passages on the in-process buyer; the mediation-double paragraph of the
      test-compatibility companion; the composition root wording in storefront
      publication's declaration section. The deal-lifecycle "Current limits" bullet on
      rate servicing keeps its still-true limits (no funding timer, later qualification)
      without the refusal. `make check-spec-index CHANGE=serve-running-rate-deals`
      passed; no touched capability has an `index.md`.
- [x] 12.10 Guidance placement: read the five guidance paragraphs promoted in 12.9 against
      the layer test — `test-doubles.md`'s and `system-tests.md`'s in the engineering
      layer, the other three in the repository's and the workflow's — then run
      `make check-guidance`.
      Done: `test-doubles.md`'s scheduled-actions paragraph and `system-tests.md`'s CLI
      paragraph hold without this repository or the workflow, each with a neutral
      example (a billing service's renewal; a command's composition factories);
      `deterministic-tests.md`'s pause rule and `package-versions.md`'s client rule name
      this repository's storefronts, lanes and CLIs, so are repository guidance spanning
      its systems; `changes.md`'s rule is about change records, so workflow. The change's
      earlier guidance edits (`deterministic-tests.md`'s loop table,
      `published-packages.md`, `test-placement.md`) stay in the repository layer they
      describe. No exception was added. `make check-guidance` passed.
- [x] 12.11 Documentation citations: run `make check-doc-citations
      CHANGE=serve-running-rate-deals` and resolve every match, then
      `scripts/change-workflow openspec validate serve-running-rate-deals --strict`.
      Done: `make check-doc-citations CHANGE=serve-running-rate-deals` passed (every
      cited path resolves); the strict validation reports the change valid.
- [x] 12.12 Archival: `scripts/change-workflow openspec archive serve-running-rate-deals
      -y`, merging the deltas into `deal-lifecycle`, `compute-delivery`,
      `market-composition`, `settlement-servicing`, `buyer-orchestration` and
      `test-compatibility`; the index row then links the archive directory.
      Done: no permanent spec held a delta's requirement beforehand, so the deltas
      merged (no `--skip-specs`); archived as
      `openspec/changes/archive/2026-11-18-serve-running-rate-deals/` (+12 added, ~6
      modified, −4 removed across the six specs). Each changed requirement appears
      once in its `spec.md`, the modified ones in place, and nothing else changed but
      `compute-delivery/spec.md`'s hand-edited reason list (12.9). The index row links
      the archive directory; its status stays `in closeout` for archive cleanup.
