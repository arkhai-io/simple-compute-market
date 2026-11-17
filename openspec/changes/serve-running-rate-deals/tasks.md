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
      dump every field; contracts 0.3.0. Beyond the plan, a `DealSummary` validator
      lists each code once and only while the state is `ending`, as the delta's "ended
      with no `ending`" reads. Unit (`test_models.py`, 54 passed with the suite): a
      once-only summary dumps every field, `parts` and `ending` empty; a rate summary
      with a requested stop dumps every field, its part every observation field with a
      null `final_stop`, and its request every event field with a null
      `settles_through`; an `AuthorityView` dumps an empty `parts` and a once-only
      event's null `settles_through`; an unknown code, a code outside `ending` and a
      repeated code are refused; every code has non-blank text. Stored servicing views
      and journal rows written before this release omit those fields; they read back
      with their defaults, and every comparison in `kit/deal-servicing` is between
      parsed models, so none is affected. `kit/deal-servicing`, which serves the read
      and list, raises its contracts bound in section 2, which bumps it anyway.
- [x] 1.2 Replace `tests/unit/test_released_reads.py` and `released_0_1_0.py` with a test
      that this release's models read once-only, rate, ending and ended reads and pages
      as the storefront dumps them (D7). Verify (unit): the new test passes, and no test
      validates against the 0.1.0 models.
      Done: `tests/unit/test_shipped_reads.py` serializes each read and page as a
      storefront's lifecycle route does (`canonical_json` of the model's JSON dump,
      re-implemented in the test, since the contracts cannot import the route), decodes
      it, and validates it back to the same model as the seller client does, for a
      once-only, rate, ending and ended read and page (unit, passed). It is a round
      trip, and would pass at the base too, where the omission was restored on read;
      that every field is dumped is `test_models.py`'s evidence. Both 0.1.0 files are
      removed; no test in the repository names them.
- [x] 1.3 `kit/deal-lifecycle-client`: raise its contracts bound, and expose each listed
      deal's `ending` codes with their text through `SellerLifecycleClient.list` and its
      sync variant, so a caller renders the text without interpreting codes (D7). Verify
      (unit, `kit/deal-lifecycle-client/tests/test_client.py`): a page with an ending
      deal yields its codes and their text.
      Done, differing from the plan in where the text is joined: `DealSummary` carries an
      `ending_reasons` property (each code with its `ENDING_TEXT`), not serialized, so
      every reader of the contracts — this client, the storefronts, any CLI — renders the
      same words and the client needed no wrapper type. The client takes contracts
      `>=0.3.0` and version 0.2.0; its README names `ending` and `ending_reasons`. Unit
      (`test_client.py`, 3 passed): over a mocked transport returning a decoded page
      with an ending deal, both `SyncSellerLifecycleClient.list` and
      `SellerLifecycleClient.list` send the list route's method and path, the
      administrator role, the operation and the request's resource and parameters, and
      return a page whose deal yields its codes and their text. The package's tests stay
      flat in `tests/`, the path the plan names, rather than `tests/unit/`; moving its
      one module is left out of this section.
- [x] 1.4 Verification point: `kit/deal-lifecycle-contracts` and
      `kit/deal-lifecycle-client` suites (unit) pass; `make check-packaging` passes.
      End-to-end: no scenario asserts the new field yet; every scenario reading a seller
      lifecycle read through the typed client (`e2e_vm_recurring_purchase`,
      `e2e_bare_metal_recurring_purchase`, the `e2e_vm_dispute_*` scenarios) is pipeline
      evidence that the shipped client reads the new shapes.
      Done: both suites pass (unit); `make check-packaging` and `make test` pass in
      `scripts/change-workflow run pre-commit`, after `make lock` moved every lock to
      contracts 0.3.0 and client 0.2.0. End-to-end corrected: no scenario asserts
      `ending`, and none calls the seller client's `read` or `list`, so the list's new
      shape has no pipeline evidence. The VM scenarios named read the buyer lifecycle
      route through the buyer `LifecycleClient`, and the bare-metal scenario validates
      the read with `LifecycleRead` itself; they are pipeline evidence that this
      release's models read the `LifecycleRead` a storefront of the release serves.
      `scripts/change-workflow run test-before` cannot show the new unit tests failing at
      the base, since it runs without the package's environment (no pydantic); the
      `test_models.py` and `test_client.py` cases name `ENDING_TEXT`, `EndingCode`,
      `ending` or `ending_reasons`, which only this section adds, and the
      `test_shipped_reads.py` round trips would pass at the base.

## 2. End service asks the adapter for every deal, holds changed answers, and lists *ended* truly

Replanned against the reviewed design after implementation returned the change to
planning (its handoff below): this section is now the kit and compute-delivery slice,
tasks 2.1–2.4. The storefronts' rate-delivery evidence is section 2A, and the lane
scenarios that were 2.5 are section 2B. 2.5's text is kept for history and is not
implemented here.

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
      Done: `_unserviceable` and its call are gone; a phase whose authorization at this
      revision is `done` and whose new answer differs by status returns `pending` naming
      both answers, with nothing journaled. Answers compare by status alone, since a rate
      adapter's evidence references name each fresh snapshot. An end due by now at the
      same revision is admission's own `refuse`, returned unjournaled rather than held
      as a changed answer. `DeliveryAuthorization.code` and `RefusalCode` are removed,
      with `kit/deal-lifecycle/tests/unit/test_delivery_authorization.py`, which tested
      only the code's omission. Library integration (`test_changed_answer.py`, replacing
      `test_rate_refusal.py`): a rate commit asks the adapter and journals its allow;
      `allow` then `pending` and `allow` then `refuse` return `pending` with the journal
      unchanged and nothing raised, and a later identical `allow` proceeds; once a
      recorded end moves the revision admission answers ended; an end due at the same
      revision is admission's answer; a once-only deal's unchanged answer reads the
      journal as before. `test_deadline_barrier.py` keeps its three scenarios on an
      undelivered rate deal. `kit/deal-lifecycle` 0.5.0, `kit/deal-servicing` 0.4.0
      (contracts `>=0.3.0`); `kit/deal-servicing` 114 passed, `kit/deal-lifecycle` 82
      passed.
- [x] 2.2 `domains/compute/delivery/src/compute_delivery/path.py` and `outcome.py`: remove
      `RepairReason.RATE_SERVICING_UNAVAILABLE` and the code branch in `_authorized`;
      every refusal with no end due is `repair_required(no_accepted_deal)`. Verify
      (library integration, `domains/compute/delivery/tests/integration/test_drive_delivery.py`,
      where the refused-rate cases are — corrected from `test_drive_commit.py`): the
      refused-rate cases are replaced by a rate deal that commits and is delivered, a
      changed answer while it waits for its start leaving the drive pending, and an
      undelivered rate deal past its deadline.
      Done: the reason and its branch are gone; a refusal with no end due is
      `repair_required(no_accepted_deal)`. Library integration (`test_drive_delivery.py`,
      130 passed with the suite): a rate deal commits and is delivered; a changed answer
      while it waits for its start leaves the drive pending; an undelivered rate deal past
      its deadline waits for a payment observation; one first driven past its deadline is
      pending with nothing begun. `domains/compute/delivery` 0.2.0.
- [x] 2.3 `kit/deal-servicing/src/market_deal_servicing/seller.py`, `_list`: a deal with a
      selected end is `ended` only when `progress == "released"`, every part in the
      authority view has a `final_stop` or an `end_at` at or before now, and no case is
      open; otherwise `ending`, with `ending` naming each outstanding code (D7). Verify
      (library integration, `test_watch_and_seller.py`): a released rate deal whose part
      still runs is `ending` with `payment_running`; tearing down with an open case gives
      `release_pending` and `case_open`; all clear gives `ended` with no codes; a case
      filed after `ended` returns `ending`.
      Done: `_list` computes the outstanding codes in `_outstanding`; a repair-required
      deal lists no codes. Library integration (`test_watch_and_seller.py`, through
      `SellerServicing.list`): a released rate deal whose part still runs is `ending`
      with `payment_running`, and `ended` with no codes once one part has a final stop and
      the other an `end_at` by now; a deal torn down with a filed case is `ending` with
      `release_pending` and `case_open`, `ended` once the case closes and the resource is
      released, and `ending` with `case_open` when a later case is filed. The kit README
      names the codes.
- [x] 2.4 Verify D12 (library integration, `test_final_stop.py`): after the watch records a
      rate part's final stop, the servicing tables hold the stop and the selected end and
      no balance, funded amount or amount owed.
      Done: with the authority's view carrying a collection amount and a funded boundary,
      the watch records the stop as the selected end, and no `servicing_` table has a
      money-named column and no journaled request, intent or delivery record a money-named
      key (library integration, passed). Narrower than the task reads in two ways: the
      watch's stored observation views (`servicing_watch`, `servicing_observations`) keep
      the authority's view as read, its amount and funded boundary included, which D12's
      requirement admits as a journaled observation, so the check leaves them out; and
      the deal is the rig's once-only registration with a rate-shaped part (a
      `funded_through` and a payer stop), not a deal registered as rate.
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
      Done through section 2B, which carries this task resized (2B.1–2B.3); checked
      so section 2 reads complete, and its text is history.
- [x] 2.6 Verification point: `kit/deal-lifecycle`, `kit/deal-servicing` and
      `domains/compute/delivery` suites (unit, library integration) pass. The storefronts'
      suites are section 2A's verification point, which this section's work leaves
      failing four tests in each storefront until 2A rewrites them. End-to-end: none at
      this level; section 2B carries the recurring purchases.
      Done: `kit/deal-servicing` (114), `kit/deal-lifecycle` (82) and
      `domains/compute/delivery` (130) pass, unit and library integration, at the work in
      progress committed before the replan; this section commits only its task notes, so
      `scripts/change-workflow run pre-commit` runs its inert-path checks, and the
      functional hooks, every suite with them, run at 2A's commit, once the storefront
      suites pass. End-to-end confirmed: no scenario exercises this section alone; the
      recurring purchases (section 2B) are its pipeline evidence. Owed by validation:
      none.
      Fresh-context check: it found the 2.4 note broader than its test (corrected above);
      permanent documents describing the removed refusal missing from 12.9 (added to its
      D1 entry); and comments left false by the refusal's removal, outside the plan —
      `domains/bare_metal/storefront/storefront.dev.toml` and
      `domains/vms/storefront/storefront.bob.lane.toml` (fixed with section 2A's commit,
      which runs the functional hooks), `domains/compute/delivery/pyproject.toml`'s
      version-history comment on its servicing bound (fixed with 2A), and
      `e2e-tests/tests/e2e/roles/scenarios/bare_metal/purchase_driver.py`'s docstring and
      `e2e-tests/README.md`'s recurring-purchase paragraph (section 2B, which rewrites
      that scenario). Declined: the citation in `journal.py` of the delta's heading, which
      holds once the archive merges it; a stronger assertion in the undelivered-deadline
      case of `test_drive_delivery.py`, whose later `ended` already shows the barrier;
      and the "as before" test name, the delta scenario's own words.

Section 2 handoff, kept as history: written when the work in progress was returned to
planning, before the replan; tasks 2.1–2.4 and 2.6 were checked afterwards against that
committed work.

- Done in the worktree, suites passing: 2.1's end service (`_unserviceable` gone; a changed
  answer at a revision whose phase is `done` returns `pending`, compared by status alone,
  since a rate adapter's evidence references name each fresh snapshot; an end due by now
  at the same revision is admission's own `refuse`, returned unjournaled rather than held
  as a changed answer), `DeliveryAuthorization.code` and `RefusalCode` removed with
  `kit/deal-lifecycle/tests/unit/test_delivery_authorization.py`, the journal docstring,
  `test_changed_answer.py` replacing `test_rate_refusal.py`, `test_deadline_barrier.py`'s
  refused setups rewritten; 2.2's `RATE_SERVICING_UNAVAILABLE` and its branch removed, the
  refused-rate cases replaced in `test_drive_delivery.py` (where they were, not
  `test_drive_commit.py` as the plan says) by a rate deal that commits and is delivered, a
  changed answer while it waits for its start leaving the drive pending, and an
  undelivered rate deal past its deadline; 2.3's `_list` with `ending` codes and its two
  tests; 2.4's journal test in `test_final_stop.py`; the kit README. Versions:
  `kit/deal-lifecycle` 0.5.0, `kit/deal-servicing` 0.4.0 (contracts `>=0.3.0`),
  `domains/compute/delivery` 0.2.0, both storefronts 0.29.0 with their bounds raised and
  VM's exact pin on bare metal moved; `make lock` run. `kit/deal-servicing` (114),
  `kit/deal-lifecycle` (82) and `domains/compute/delivery` (130) pass.
- Found larger than planned: both storefront suites fail four tests the plan does not
  name, each asserting the removed refusal: `tests/integration/test_rate_delivery_refusal.py`
  (three tests) and `tests/integration/test_watchdog_buy.py::test_a_watched_purchase_whose_commit_is_refused_is_never_watched`,
  in each storefront. Neither storefront's recurring test world can deliver a deal once
  the commit is allowed. In VM's (`tests/recurring_world.py`, `settlement`), placement
  ends `capacity_unavailable`, and the end hand-off's and failure policy's capacity
  runtime raises "No capacity site authority configured". In bare metal's, settle answers
  500 because the world's `_OneSite` capacity client has no `site_names`
  (`fulfillment_service.py`, `fulfill_bare_metal`); what its dispatch then needs is unknown.
  The three deadline-recovery tests in each file are the storefronts' evidence for the
  deadline barrier's scenarios on an undelivered rate deal, which the delta keeps.
- Not started: 2.5's lane stages (the recurring purchases' stages and drivers, and
  `e2e-tests/tests/unit/test_recurring_purchase_stages.py`'s order) and its lane runs.
- The owner returned the change to planning, so the plan can give the storefront
  recurring test worlds' rework (each world delivering a rate deal, and the four tests in
  each storefront rewritten as delivered-deal and undelivered-deadline evidence) a section
  of its own and resize 2.5. The work above is committed as a work in progress, its
  storefront suites failing those four tests in each storefront, and no task is checked.

Round 1 triage fix, 32 F1 (`reviews/32-implementation.triage.md`): the seller list's
`_outstanding` takes the deal and counts a deal that is not once-only, whose saved
payment view lists no part or that has none, as `payment_running`, so a released rate
deal is never `ended` before the payment authority is seen (D7's settled note). Library
integration, `kit/deal-servicing/tests/integration/test_watch_and_seller.py`: a released
rate deal never observed, then observed with no parts, lists `ending
["payment_running"]`; a released once-only deal never observed lists `ended`. A rate
deal ended before its part ever started stays `payment_running` until that part's
terms end, as the requirement's words ask.

Round 1 repeat-pass triage fix, 44 F1 (`reviews/44-implementation.triage.md`): the
dispute half of the list's rule. A deal naming a dispute authority of which no verified
read is saved has its cases unknown, so `_outstanding` names a fourth code,
`case_unobserved`, and neither the list nor `unserviceable()` calls it ended until one
read is saved (D7's second settled note). `_observed` reads the authority view and
whether the dispute view is missing in one transaction, so a view saved meanwhile
cannot leave them disagreeing. `kit/deal-lifecycle-contracts` 0.3.0 gains the code and
its text; the delta's closed list and a scenario, and the kit README, name it. The
32 F1 note's released once-only deal now lists `ending ["case_unobserved"]` until its
dispute authority is read. Library integration, `test_watch_and_seller.py`: a released
once-only deal lists `ending ["case_unobserved"]`, `repair_required` without its
credential, still `case_unobserved` after a failed read, and `ended` after one verified
empty read; a deal naming no dispute authority is `ended` with no read; the
missing-adapter report keeps a released deal until its dispute authority is read;
the never-observed rate deal names `payment_running` and `case_unobserved`. Unit,
contracts: the served-page shapes include an ending deal with `case_unobserved`.
Evidence:
- library integration, `make test-kits`: `kit/deal-servicing` 134 passed,
  `kit/deal-lifecycle-contracts` 55 passed, `kit/deal-lifecycle-client` 3 passed, every
  other kit suite passed;
- `scripts/change-workflow run pre-commit`: `after-functional-change … passed, exit 0`,
  `pre-commit-functional … passed, exit 0` (among them the VM storefront 1197 passed,
  1 skipped and 623 passed, bare metal 663 passed, the e2e unit suite 911 passed,
  1 skipped, the release tooling 3123 passed), `pre-commit … passed, exit 0`;
- `run test-before` not run: it runs a test file as `HEAD` holds it, and the changed
  file is uncommitted until this commit; at the commit before, the rewritten once-only
  case's first assertion reads `ended`, the defect the review showed;
- fresh-context check: no correctness defect beyond a race between the authority read
  and a separate dispute-view read, fixed by reading both in one transaction
  (`_observed`); fixed the `unserviceable()` docstring (a dispute read, not the payment
  adapter, clears an unobserved deal), the delta scenario's wording ("verified read …
  saved"), the README's reflow, and a missing `repair_required` assertion; noted for
  section 10.1 that a lane deal's `ended` needs one saved dispute read; declined
  rewording D7's opening paragraph, which its settled notes amend, as 32 F1's did.

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
      Done, differing from the plan in which site: the world's site for delivery is
      `tests.delivery_fakes.DeliverySite`, the fake `test_vm_delivery_path.py` already
      delivers against, composed as the one site of a real `CapacityRuntime`
      (`delivery_capacity`, resolving the publication harness's `SITE`) whose site client
      factory returns it; the publication harness's `FakeSite` serves projections only and
      has no activation route. The coordinator takes that runtime's effects, and the
      lifecycle's end service has its physical collaborator replaced after construction
      by a `VmPhysicalEnd` over the same runtime and provisioning
      (`lifecycle.end.physical`, as `test_payment_settlement.py`,
      `test_lifecycle_failures.py` and `test_lifecycle_admin.py` replace it; `VmDealLifecycle`
      takes no constructor parameter for it), so the end hand-off reaches the world's
      site instead of building a runtime from the storefront's configured sites. The
      failure policy still builds its own runtime; no 2A case fails a delivery, so none
      reaches it. `DeliverySite` gains `list_reservations`, filtered by state and escrow
      as the site client's is, which `VmPhysicalEnd` reads, and an `unreachable` switch, a
      reserve failing before its effect. Application integration
      (`test_rate_delivery.py`, the case named below in 2A.3): a settled recurring deal's
      commit is allowed, its reservation committed and activated at the site, billing
      journaled once naming that activation, the payments engine holding the started rate
      (one `submit_event`), and the deal available no earlier than the activation; passed.
- [x] 2A.2 Bare metal: give `domains/bare_metal/storefront/tests/recurring_world.py`'s
      `_OneSite` capacity client what `fulfillment_service.py`'s `fulfill_bare_metal` needs
      (`site_names`, then whatever its dispatch needs, found by running it), so settle no
      longer answers 500 and a committed recurring deal reaches activation, the payments
      fake's rate `start` and availability. Verify (application integration): as 2A.1, in
      bare metal.
      Done: `_OneSite` became `WorldSite`, a subclass of `test_http_settlement.py`'s
      `_CapacityClient` (site names, reserve, commit, activation) that still serves the
      projection site to the pool overrides and has the same `unreachable` switch. What
      dispatch needed, found by running it, was a fulfillment client: the world's runtime
      had `object()`. It now has `WorldProvisioning`, a subclass of `_ProvisioningClient`
      scheduling the pool member's machine (`machine-r1`, `physical-r1`) in the world's
      pool (`pool-1`), since delivery refuses a scheduled resource whose pool or host
      differs. `RecurringWorld` exposes both as `capacity` and `provisioning`. Application
      integration (`test_rate_delivery.py`): as 2A.1, with the reservation committed and
      activated, fulfillment begun once, billing naming the activation, one
      `submit_event`, and the deal available; passed. The lifecycle row's `state` keeps
      the provisioning state recorded at dispatch until a status read refreshes it, so the
      case asserts availability from end service, not that column.
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
      three — a buyer's stop while the storefront was down winning over the deadline, and
      recovery after the deadline recording seller non-delivery (the deadline admitted
      after the payment observation). Both are kept on a rate deal left undelivered by an
      unreachable site (`unreachable`: a reserve fails before its effect, which the path
      leaves pending), whose commit is allowed and journaled and nothing placed — VM
      asserts the site holds no reservation, bare metal that the site recorded no
      reservation or commit and provisioning began nothing. The third scenario the plan
      names, the delta's "The payment authority is unreadable at the deadline", existed
      only in the kit's `test_deadline_barrier.py`; each file adds it whole: with the
      payments service unavailable at recovery past the deadline, the cycle asks the
      authority (a further `get_transaction`, failing) and journals no end request and no
      filing intent, and once the authority is readable the next recovery records seller
      non-delivery at the deadline with its one filing. In each storefront
      `test_rate_delivery.py` (the delivered case of 2A.1/2A.2 and the three deadline
      cases) and `test_watchdog_buy.py::test_a_watched_purchase_is_monitored_from_available`
      pass (application integration). The watchdog case runs the production buyer `buy
      --watchdog --watchdog-interval 1 --watchdog-threshold 2` against the served
      storefront; the buy commands' own factories are its seam for the probe and the clock
      (`watchdog_probe` answering `[True, False, False]` from a script, `wait_clock`'s
      waits returning at once). The watchdog states its bound, probes, journals its last
      probe and, after two failures, its stop resting on them, which the payments engine
      accepts (two `submit_event` calls in all; VM's shows the rate start's before the
      resumed run and the stop's after it, bare metal's only the total), and the buyer's
      read shows it `stopped`. In bare metal the buy's availability wait, in fake time, answers
      `available` before the CLI builds the probe, as its output shows. VM's buy CLI polls
      the settle status in real time with no clock seam, so its case does not let it wait:
      the buy runs with the site unreachable and `--settlement-timeout 0`, reads the
      status once and exits 4 with the opt-in journaled and nothing probed; the test then
      re-settles through the
      typed client with the site answering, waits on that delivery task, checks the deal
      available and billed, and resumes the run (`buy --from`, timeout 0), which reads it
      ready and re-enters the watchdog. VM's checks that the probe was built from the
      endpoint the delivery disclosed (`203.0.113.10:2222`); bare metal's factory is given
      the run, its own input.
- [x] 2A.4 Verification point: both storefronts' suites (application integration) pass,
      among them `test_rate_delivery.py`, `test_watchdog_buy.py` and the
      `test_lifecycle_*.py` modules; `scripts/change-workflow run pre-commit` passes.
      End-to-end: section 2B.
      Done: `make -C domains/vms/storefront test` (unit 1194 passed, 1 skipped;
      integration passed) and `make -C domains/bare_metal/storefront test` (passed), and
      `scripts/change-workflow run pre-commit` passed with every functional hook. End-to-end,
      corrected: no scenario is evidence for this section until section 2B rewrites the
      recurring purchases' stages to assert delivery; until then they assert the refusal
      and fail in the lanes. Owed by validation: none. Also in this commit, outside the plan and found by section 2's
      fresh-context check: the comments in `domains/bare_metal/storefront/storefront.dev.toml`
      and `domains/vms/storefront/storefront.bob.lane.toml` saying end service refuses
      to commit a rate deal, and `domains/compute/delivery/pyproject.toml`'s
      version-history comment on its servicing bound, now describe the current system.
      `scripts/change-workflow run test-before` was not run: it runs without the
      storefronts' environments, so the rewritten modules would fail at collection there,
      showing nothing. At the round's base end service refused the commit the delivered
      cases assert allowed, which is the reasoning, not a run, that they fail there.
      Fresh-context check: fixed — VM's watchdog case waited on real-time settle polls
      (now the resume flow above); the unreadable-authority cases covered only the first
      half of their scenario; "a site that answers no reservation" described the
      opposite path outcome (it is an unreachable site); `DeliverySite`'s docstring said
      the unreachable site answers nothing, where only a reserve fails;
      `list_reservations` took none of the site client's filters; the watchdog comments
      claimed the first probe was journaled; bare metal's undelivered helper asserted
      nothing at the site; and these notes' overstatements. Declined: the two lane
      configurations' comments saying the lane delivers a per-period Agreement before a
      lane run shows it — they describe what the configuration admits, which the code now
      delivers, and section 2B runs the lanes; `TESTING.md`'s recurring-purchase
      paragraph is 12.9's. A second check after those fixes found no determinism or
      comment break; it asked for the unreadable-authority cases to show the cycle read
      the authority, the VM watchdog case to assert the opt-in after the first buy, two
      note phrasings narrowed, and the two seam gaps recorded as deferred work, all done.

Section 2A handoff:

- The worlds sections 3.3 and 9.3 build on: VM's `settlement(world)` yields `site` (the
  `DeliverySite` delivery and the physical end share) beside `provisioning`; bare metal's
  `RecurringWorld` carries `capacity` (`WorldSite`) and `provisioning`
  (`WorldProvisioning`). Each `recurring_world`/`settlement` builds fresh fakes, so a
  restarted storefront meets a site holding no reservation; a test needing the site to
  outlive a restart must pass it in, which neither world takes yet.
- VM's failure policy (`market_storefront.failure_actions`) still builds its capacity
  runtime from the storefront's configured sites, so a VM case that fails a delivered
  rate deal (3.3's provisioning failure after a buyer stop) reaches "No capacity site
  authority configured" in the policy unless the world supplies that runtime too; the
  end hand-off itself already reaches the world's site.
- VM's buy CLI waits for settlement with `time.sleep` (`core_buyer.orchestration`'s
  `wait_for_settlement`, reached with no sleep seam from `arkhai_payments.py`), so a VM
  buy case cannot wait for delivery in fake time; bare metal's `wait_clock` covers its
  waits. This gap, and `VmDealLifecycle` taking no physical-end or failure-policy
  capacity collaborator, are rows under "Unowned work found by
  `serve-running-rate-deals`" in `openspec/changes/README.md`.
- The second fresh-context check also noted that no 2A case asserts D1's held answer
  itself (the journaled commit `allow` unchanged while a later drive answers
  `pending`); that is section 2's library-integration evidence
  (`test_changed_answer.py`), and 2A's cases show only delivery and the deadline
  barrier through the application.
- In bare metal, the lifecycle row's `state` is provisioning's state as last read; the
  settle-driven delivery leaves it `dispatch_pending` while end service records the deal
  available.

Round 1 triage fix, 34 O1's U2 (`reviews/34-implementation-owner.triage.md`), outside
the plan: `VmDealLifecycle` takes `capacity=` (a capacity runtime) and `physical=`; its
end service's physical end is built over its capacity and fulfillment, its site-report
recovery's fulfillment client over its capacity, and the release failure action
(`failure_actions._release_capacity`) uses the composition lifecycle's runtime before
building one. The composition root passes neither, so production keeps the configured
sites' cached runtime. `tests/recurring_world.py`, `test_payment_settlement.py` (its
harness's `physical=` factory), `test_lifecycle_failures.py`, `test_lifecycle_admin.py`,
`test_lifecycle_cycle.py`, `test_fulfillment_resume_runtime.py` and
`examples/payment_smoke.py` construct with them rather than replacing
`lifecycle.end.physical`. New unit case `test_failure_policy.py::
test_the_release_uses_the_deal_lifecycles_capacity_runtime`. The unowned row is removed.

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
      Done, more than the refusal's removal, as the handoff below found: each module
      now composes the payment purchase's delivery and teardown stages. Order:
      readiness and the domain's listing; `Purchase01`, `Purchase02`, `Stage07a`,
      `Purchase03`, `Purchase04`, `Stage08b2`, `Recurring04_MandateApproved` (now
      checking `Purchase04`'s correlation rather than re-correlating, and read before
      `Stage09a` so before delivery can start the rate part); `Stage09a`, the domain's
      `Stage09a2` (VM's capacity-event step, bare metal's `BareMetalPublicationClosesListing`,
      which `Stage09b` requires and the handoff did not name), `Stage09b`, `Stage09c`;
      `Recurring05_RateStartedAfterActivation` (one servicing step, then the double's
      part `started` and its one start event no earlier than the lease's
      `activated_at_utc`, to the whole second, and the lifecycle read `active` with no
      end or filing), `Purchase09`, `Recurring06_AcceptedMoneyShown` (the stderr check
      on the ended run); `Stage09c2`, `Recurring07_BuyerEnds` (the buyer's `end`; the
      part stopped by the payer with `partialPeriod` `charged`, nothing reserved, and
      held plus released one period's price; the lifecycle read's payer end and no
      filing, read on the hint before any step; one servicing step, still no filing;
      then `Purchase10`'s lease checks — `releasing`,
      `teardown_dispatch_pending`, one convergence advance to `tearing_down`, the
      resource still held), `Stage11a2`, `Stage11b`, `Recurring08_PayerChargedOnePeriod`
      (available down by exactly `PERIOD_GROSS`). `Purchase05` is not run: its debit
      check is a once-only payment's, and `Recurring04` is the rate part's. Each
      module's cleanup opens the gates, stops the buy, ends an unended deal by the
      buyer's stop, removes both mock rules (bare metal also drains provisioning and
      removes the pool override). `close_purchase_run`, `_commit_refused`,
      `RecurringPurchaseDriver.site_capacity` and VM's `FIRST_SETTLEMENT_POLL_SECONDS`
      are gone; the stage module's, both scenario modules', both drivers',
      `e2e-tests/README.md`'s and both `e2e-tests/pyproject.toml` markers'
      recurring-purchase text and `test_buyer_purchase_stages.py`'s docstring
      describe delivery. The unit check's
      handoff reads bare metal's `publication_stages.py` beside the shared stages, as
      `test_compute_deal_stages.py` does, so `Stage09a2`'s write is seen. Unit
      (`make -C e2e-tests test-unit`, 911 passed, 1 skipped), among them
      `test_recurring_purchase_stages.py`'s order and handoff checks for both modules.
- [x] 2B.2 Run both scenarios in their lanes. Verify (system):
      `e2e_vm_recurring_purchase` and `e2e_bare_metal_recurring_purchase` pass, each
      leaving no payment hold, mock rule or held loop.
      Done: `make -C e2e-tests test-e2e-vm E2E_MODULE=e2e_vm_recurring_purchase` (28
      passed) and `make -C e2e-tests test-e2e-bare-metal
      E2E_BARE_METAL_MODULE=e2e_bare_metal_recurring_purchase` (28 passed), system
      level against each lane's Compose stack with mock provisioning and the payments
      double, each run twice (before and after the fresh-context fixes, the second at
      the committed stages) and each stack taken down after. In every run the double
      recorded the rate start in the same whole second as the site's activation
      (second runs: VM activated 16:25:23.70Z, started 1794846323; bare metal
      16:26:54.09Z, 1794846414), so the lane check passed at equality and does not
      show the start followed the activation within that second; that order is each
      storefront's `test_rate_delivery.py` (application integration: billing starts
      from the recorded activation), and section 10's lane time may separate them.
      The payer ended 250000 USD/6 down. Each module's cleanup deleted both mock rules,
      removed the pool override in bare metal, and every hold resumed. "No payment
      hold" — the spec's clean-up rule — is read as nothing reserved for the payer and
      nothing the stages left running: the same requirement demands the started period
      charged, which the double holds for the payee until its release instant (the
      stop asserts held plus released one period), as a once-only purchase's payment
      stays held until the lane ends; the owner may read it otherwise at triage. The
      recorded end is read on the hint, before the servicing step; the lease is read
      `releasing` only after the step, so the lanes do not show which move began the
      teardown (by the code, bare metal's hint drives the physical end and VM's
      lifecycle cycle does).
- [x] 2B.3 Verification point: the `e2e-tests` unit suite and both lane runs pass.
      End-to-end: `e2e_vm_recurring_purchase`, `e2e_bare_metal_recurring_purchase`.
      Done: as 2B.1 and 2B.2. End-to-end confirmed: `e2e_vm_recurring_purchase` and
      `e2e_bare_metal_recurring_purchase`, which validation's pipeline (`make
      run-e2e`) also runs, are evidence for sections 2, 2A and 2B once deployed. Owed by
      validation: none. `scripts/change-workflow run pre-commit` passed with every
      functional hook. `run test-before` was not run: the stage modules are lane
      scenarios, which fail at the round's base only against a stack, where end
      service refused the commit `Recurring05` now asserts delivered.
      Fresh-context check: fixed — the two `e2e-tests/pyproject.toml` marker
      descriptions still describing the refusal; `test-compatibility/architecture.md`'s
      two refusal passages missing from 12.9 (added to its D9 entry); `Recurring07`
      reading the recorded end only after the servicing step, so the hint's effect was
      unmeasured (now read before it); `Recurring07` reading `purchase_run` and
      `payer_account` unnamed to `require_state`; "no earlier than that activation"
      claimed beyond the whole-second check, in the stage, the state field and the
      README; the README reading Recurring05's step as causal; bare metal's cleanup
      docstring omitting its drain; and these notes' timing, hint and hold claims.
      Declined: splitting `Recurring07`, whose end, step and lease checks are one
      ending as `Purchase10` is; sharing `Purchase10`'s lease-check body with it, which
      the handoff planned as a copy and no rule forbids; and `deterministic-tests.md`'s
      bare-metal loop table, which omitted `delivery-recovery` before this change and is
      left to section 9's loop layout (handoff below).

Section 2B handoff:

- The handoff below, written before 2B started, held: the composed stages are the
  ones it names, plus the domain's `Stage09a2`, which `Stage09b` requires. Its
  "`Recurring08`" and stage names are superseded by those in 2B.1's note.
- Section 10 rewrites these modules on lane time. What it keeps: the stage order the
  unit check holds (`EXPECTED_ORDER`), `Recurring04` read before `Stage09a`, and the
  servicing steps in `Recurring05` and `Recurring07`, whose loop becomes
  `deal-servicing` after section 9's rename. The `driver.servicing_loop` names
  (`settlement-servicing` in VM, `delivery-recovery` in bare metal) are the two
  places section 9.2 must rename for these modules.
- `docs/guidance/repository/deterministic-tests.md`'s bare-metal loop table omits
  `delivery-recovery`, which these modules step; section 9's new loop layout is
  where the table is next made current.
- The lanes run in about 15 seconds of stages once images are built; the image build
  dominates. Each lane's stack must come down (`make -C e2e-tests e2e-<lane>-down`)
  before the other's starts: they share host ports.

Section 2B handoff, kept as history (written before 2B started, from reading the
stages after sections 2 and 2A were committed):

- Delivering the recurring deal in a lane is more than the refusal's removal. Every
  compute-lane module holds fulfillment convergence and the lease watchdog
  (`docs/guidance/repository/deterministic-tests.md`), so delivery needs the stages the
  payment purchases already compose (`test_vm_payment_purchase.py`,
  `test_bare_metal_payment_deal.py`): `Stage07a_ArmCreateGate` before `Purchase03_Bought`;
  `Purchase04_PurchaseCorrelated` (it writes the `fulfillment_id`, `expected_host_id` and
  Agreement window the later shared stages require) and `Stage08b2_ReleaseCreateGateAndDrain`
  after it; `Stage09a_FulfillmentConvergesToActive`, `Stage09b_SettlementReadyAndCredentials`
  and `Stage09c_LeaseRecorded`; then `Purchase09_PurchaseRunEnded` in place of the drivers'
  `close_purchase_run`, since the buy now runs to ready (VM's `check_run_ended` expects
  `ready`; bare metal's `agreed`).
- A new recurring stage in place of `Recurring05_CommitRefused` asserts the delivery
  itself: the site's activation, the payments double's rate `start` after it (the
  snapshot's part `started` and its start event), and the lifecycle read's progress.
- The buyer's `end` of a delivered deal ends a lease, so after it the teardown the payment
  purchases stage is needed: `Stage09c2_ArmTeardownGate` before the end,
  `Recurring07_BuyerEnds` carrying `Purchase10_BuyerTeardown`'s lease checks (the lease
  `releasing`, one convergence advance to `tearing_down`) beside its own (the payer's stop
  accepted with `settles_through=started_period`, the seller's read showing the payer's
  end and no filing), then `Stage11a2_ReleaseTeardownGateAndDrain` and
  `Stage11b_TeardownCompletion`. Without them the lane leaves a held mock job and a
  leased resource, which 2B.2's "no mock rule or held loop" forbids.
- `Recurring08` becomes the payer's available balance down by exactly one period's price
  (`PERIOD_GROSS`) from `Purchase01`'s, the reservation's remainder returned.
- Each module's `purchase_cleanup` gains the payment purchase's gate cleanup (open the
  gates, then delete the create and teardown rules) beside `recurring_purchase_cleanup`;
  `VmRecurringPurchaseDriver.close_purchase_run` and its bare-metal twin go;
  `RecurringPurchaseState._commit_refused` goes; `recurring_purchase_stages.py`'s and the
  two modules' docstrings, `purchase_driver.py`'s refusal docstrings, and
  `e2e-tests/README.md`'s recurring-purchase paragraph are rewritten.
- `e2e-tests/tests/unit/test_recurring_purchase_stages.py`'s `EXPECTED_ORDER` takes the
  composed order, and its module docstring ("Nothing is delivered ... no mock gate") is
  rewritten; its `handoff_faults` check will name any field a reused shared stage reads
  that no earlier stage writes.
- 2B.2's lane runs are reachable from an implement session: `make -C e2e-tests
  test-e2e-vm E2E_MODULE=e2e_vm_recurring_purchase` and `make -C e2e-tests
  test-e2e-bare-metal E2E_BARE_METAL_MODULE=e2e_bare_metal_recurring_purchase` match the
  step's `make -C * test*` rule, each building its lane's images and bringing up its
  Compose project, and `make -C e2e-tests e2e-<lane>-down` takes it down. Validation's
  pipeline (`make run-e2e`) also runs both markers.
- Until 2B lands, both recurring purchases fail in their lanes: their `Recurring05`
  asserts the refusal sections 2 and 2A removed.

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
      passed with the module): payer, payee, authority and an early `terms` stop of a deal
      entitling both parties; a payer or payee stop with only the other party entitled,
      and with none, pending; an unknown cause pending; `terms` one second before
      (`exhaustion`), at and after (`terms`) the end. `arkhai-compute` 0.3.0; both
      storefronts take `>=0.3.0`; `make lock` run.
- [x] 3.2 `kit/deal-servicing/src/market_deal_servicing/watch.py`, `_record_payment_stop`:
      when the stop's record exists with a pending classification and the classifier now
      classifies it, resolve it through `EndSession.resolve_correction` at the record's
      revision, lawful and with no filing (D2). Verify (library integration,
      `test_final_stop.py`): a pending stop recorded without a classifier is resolved on a
      later poll with one; the recorded end is unchanged; a resolved one is not resolved
      twice.
      Done: `EndSession.classification(negotiation_id, source_ref)` reads a recorded
      request's slot (`None` while pending); the watch resolves only a pending slot,
      taking the record's revision inside the observation's transaction. A non-lawful
      classification carries its failure filing as at record time (`_failure_filing`,
      shared by both paths); the compute classifier returns only lawful kinds. The kit
      README says so. The rig's watch factory passes keyword options through to
      `DealWatch`. Library integration (`test_final_stop.py`, through `DealWatch.poll`
      against the rig's SQLite): a stop recorded by a watch with no classifier is pending;
      a later poll with one resolves it `entitled_stop`, the request unchanged and no
      filing journaled; a third poll calls the classifier no more and leaves the
      classification and the revision unchanged; a classifier still answering `None`
      leaves the slot and the revision as they were; a pending stop a classifier resolves
      as a seller failure journals its one `delivery_end` filing. `kit/deal-servicing` 117
      passed.
      `run test-before` exits at collection (no `market_deal_lifecycle` in its
      environment), as for section 1; at the base `EndSession.classification` and the
      resolution do not exist.
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
      integration, on each storefront's recurring world (`tests/recurring_world.py`):
      VM (`test_lifecycle_ends.py`, two new cases) — a delivered on-demand deal's payer
      stop, submitted at the payments engine and read by a `settlement-servicing` cycle,
      is recorded `payer` and classified `entitled_stop`; the VM failure policy's
      `release_capacity` (`apply_fulfillment_failure_policy`, given the world's capacity
      runtime, as `test_lifecycle_failures.py` calls it) then records the provisioning
      failure correlated to that stop, classified `entitled_stop`, with no filing; a
      delivered once-only payments deal, the storefront restarted past the Agreement's end
      with the payments engine there, has its payment-stop end recorded `terms` at or
      after the term end and classified `terms`. Bare metal (`test_lifecycle_ends.py`, two
      new cases) — the same payer stop, read by a `delivery-recovery` cycle, is
      `entitled_stop`; bare metal records no provisioning failure for a delivered deal, so
      its seller failure after the stop is the site's signed withdrawal (`force_release`),
      pushed to the app's lease-ended callback through a typed client, classified
      `unentitled_withdrawal`, with the stop still selected and no filing; for the
      once-only deal restarted past its end, the payment stop is recorded and classified
      `terms`, and a withdrawal after the term end is classified `unentitled_withdrawal`
      and files nothing. `RecurringWorld` in bare metal now exposes its `runtime`, whose
      site trust the withdrawal seeds, and its `app`, which the site's client calls. Both
      storefront suites pass (VM integration 607, bare metal 649).
- [x] 3.4 Verification point: `domains/compute` tests (unit), `kit/deal-servicing`
      (library integration), both storefronts' lifecycle suites (application
      integration) pass. End-to-end: `e2e_vm_payment_deal`, `e2e_bare_metal_payment_deal`
      and the two recurring purchases record classified ends; none asserts the
      classification.
      Done: `make -C domains/compute test` (24), `make -C kit/deal-servicing test` (116),
      `make -C domains/vms/storefront test-integration` (607) and `make -C
      domains/bare_metal/storefront test` (649) pass, and `scripts/change-workflow run
      pre-commit` passed with every functional hook, every suite among them. End-to-end
      corrected: neither payment deal records a payment stop — VM's ends by an
      administrator interruption, bare metal's by the buyer's teardown and a seller
      refund — so only
      `e2e_vm_recurring_purchase` and `e2e_bare_metal_recurring_purchase` record a
      payment stop this section classifies (the payer's, now `entitled_stop`); neither
      asserts the classification, so no scenario is evidence for it. Owed by validation:
      none.
      Fresh-context check: fixed — the bare-metal world's comment saying no route carries
      a site report (the withdrawal now goes through the lease-ended callback, not the
      ingress directly); a test comment claiming bare metal's own term-end record falls at
      the payment stop's instant, which the test never checks; the watch's and its test's
      comments explaining a pending slot by an earlier release rather than its state; the
      once-only bare-metal case not showing how the withdrawal was classified (now
      asserted); the untested seller-failure resolution branch (now a kit case); and
      3.4's reason for bare metal's payment deal. Declined: the two storefronts' identical
      `classify` closures, since the family classifier cannot build the kit's
      `Classification` under its allowlist and a shared wrapper would need a package both
      storefronts and the kit admit for two lines; `EndSession.classification` beside the
      storefronts' and compute delivery's own `classification_for` readers, which are
      outside this section and left as they are; the VM failure step calling
      `apply_fulfillment_failure_policy` rather than a provisioning-failure route, as
      `test_lifecycle_failures.py` does, since VM has no route reporting a teardown
      failure; and `domains/compute/tests/` being flat, as it was.

Section 3 handoff:

- The kit's resolution path: `DealWatch._record_payment_stop` resolves a pending slot only
  (`EndSession.classification` is `None`), at the record's revision read inside the
  observation's transaction, and its revision moves once. Section 6's helper reads the
  authorities through the same watch, so it needs nothing more for D2.
- Each storefront binds the classifier in its `watch` factory with the term end computed
  from the Agreement, truncated as each registers it; the payments mandate's part end is
  `ceil(start + duration)`, so for a fractional start the payment stop lands a second after
  the registered term end and still classifies `terms`. Section 7's unified term end
  (D4) records the storefront's own `term-end` request beside it.
- Bare metal's once-only case shows both its own `term-end` request and the payment stop
  recorded; which sorts first depends on the start's fraction, so the case asserts the
  payment stop's classification, not that it is selected.
- VM's recurring world's `DeliveryProvisioning` has no `terminate_lease`, so the physical
  end after a stop logs "VM physical end awaits recovery" in these cases; nothing asserts
  teardown there. Section 9.3's restart cases, which do, will need it.
- Bare metal's `WorldProvisioning` has no `get_lease`, so a cycle's `recover_site` logs a
  failure in the recurring world; the same applies to cases asserting site recovery.

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
      its payments section, its new `payments_client_for_owner` (the payments service's
      client; `None` builds one from the section, as bare metal's does) and its
      declaration; `build_vm_settlement_composition` builds the coordinator over the
      composition's stage, and the recurring world gives the composition the in-process
      engine as `payments_client_for_owner`. A `dataclasses.replace` builds the stage
      again, an equal one, since the stage holds only its section, client factory and
      declaration; the builder's comment says the coordinator keeps the first. Evidence:
      `test_servicing_composition.py`, the served recurring world's composition, built
      from a payments section with the servicing fields and given no stage, holds a stage
      over its own declaration (`rate_servicing` the composition's, `charged` and
      `returned` declared) and the section's receipt identity — composition
      construction read through the served world, so narrower than application
      integration; the application evidence that the composition-built stage services
      deals is the recurring world's delivered cases (`test_rate_delivery.py`,
      `test_lifecycle_ends.py`, `test_watchdog_buy.py`), which now run on it and pass.
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
      mechanism not named keeps its earlier, non-repair outcome, which three kit tests
      composing no adapter rely on. `unserviceable()` lists each such deal still open
      (not released after a recorded end), paging every registered deal. VM's lifecycle names the
      payments fields when no coordinator is composed; bare metal's composes the payments
      adapter only while its composition builds a stage, and names them otherwise. Each
      startup (`server.py`'s `_start_vm_services`, bare metal `server.py`'s
      `_start_runtime`, where the runtime starts) logs a warning per deal, and each status
      reports `unserviceable_deals` (VM's `SystemService` provider and
      `VmSystemStatusResponse`; bare metal's `runtime.status` and
      `BareMetalHealthResponse`), the typed client reading it in `extra`. Files differing
      from the plan: the startup is bare metal's `server.py`, not `runtime.py`, which
      holds its status; both status response models. Library integration
      (`test_watch_and_seller.py`): such a deal lists `repair_required` with that reason
      before its missing credential, `unserviceable()` names it, a composition naming the
      mechanism but composing its adapter reports none and lists the deal `running`, one
      naming no missing configuration reports none, and once ended and released the deal
      is not reported; `kit/deal-servicing` 118 passed. Application integration,
      one deal kind per case, each world settling one deal on its one listing: VM (`test_degraded_startup.py`) — the recurring
      world settles a rate, or a once-only, payments deal with its site unreachable (so
      it stays open), then the configured app starts over the same database with an
      Alkahest-only settlement, configured as the same seller (its lifecycle routes sign
      as the Agreement's seller) with the harness's administrator, which stays durable:
      it starts, logs the deal with the reason, status reports it, and the
      typed seller lifecycle client (`SellerLifecycleClient`) lists it `repair_required`
      and reads its reason; bare metal (`test_unserviceable_startup.py`) — the same
      observations, restarting its recurring world with `payments_section=False`, which
      configures no payments section and publishes no payment clause; that restart
      replaces the test runtime's composition rather than loading a configuration, so it
      is narrower than VM's, which runs the configured app. "Servicing fields removed" is
      a configuration with no payments section in both, the case a stage is not built
      for.
- [x] 4.3 Verify withdrawal (application integration, `test_servicing_composition.py` in
      each storefront): a running rate deal accepted under `returned` is still serviced
      after `returned` leaves the declaration, and no new option naming it publishes.
      Done: in each storefront's recurring world, an on-demand deal (naming `returned` at
      its term end) is accepted and the declaration narrowed to `charged` in place, as a
      restart under the narrower declaration would read it; the accepted deal then
      settles, is delivered (available), and its payer's stop, read by a servicing cycle
      (`settlement-servicing` in VM, `delivery-recovery` in bare metal), is recorded
      `payer` and classified `entitled_stop` (application integration, passed). That no
      new option naming `returned` publishes is the existing evidence, not repeated here:
      VM's `test_publication_loop.py::test_publication_omits_recurring_options_whose_treatments_are_undeclared`
      and bare metal's `tests/test_http_publication_rates.py`. "Serviced to its end" is
      shown as far as the recorded end; the teardown is the doubles' (section 3's
      handoff).
- [x] 4.4 Verification point: both storefronts' suites pass. End-to-end: every lane starts
      both storefronts from their compositions; no scenario asserts the startup report.
      Done: `make -C domains/vms/storefront test` (unit 1194 passed, 1 skipped;
      integration 611 passed) and `make -C domains/bare_metal/storefront test` (652
      passed); `make -C kit/deal-servicing test` (118). End-to-end confirmed: every lane
      starts both storefronts from their compositions, VM's now building its own stage,
      so any payments scenario (`e2e_vm_payment_deal`, the recurring purchases) is
      evidence that the composition's stage services; none asserts the startup report or
      `unserviceable_deals`. Owed by validation: none.
      Fresh-context check: fixed — a test comment saying "no longer" (also refused by the
      history-wording check); the two startup comments saying the list names the
      configuration (the read does; the list shows the state); the application tests'
      hand-built lifecycle list calls, now the typed `SellerLifecycleClient`, which also
      reads the reason at application level; the kit case for a composition with the
      adapter, which passed no `missing_adapters` and so showed nothing more than the
      unnamed case; `test_degraded_startup.py`'s module docstring; 4.3's publication
      checks, a weaker copy of the existing withdrawal tests, removed; and these notes'
      claims. Declined: moving `PAYMENTS_SERVICING_FIELDS` into `kit/arkhai-payments`
      beside `servicing_stage`, which would take that package a version and every
      dependent a relock for one string each storefront states beside its own payments
      composition; the startup warning and status entry written in each storefront, each
      in its own status pattern (VM's providers report `None` on an error, as all its
      providers do; bare metal's status computes its fields inline); the stage
      `dataclasses.replace` builds again in `build_vm_settlement_composition` and the
      recurring world, since the stage holds only its section, its client factory and the
      composition's one declaration object, which is the agreement the requirement
      guards, and a frozen composition holding its coordinator and lifecycle has no other
      way to gain them; and the 4.1 case's level, which the plan set and its note states.

Section 4 handoff:

- `SellerServicing(missing_adapters=...)` is how a storefront says a mechanism is
  installed but unconfigured; section 6's servicing helper pages deals through the same
  seller half, so an unserviceable deal reaches it with no payment adapter, and its
  authorities read must tolerate that (today the watch simply reads no payment).
- Bare metal's lifecycle now composes the payments adapter only when its composition has
  a stage; `BareMetalLifecycle.payment` still raises when called directly, which the
  respondent discovery in `cycle` does (caught there). Section 7's respondent port should
  not reach it for a deal without a stage.
- Restarting VM's configured app over a recurring world's database needs the harness's
  seller seed (`b"\x41" * 32`, `TEST_MARKETPLACE_SIGNER`) as its credential and the
  harness's administrator: lifecycle routes refuse to sign as another seller, and
  startup refuses an administrator configuration that drops a durable identity. Section
  9.3's VM restart cases will meet both.
- The VM composition is rebuilt by every `dataclasses.replace`, each time building an
  equal stage; a test needing the composition's exact stage object reads it after its
  last replace.

Round 1 triage fix, 32 F2 (`reviews/32-implementation.triage.md`): `unserviceable()`
reports a missing-adapter deal until the seller list's rule (`_outstanding`, as 32 F1
refines it) finds nothing outstanding over its saved views (`_ended`), not only until
its resource is released, so a released rate deal whose part last showed no stop stays
in the startup log and `unserviceable_deals` (D8's settled note); a deal whose views
cannot be read stays reported, logged. Library integration,
`test_watch_and_seller.py::test_a_released_rate_deal_still_billing_stays_unserviceable_until_its_part_stops`.
Both storefronts' startup and status call `unserviceable()` unchanged, so 4.2's
application cases stand for them.

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
      new case for an on-demand option without and with a setup charge; the suite 304
      passed). `kit/settlement-runtime` 0.8.1 (wording, no API); its six exact pins
      moved with it, so `kit/arkhai-payments` 0.8.1, `kit/contact-exchange` 0.5.1,
      `kit/config` 0.6.1 and `core/buyer` 0.7.1 each take a patch bump for the pin, and
      their own exact pins moved (both storefronts' `contact-exchange`, bare metal's
      `arkhai-payments`, bare metal buyer's `core-buyer`); `make lock` run.
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
      (`market delivery`, `market bare-metal delivery`, the kit's `register_read_command`,
      whose help and docstrings now name `funding_stop`), so the read, the delivery output
      and the watchdog's exit say it; `buy`'s own progress lines do not. `published-packages.md`'s
      table names `arkhai-compute` among both buyers' internal dependencies.
      `kit/deal-lifecycle-buyer` 0.3.0; VM buyer
      0.13.0 and bare metal buyer 0.9.0, each taking it `>=0.3.0`. Unit
      (`tests/unit/test_funding_stop.py`, a real `BuyerLifecycle` over mocked ports with
      an injected classifier): a read of a deal whose part stopped under `terms` before
      the term end carries the text; one stopped at the term end, one with no
      classifier, and one with no final stop carry `None`; `run_monitor`'s exit line
      carries the text for the early stop and not for the term end, the outcome's
      `funding_stop` likewise; `kit/deal-lifecycle-buyer` 55 passed
      (`test_watchdog_journal.py` now leaves `funding_stop` out with `watchdog` before
      validating the wire read). Each buyer (`test_watchdog_rate_stop.py`): the lifecycle
      the buyer's own `buyer_lifecycle` composes, over the approved rate mandate, reads a
      `terms` stop one period before the Agreement's end as funds running out and one at
      its end as not — a unit-level check of the term-end binding inside that module's
      fixture, not application integration as the plan says: it reads views built in the
      test, asserts neither the read's nor the exit's text (the kit cases do), and
      exercises neither the entitlements binding (a `terms` stop reads none) nor the
      whole-second truncation (the fixture's start is whole). The engine is not driven to
      exhaust a balance. VM buyer 336 and bare metal buyer 86 passed.
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
      Fresh-context check: fixed — the note claiming no delivery output says it (the
      delivery command prints `buyer_read`); the read command's docstrings and help, and
      the buyers' test module docstrings, which did not name the new content; the
      watchdog's exit reading the authority with no bound (now cut off at the probe
      timeout, as every other read in the loop is); bare metal's waiver coverage, which,
      like VM's, named `--allow-charged-preemption` only through the shorthand; the
      buyer cases' level and what they leave unexercised; and `published-packages.md`'s
      buyer rows, refused by `make test`'s publish-matrix check. Declined: the
      `"exhaustion"` literal in the buyer kit, which cannot import the servicing kit's
      `ClassificationKind` and names the classifier's own word; the term-end and
      entitlements binding stated in both buyers beside the storefronts' (section 3's
      decline applies); untested `funding_stopped` branches for no classifier and an
      unreadable authority, each answering the same `False` the tested term-end case
      shows; and checking rate parts only, since a once-only part's end is the
      Agreement's end, so its `terms` stop never reads as funds running out.

Section 5 handoff:

- `BuyerLifecycle.classify_payment_stop` is the buyer's slot; each buyer binds it in its
  `buyer_lifecycle`. Section 10's funds-running-out lane row asserts "the buyer's
  message": it is `buyer_read`'s `funding_stop` (`market delivery`) and the watchdog's
  exit line, `FUNDING_STOP` in `market_deal_lifecycle_buyer`.
- `kit/settlement-runtime` is exactly pinned by six packages; any later edit to it moves
  them all, and through them the storefronts' and bare metal buyer's pins on
  `contact-exchange`, `arkhai-payments` and `core-buyer`. This change has bumped each of
  them once already, so a later edit in this change moves no version again unless it
  needs a larger bump.
- `published-packages.md` holds each published package's internal dependencies, checked
  by `scripts/tests/test_publish_matrix.py` in `make test`; a dependency added to a
  published package goes there too.

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
      Reconciliation is bare metal's `reconcile_local` moved into the kit (`term-end`,
      `source="agreement"`, the record's seller as actor, the commitment as evidence).
      Library integration (`test_servicing_order.py`, the rig's SQLite): the order, with
      the seller half wrapped and end service doubled to record each step's moment, each
      step seeing what the ones before it recorded (the first physical end no term end,
      the correction and filing steps the term end, the second physical end too); with
      the real seller half and end service, a deal with a journaled operator-end filing
      whose physical port raises has its term end reconciled, its corrections run and its
      filing dispatched (its result recorded), the port called twice and two failures
      logged naming the domain, step and deal; a delivered rate deal records no term end
      at 999 and `term-end` at 1000, observed 1005, classified `terms`, selected, no
      filing, and a cycle at 1010 records no second one and logs nothing (a re-record
      observed later would be refused); an undelivered rate deal past deadline and term end
      with its payment authority unreadable records nothing, and once a read succeeds the
      deadline and the term end are both recorded, the deadline selected; an uncommitted
      surrendered deal is paged and driven twice with neither authority read.
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
      record (by case and commitment), since repairs a database holds under the earlier
      account-and-authority record have no poller to clear them once the listing
      restarts. To keep the storefront suites running at this commit, both storefronts'
      own pollers stop passing `account` (one line each); section 7 replaces those
      cycles. Library integration (`test_respondent.py`, five new cases): a page of six —
      a deal under the first authority sorting first (registered with the Alkahest
      selector, though discovery reads no deal's mechanism or account, so that label
      shows only that it does not), a second under it, one under another authority, one
      with no authority, the rig's deal, and one whose authority's adapter offers no
      respondent discovery — lists once per discoverable authority, both listings before
      any deal's recovery step, with one credential check per authority and no failure
      logged; the authority of the page's first deal failing its listing logs the
      domain, step and authority while the next authority still lists, after it, and
      both deals' recovery steps run; an unusable credential lists nothing, the deal's
      recovery runs, its payment authority is read, and the list shows it
      `repair_required`; a mediation fixture deal whose adapter is bound to another
      Agreement keeps both listed cases as repairs with that reason, logs no discovery
      failure and appends nothing, and with the matching adapter both resolve, their
      repairs clear and two answers are appended; a repair kept under an
      account-derived record clears once its case resolves. The four existing cases
      pass with the authority-only record.
- [x] 6.3 Page position: add `servicing_page_position` (one row per loop) to
      `market_deal_servicing.schema` as its own schema set, created by an ordinary
      migration a storefront chain appends; the helper pages every registered deal and
      saves its position after each page (D6). Verify (library integration,
      `test_servicing_schema.py`): the set creates and the position survives a reopen.
      Done: `PAGE_POSITION_SCHEMA` (`loop TEXT PRIMARY KEY, continuation TEXT`, no `IF
      NOT EXISTS`) and `create_page_position`, exported; the cycle pages with
      `committed_only=False` and saves the continuation once the page is serviced, `NULL`
      after the last page, so a storefront stopped mid-page services that page again
      rather than skipping its rest. The test rig applies the set. Library integration
      (`test_servicing_schema.py`): the set creates beside the others, refuses a second
      application, and a position written in one connection reads in the next;
      (`test_servicing_order.py`) three cycles of two over three deals, each a new
      `ServicingCycle` over the same file, service `deal, deal-b`, then `deal-c`, then
      `deal, deal-b`, the row ending `("deal-servicing", "deal-b")`, and a cycle of
      another loop starts from the first deal and keeps its own row.
- [x] 6.4 Verification point: `kit/deal-servicing` suites (unit, library integration) pass.
      End-to-end: none until section 7 composes the helper.
      Done: `make -C kit/deal-servicing test` (typecheck clean; 130 passed), and
      `scripts/change-workflow run pre-commit` passed with every functional hook, both
      storefronts' suites among them with their pollers taking no `account`. Its rerun
      after the fresh-context fixes (kit tests, one comment, these notes) passed every
      suite but one unrelated test, `scripts/tests/test_change_clone.py::test_the_bootstrap_failed`
      ("No child processes", a child-reaping race), which passed in the first run and in
      `make test-release-tooling` run again (3123 passed). The kit's
      README describes the cycle, the poller's record and the new set. Version: the kit
      stays 0.4.0, the bump this change already took (section 5's handoff). End-to-end
      confirmed: none. Owed by validation: none. `run test-before` was not run: it runs
      without the kit's environment, and `test_servicing_order.py` and the new
      `test_respondent.py` cases import `ServicingCycle`, which only this section adds.
      Fresh-context check: fixed — the failing-authority case failed the page's second
      authority, so it could not show a later authority still runs (now the first);
      the term end's "once" was shown at one instant (now a later cycle too); the order
      case swapped collaborators after construction (now injected) and the notes called
      its seller half and end service real; the Alkahest label overclaimed; the
      clearing of repairs under another record, the skip of an adapter with no
      respondent discovery, discovery before the deal steps and a deal with no
      authority were untested (now tested); tripwires inside discovery's handler only
      logged (now recorded, and the cases assert no discovery failure); a test name
      claiming several loops; a docstring claiming the deadline was admitted first; the
      respondent comment's history wording; a constant splitting the imports; and two
      passages of `deal-lifecycle/architecture.md` the poller's record makes stale,
      added to 12.9. Declined: removing the non-respondent branch, which keeps an
      authority whose interface lists no cases out of discovery (now tested); the
      spec-heading citation in `servicing.py`, which holds once the archive merges the
      delta, as section 2's was declined.

Section 6 handoff:

- `ServicingCycle` is what section 7 composes: each storefront passes its lifecycle as
  the `RespondentPort` (VM's has `credential_available` and `dispute_adapter`; bare
  metal's `dispute` must answer as `dispute_adapter`), its signer, its recovery steps
  and its `resolve_site_corrections(session, negotiation_id, now)` — both storefronts'
  existing resolvers take `now` by keyword, so each needs a positional adapter or a
  signature change. Its tables need the storefront chain to apply
  `create_page_position` (7.1, 7.2).
- The cycle's authorities read is `SellerServicing.read`, not `watch`: VM's cycle
  dispatched filings through `watch` before its own filing step; under the kit only
  the filing step dispatches.
- Bare metal's cycle carries its delivery re-drive (`recover_delivery`), which 7.2
  says to drop while section 8 moves it; `test_delivery_path.py`'s waiting-deal cases
  and the bare-metal lane's delivery depend on the cycle re-driving until section 8's
  routine runs in a loop, so 7.2 may need to keep it as a recovery step until then.

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
      `test_lifecycle_cycle.py`, over `test_payment_settlement`'s harness, the composed
      lifecycle over the application's database with its cycle called directly as the
      `settlement-servicing` loop calls it — narrower than application integration, as
      that file's other cycle cases are, since a cycle of one deal is reachable only by
      a direct call: a
      delivered deal with an administrator's failure end and filing journaled, its
      dispute authority's client reaching the mediation fixture and its physical port
      raising, has its filing filed at the authority (one case, cause `payee`, the intent
      `done`/`accepted`) and the physical port called twice; with a second registered
      deal past its Agreement's end, a cycle of one services the first and saves
      position `payment-neg-1`, and a newly built `VmDealLifecycle` over the same
      database (the restart, by construction, not an application restart) services the
      second (its `term-end` recorded) and saves `NULL`, and its next cycle starts from
      the first deal again (position `payment-neg-1`). The second deal's rows are written
      through the kit's sessions, not negotiated. Application integration
      (`test_lifecycle_ends.py`, the recurring world, restarted past the Agreement's end,
      the cycle run through the typed admin client's `settlement-servicing` step) the
      once-only case now
      shows both the payment stop and the storefront's own `term-end` (at the term end,
      `source="agreement"`), both classified `terms`, the selected end at the term end,
      no filing, and the termination commanded and acknowledged: the first physical end
      commands it at the payment stop's instant, since the authorities read records that
      stop before reconciliation records the term end, and a termination never restarts;
      the restarted world's site holds no reservation, so teardown completes with nothing
      to release and the deal reads `released`. That case asserted the payment stop selected before; it is renamed.
      `test_servicing_unreachable_authority.py` now expects the kit's discovery log line
      naming the domain, step and authority.
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
      then `recover_site`. The re-drive stays a recovery step until section 8's routine
      takes it: no other bare-metal loop re-drives a delivery, and
      `test_lifecycle_dispatch.py`'s readiness-adoption cases, `test_delivery_path.py`'s
      waiting-deal cases and the bare-metal lane's delivery depend on the cycle doing so.
      Section 8 must remove it from the steps. `reconcile_local` and `committed` are gone
      (the kit's); `dispute` is renamed `dispute_adapter`, the port's name, as VM's (its
      two test callers follow). Migration `bare-metal-storefront-0020-servicing-page-position`
      creates the set and drops `bare_metal_lifecycle_cursor`. `test_lifecycle_dispatch.py`,
      over the payments harness's served application, its lifecycle's cycle called
      directly as the `delivery-recovery` loop calls it, as that file's other cycle cases
      do — narrower than application integration for the cycle itself, though the
      surrender goes through the buyer's typed lifecycle client: a settled deal with an administrator's
      failure end and filing journaled, its authority's client reaching the mediation
      fixture, whose physical port raises, has its filing filed at the authority (one
      case, cause `payee`, its outcome recorded on the intent — the fixture's answer here
      is pending, not accepted as in VM's case) and the port called twice; a buyer's
      surrender before commit, whose route-time physical end fails, is driven by the
      cycle (the port's second call, the termination `done`, progress `released`, the
      deal still uncommitted, no payment read); an Alkahest deal sorting first under the
      payments deal's authority (its thread row cloned, its servicing rows written
      through the kit's sessions) leaves one `/respondent` listing at the mediation
      fixture and no discovery failure logged. Application integration
      (`test_lifecycle_ends.py`, the recurring world restarted past the Agreement's end,
      the cycle run through the typed admin client's `delivery-recovery` step): the
      once-only case now asserts the storefront's own `term-end` at the term end, cause
      `terms`, source `agreement`, classified `terms`, beside the payment stop it already
      asserted.
- [x] 7.3 Verify both migration chains (migration tests per
      `docs/guidance/repository/migration-chain-tests.md`): fresh and upgraded databases
      reach the same schema; bare metal's upgrade drops the old cursor table.
      Done (library integration, real SQLite, no application): each chain's existing
      fresh-versus-adopted, rerun and refusal cases pass with the new migration last. VM
      `test_migration_chain.py`: an adopted floor database's last applied migration is
      the page position's and its table exists, empty. Bare metal: a floor database whose
      store never opened ends with `servicing_page_position` and no cursor, matching a
      fresh one; a store-opened database holding the cursor with a row applies exactly
      the later migrations, the page position's last, matches a fresh database, holds
      no cursor and an empty position table (replacing the case that kept the cursor's
      row). `docs/development/DEPLOYMENT_AND_CONFIG.md`'s list of migrations after the
      floor names both, written here as the description of the current chains.
- [x] 7.4 Verification point: both storefronts' suites pass. End-to-end:
      `e2e_vm_payment_deal`, the `e2e_vm_dispute_*` scenarios, `e2e_bare_metal_payment_deal`
      and the two recurring purchases step the servicing cycle.
      Done: `make -C domains/vms/storefront test` (unit 1194 passed, 1 skipped;
      integration 614 passed) and `make -C domains/bare_metal/storefront test` (655
      passed), after the fresh-context fixes; `scripts/change-workflow run pre-commit`
      passed with every functional hook before them, and again at the commit (recorded
      in the handoff). End-to-end confirmed: those scenarios, and
      `e2e_bare_metal_mock_deal`, step the loop that runs the cycle
      (`settlement-servicing` in VM, `delivery-recovery` in bare metal), so a passing
      pipeline is evidence the kit's order services them; none asserts the order or the
      page position. Owed by validation: none. `run test-before` was not run: it runs
      without the storefronts' environments; the new cases call the cycle, which at the
      round's base had bare metal's single error handler (the filing case fails there)
      and VM's in-memory position (the restart case fails there), by the code read, not a
      run.
      Fresh-context check: fixed — 7.2's note claimed the bare-metal once-only case
      showed its own `term-end`, which it did not assert (now asserted); VM's teardown
      comment and note claimed completion over an assertion admitting `tearing_down`
      (now `released`, which it is); the restart case's "first deal untouched" showed
      nothing, and its docstring's wrap to the first deal was unasserted (now a third
      cycle); `e2e_bare_metal_publication`, which steps no servicing loop, named in 7.4;
      7.4's missing pre-commit record and VM's unit suite; the cycle-calling cases
      labelled application integration (now named for what they run); the per-cycle
      build's rationale, which nothing needs (removed from both docstrings and the
      note); `vm-storefront-fulfillment/architecture.md`'s term-end sentences, now stale,
      added to 12.9; a broken docstring wrap; the bare-metal test's import order.
      Declined: driving the filing and surrender cases through the admin loop route,
      since the payments harnesses' other cycle cases call the cycle directly and a
      cycle of one deal needs the direct call; importing `_clone_row` from the sibling
      test module, as `test_payment_settlement_client.py`'s own cases share it.

Section 7 handoff:

- `scripts/change-workflow run pre-commit` passed at the commit, after the
  fresh-context fixes, with every functional hook (relock, packaging, every suite).
- Both cycles are `ServicingCycle`s built in each lifecycle's `servicing()`; the loop
  names are still the old ones (`settlement-servicing` in VM runs `cycle()` beside the
  worker; `delivery-recovery` in bare metal runs it), and the page-position row is
  already keyed `deal-servicing`, the loop 9.1 registers.
- Section 8 must remove `("delivery re-drive", self.recover_delivery)` from bare metal's
  `servicing()` recovery steps when the shared re-drive replaces `recover_delivery`;
  `test_lifecycle_dispatch.py`'s readiness-adoption cases and `test_delivery_path.py`'s
  waiting-deal cases then need the re-drive's loop, not the cycle.
- VM's term end now comes from the kit's reconciliation: past the Agreement's end the
  cycle records `term-end` beside any payment `terms` stop, and the termination is
  commanded at whichever end the first physical end of the cycle sees.
- The bare-metal payments harness's `Provisioning` has no `get_lease`, so
  `recover_site` logs a failure in every cycle there; harmless, as before.

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
      (`test_recover_deliveries.py`, the rig's SQLite and end service, the real path,
      the port a recording double): the rig's deal committed and waiting, at its start,
      is claimed, re-checked and driven to `converged` inside the claim (call order
      claim, revalidate, drive, release; the limit passed to the listing); a deal
      another worker holds is claimed-and-released with no re-check or drive; one that
      does not re-check is released undriven; a re-check raising for one listed deal is
      logged once and the next deal is driven (4 passed; the package 134). The package
      stays 0.2.0, the bump this change already took.
- [x] 8.2 VM fills the port with `list_incomplete_vm_deliveries`, its claim lease and its
      stage's `recover_evidence`, replacing `resume_incomplete_fulfillments_once`'s loop
      (`fulfillment_resume_runtime.py`); bare metal fills it with its lifecycle-row query,
      its lock and its settlement service's `verified_evidence`, replacing
      `BareMetalLifecycle.recover_delivery` (D5). Verify (application integration,
      `test_fulfillment_resume_runtime.py` in VM, `test_restart_recovery.py` in bare
      metal): a deal waiting for its start is claimed, revalidated and driven at the start;
      a deal another worker holds is skipped; a deal whose evidence fails is not driven.
      Done, differing from the plan in each domain's drive, in bare metal's claim, in
      bare metal's test file and in VM's test level. Both domains' `revalidate` answers
      `False` when the evidence does not re-check — an unreachable chain included, since
      each stage reports that as a refusal — logging the reason at warning (`[DELIVERY]
      <id> does not re-check for recovery: …`); only an unexpected error raises, which
      the routine logs. Both list at most 50 deals a pass, VM's existing limit. VM:
      `VmDeliveryRecovery` (the incomplete-deliveries query, the `claim_vm_delivery`
      lease released after the drive, the selected stage's `recover_evidence`, whose
      `ValueError` answers `False`, as does evidence not in a verified state) and
      `VmRecoveryDrive`, which drives through `drive_vm_delivery` so the outcome is
      recorded in the delivery record and the stage's failure policy runs once,
      building the path at its first drive (a composition with no deal lifecycle and
      nothing to resume needs none); `resume_incomplete_fulfillments_once` keeps its
      signature over them, and now counts every drive it made, a drive
      `drive_vm_delivery` deferred on an exception included, where it counted only
      drives that reached an outcome; a failure building the path is now one deal's,
      logged, not the cycle's. Bare metal's step reports `redriven`; VM's
      `fulfillment-resume` step reports only its loop until section 9 splits it. Bare
      metal (`delivery_recovery.py`):
      `BareMetalDeliveryRecovery` lists the deals whose lifecycle row is not released
      (`list_unreleased_bare_metal_fulfillments`, new), whose end-service progress is
      `unstarted` or `active`, and which are not available with their result and
      receipt recorded — `recover_delivery`'s filter, applied before the limit; its
      claim answers whether the deal's lock is free; it re-checks through the new
      `BareMetalFulfillmentService.revalidate` (`deliver`'s own gate: owned context,
      then `_verified_evidence`, which runs the settlement's recovery gate, for the
      buyer recorded at acceptance). Its drive is `BareMetalFulfillmentService.redeliver`,
      `deliver` for that buyer, so every bare-metal delivery still enters through core's
      fulfillment hook (`physical-provisioning`, "Bare-metal delivery enters through the
      core fulfillment hook"): the hook takes the deal's lock for the drive and drives
      its physical end in its `finally`. That is why the claim only answers whether the
      lock is free rather than holding it — an `asyncio.Lock` is not re-entrant — and
      why `deliver`'s gate re-checks the evidence a second time before the hook; a drive
      that takes the lock between the claim and the hook is waited for, never
      overlapped. `recover_delivery` is gone from the lifecycle and its servicing steps.
      Until section 9 splits the loops, bare metal's `delivery-recovery` step runs the
      re-drive, then the servicing cycle (in a `finally`, so a re-drive that cannot list
      its deals still services them), and reports `redriven` beside `processed`; VM's
      `fulfillment-resume` step is unchanged in shape. Evidence — VM
      (`test_fulfillment_resume_runtime.py`, the pass called directly, with the rig's
      site and provisioning fakes the loop's own step would build from the configured
      sites, over the payment rig's real database, path, end service and lifecycle, the
      deal settled through the typed buyer client against the rig's app — narrower than
      the application integration the plan names, since the step cannot reach the
      fakes): a payment deal settled an hour before its start (the lifecycle clock an
      hour behind wall time, then set to it) is re-checked by the real payments stage
      once, driven to `ready` and activated, the row's claim held by the pass at
      `begin_fulfillment` and released after; with the claim held by another worker the
      pass drives nothing and re-checks nothing, the other worker's claim intact; with
      the receipt identity pin moved (the composition's payments stage built for
      another service identity) the re-check answers `False` with its warning naming
      the mismatch, the routine logs nothing, nothing is begun and the claim is
      released. Bare metal, in `integration/test_delivery_path.py` rather than
      `test_restart_recovery.py`, where the waiting Alkahest deal's setup already is
      (application integration: the served app's `delivery-recovery` loop stepped
      through the typed admin client, its timers held): at its start the waiting deal is
      driven (`redriven` 1), the escrow read from the chain twice before
      `begin_fulfillment` (the routine's re-check and `deliver`'s gate), the deal's lock
      held by the drive at `begin_fulfillment` and released after, activated and
      available; with the lock held by the test the step re-drives nothing; with the
      escrow verifier raising the re-check answers `False` — its warning names the
      gate's refusal, the routine logs nothing — and nothing is begun; and a deal whose
      end was recorded while it waited is listed no more (`progress` `end_recorded`,
      `redriven` 0). The four `test_lifecycle_dispatch.py` readiness-adoption cases now
      step `delivery-recovery` through the typed admin client, every loop held, rather
      than calling the servicing cycle; three are renamed `recovery_…`. Not exercised:
      an end recorded while the re-drive's drive holds the lock (the hook's `finally`
      physical end, unchanged). The VM test level's cause — the re-drive's capacity
      effects built from the configured sites, with no seam for a test's site — is a
      row under "Unowned work found by `serve-running-rate-deals`" in
      `openspec/changes/README.md`. Also in this section, from its compliance checks:
      `e2e-tests/tests/e2e/roles/scenarios/bare_metal/recovery_stages.py`'s docstrings
      name the re-drive, not the lifecycle's cycle.
- [x] 8.3 Verification point: `domains/compute/delivery` and both storefronts' suites pass.
      End-to-end: every scenario that re-drives a delivery, among them
      `e2e_vm_payment_purchase`, `e2e_bare_metal_mock_deal` and the recurring purchases.
      Done: `make -C domains/compute/delivery test` (134), `make -C domains/vms/storefront
      test-unit` (1194, 1 skipped) and `test-integration` (617), `make -C
      domains/bare_metal/storefront test` (657). End-to-end corrected: VM's
      `fulfillment-resume` and bare metal's `delivery-recovery` loops now run the shared
      re-drive, so the scenarios that re-drive a delivery through them are pipeline
      evidence for it: `e2e_deal` (VM's delivery-timing phase steps `fulfillment-resume`
      before and after the start) and `e2e_bare_metal_mock_deal` (its recovery stages).
      `e2e_bare_metal_recurring_purchase` steps `delivery-recovery` only once its deal is
      delivered, so it shows the step runs with nothing to re-drive;
      `e2e_bare_metal_payment_deal` re-drives through the lifecycle `commit`, and
      `e2e_vm_payment_purchase` and `e2e_vm_recurring_purchase` deliver through the settle
      task, so none of those is evidence for the routine. None asserts the routine's own
      order. Owed by validation: none. `run
      test-before` on `test_recover_deliveries.py` exits at collection (no
      `compute_provisioning_contracts` in its environment), showing nothing; at the base
      `recover_deliveries` does not exist. `scripts/change-workflow run pre-commit`
      passed with every functional hook, after the fresh-context fixes.
      Fresh-context checks (two): fixed — bare metal's re-drive drove the path directly,
      skipping the fulfillment hook and so core's identity check, which
      `physical-provisioning` gives every bare-metal delivery (now `redeliver` through
      `deliver`, the claim answering whether the lock is free); the hook's
      repair-required log copied into the re-drive (gone with it); the claim's physical
      end missing after a failed drive (now the hook's `finally`); the two domains'
      re-checks differing (VM raised, bare metal answered `False`; both now answer
      `False` with a warning, and VM's silent refusal of unverified evidence logs too)
      and their limits (both 50); the port contract and VM's docstring saying an
      unreachable authority raises, which neither stage does; the routine's docstring
      naming a `delivery-recovery` loop VM does not yet run and saying a deal is driven
      only while held; VM's cycle docstring naming client builds as cycle failures; the
      fulfillment service's module docstring; `test_lifecycle_dispatch.py`'s fourth
      readiness case still calling the servicing cycle, and its step helper not holding
      the loops; bare metal's interim step skipping the servicing cycle when the
      re-drive's listing fails (now a `finally`); the bare-metal escrow case not showing
      how the re-check answered, and the first case not showing the re-check ran;
      `recovery_stages.py`'s docstrings; 12.9's D5 list missing passages of
      `compute-delivery/architecture.md` and `physical-provisioning/architecture.md`;
      the VM test level recorded as an unowned row; a guard on a lifecycle row with no
      servicing record, removed (the path creates the row under admission); and these
      notes' VM-level, physical-end and end-to-end claims. Declined: VM's step reporting
      `redriven` before section 9 splits its loop.

Section 8 handoff:

- Bare metal's `delivery-recovery` step is interim: the re-drive, then the servicing
  cycle in a `finally`, reporting `redriven` and `processed`. Section 9.1 makes it the
  re-drive alone and registers `deal-servicing` over `lifecycle.cycle()`; VM's
  `fulfillment-resume` (the re-drive, then `_reconcile_payment_deals`) splits into
  `delivery-recovery` (`resume_incomplete_fulfillments_once`) and
  `payment-reconciliation`, and its `settlement-servicing` stops calling
  `lifecycle.cycle()`.
- Tests stepping bare metal's `delivery-recovery` for the servicing half will need
  `deal-servicing` after 9.1: `test_lifecycle_dispatch.py`'s
  `test_failed_readiness_observation_retries_without_starving_site_recovery` (its
  `lease_reads == 1` is site recovery, a servicing step) and
  `test_recovery_never_adopts_readiness_after_buyer_end` (its teardown is the servicing
  cycle's physical end); `test_lifecycle_ends.py` and `test_servicing_composition.py`
  step `delivery-recovery` through the recurring world for the payment watch.
- Bare metal's claim answers whether the deal's lock is free and the drive takes it in
  the hook; VM's claim holds its lease across the re-check and drive. Both re-checks
  answer `False` with a warning; the routine logs only what raises.
- The lane's `recovery_stages.py` steps `delivery-recovery` for re-drives, which stays
  right after 9.1; the purchase drivers' `servicing_loop` names and the other loop
  names are 9.2's.

Round 1 triage fix, 34 O1's U3 (`reviews/34-implementation-owner.triage.md`):
`vm_delivery_path` and `read_vm_credentials` default to the deal lifecycle's capacity
runtime (its effects) and fulfillment client, so the `delivery-recovery` loop's re-drive
reaches the site a composition's lifecycle was given. 8.2's three VM cases move from
`test_fulfillment_resume_runtime.py`'s direct pass to the new
`tests/integration/test_delivery_recovery_loop.py`, application integration: the
recurring world's served storefront, its loops held, `delivery-recovery` stepped once
through the typed admin client — the waiting deal re-checked once, claimed at
`begin_fulfillment` by a `delivery-recovery:` owner and released, `ready` and activated,
`redriven` 1; another worker's claim skipped, nothing re-checked, `redriven` 0; the
impostor-pinned stage's re-check refused with its warning, nothing begun, the claim
released. The older direct callers (`test_vm_delivery_path.py`'s three,
`test_fulfillment_resume_runtime.py`'s four Alkahest cases) are the narrowed unowned
row; the payment rig's unused `clock=` is removed.

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
      `settlement_servicing` (routes hyphenated, as every loop's are). VM: `lifecycle.py`
      names the three new loops in place of `FULFILLMENT_RESUME`; `deal-servicing` runs
      `lifecycle.cycle()`, `delivery-recovery` `resume_incomplete_fulfillments_once`
      (reporting `redriven`), `payment-reconciliation` the coordinator's
      `reconcile_once`, `settlement-servicing` the worker alone;
      `fulfillment_resume_cycle_once` and `_reconcile_payment_deals` are gone. Keys:
      `deal_servicing_interval_seconds` (unstated, `settlement_servicing_interval_seconds`)
      and `delivery_recovery_interval_seconds` (unstated,
      `fulfillment_resume_sweep_interval`, which `payment-reconciliation` reads), each
      refused by key unless positive seconds (`utils/config.py`), as
      `fulfillment_resume_sweep_interval` now is too, matching bare metal's
      `payment_reconciliation_interval`. Both storefronts' `payment-reconciliation`
      steps report the pass's `attempted` and `failed`. Bare metal:
      `deal-servicing` runs `lifecycle.cycle()`, `delivery-recovery` the re-drive alone;
      `deal_servicing_interval_seconds` and `delivery_recovery_interval_seconds` are
      optional typed settings, unstated meaning `payment_reconciliation_interval`, at
      which both jobs ran; the bare-metal chart's values schema is regenerated (`make
      helm-values-schema`), so the umbrella chart and `bare-metal-storefront` take 0.5.0.
      Both packaged `settings.toml` files say which interval each loop runs at. Beyond
      the plan, the loops' first cycles now agree: every servicing loop in both
      storefronts runs its first cycle one interval after its timer starts, where VM's
      `fulfillment-resume` ran at once — the docstring's reason, an operator holding the
      loops as the storefront starts, applies to each; a restarted storefront's first
      re-drive is therefore an interval after start, 30 seconds by default, as bare
      metal's already was. Bare metal now registers all four loops whatever it
      composes, as VM does — `payment-reconciliation` had been registered only while
      payments were composed and `settlement-servicing` only while a worker was — each
      step reporting zero work when its job has nothing composed.
      `docs/guidance/repository/deterministic-tests.md`'s loop table, which section 2B
      left for this layout, and `docs/configuration.md`'s failure-policy paragraph name
      the new loops. Evidence — VM (`test_lifecycle_status.py`): every loop startup
      registers, the four among them, is reported paused through the typed client
      (application integration); on the recurring world a deal left undelivered by an
      unreachable site, the site then answering, is serviced by a `deal-servicing` step
      through the typed admin client (page size at least one, the payment authority read
      again) and stays undelivered — which shows the servicing step ran and delivered
      nothing, though in this world a re-drive could not reach the fake site either (its
      capacity is built from the configured sites, the unowned row of section 8), so that
      `deal-servicing` never calls the re-drive is the unit case below; the intervals
      `register_vm_loops` registers, called directly under settings overrides, are 45, 20,
      20, 45 for the four with only the old keys stated and 7, 9, 20, 45 with the new
      ones, and a zero `deal_servicing_interval_seconds` is refused naming the key. VM
      unit (`test_lifecycle_advance_routes.py`): each of the four steps runs exactly its
      one job — `deal-servicing` the cycle and neither the worker nor the re-drive — and
      reports its loop; `test_loop_gate_wiring.py` gates the four. Bare metal
      (`integration/test_lifecycle_dispatch.py`, application integration through the
      typed admin client over the payments harness, rather than `test_app_composition.py`,
      which has no deal): the four loops reported, paused; a `deal-servicing` step
      reads the payment authority (page size 1) and leaves a ready fulfillment
      `unstarted`, which a `delivery-recovery` step then re-drives to `active`
      (`redriven` 1); the readiness cases step the loop each half needs.
      `test_app_composition.py`: a configured runtime registers both new loops at
      `payment_reconciliation_interval` (8) unstated and at their own keys (5, 6) stated;
      a zero `delivery_recovery_interval_seconds` is refused naming the key.
      `test_http_system.py` and `test_app_composition.py`'s loop lists name all four; a
      storefront with no worker steps `settlement-servicing` with nothing swept, and one
      with neither a worker nor payments steps both loops idle.
- [x] 9.2 Rename the loops in the lane stages that pause and step them (the 11 files
      under `e2e-tests/tests/e2e/roles/` naming `fulfillment-resume`,
      `settlement-servicing` or `delivery-recovery`, and `held_loops.py` in bare metal's
      tests). Verify (unit, `e2e-tests/tests/unit/`): the stage modules pass; and by
      running the affected scenarios in their lanes.
      Done, correcting the plan's count: ten lane files name a loop, and bare metal's
      `held_loops.py` names none. Renamed by what each step needs: the servicing cycle
      is `deal-servicing` (`vms/purchase_driver.py`'s and `bare_metal/purchase_driver.py`'s
      `servicing_loop`, `vms/test_vm_payment_deal.py`, `vms/lifecycle_deal.py`,
      `vms/dispute/stages.py`, `bare_metal/test_bare_metal_mock_deal.py`'s site-report
      read), VM's re-drive is `delivery-recovery` (`vms/delivery_timing_deal.py`), and the
      Alkahest worker's steps stay `settlement-servicing`
      (`bare_metal/publication_stages.py`, `vms/test_full_deal.py`), as does bare metal's
      re-drive `delivery-recovery` (`recovery_stages.py`); `helpers/compute_deal.py`'s
      example names `deal-servicing`. Docstrings naming the resume pass now name the
      re-drive. Unit (`make -C e2e-tests test-unit`): 911 passed, 1 skipped. System:
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
      once-only Alkahest restarts, and the recurring world is the integration
      directory's). Application integration: each storefront's recurring world settles
      and delivers a rate deal through the typed buyer client, stops, and is composed
      again over the same database with the same in-process payments engine, its loops
      held and `deal-servicing` stepped through the typed admin client. Running: after
      the restart a `deal-servicing` and a `delivery-recovery` step leave the on-demand
      deal `active` in the buyer's typed lifecycle read, no end recorded, its part with no
      final stop, nothing re-driven. Ending: the payer's stop submitted at the payments
      engine while the storefront is down shows no recorded end in the buyer's typed read
      until the restarted storefront's `deal-servicing` step, after which the read shows
      the `payer` end, which the journal classifies `entitled_stop`. Pending seller stop:
      a spot deal's payee stop with its 120-second notice, submitted while the storefront
      is down, records no end at a step before its instant, and a step with the
      lifecycle clock and the engine past the instant records the `payee` stop ended at
      the instant, `entitled_stop` — read from the servicing journal, not the typed
      client, since the storefront's clock is then ahead of the reader's. Each restarted
      world's site is a fresh fake, so none asserts the teardown (section 3's handoff).
      VM 3 passed (integration 623), bare metal 3 passed.
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
      `e2e_bare_metal_recurring_purchase` (113 passed), both run before the fresh-context
      fixes; those changed bare metal's registration only for a composition without
      payments or a worker, which neither lane runs, VM's reconciliation step's report,
      which no lane stage steps, and lane docstrings. End-to-end confirmed, as those runs show:
      the scenarios above step the renamed loops (`e2e_vm_payment_purchase` steps none of
      them), and are the pipeline's evidence for the layout once deployed; none asserts
      the intervals or the restart cases, which are application integration only. Owed
      by validation: none. `run test-before` was not run: it runs without the
      storefronts' environments, and the new cases step routes (`deal-servicing`,
      `delivery-recovery` as the re-drive alone) the base does not register.
      `scripts/change-workflow run pre-commit` passed with every functional hook, after
      the fresh-context fixes.
      Fresh-context check: fixed — bare metal registering `payment-reconciliation` and
      `settlement-servicing` only as composed, against the delta's same four loops (now
      always, idle when unconfigured); VM's `fulfillment_resume_sweep_interval` read
      unchecked though two loops now run at it (now refused unless positive seconds);
      the two `payment-reconciliation` steps reporting differently (both now report
      `attempted` and `failed`); the restart cases' ending stop read only from the
      journal (now through the buyer's typed read too) and their loops not held (now
      held); two lane docstrings calling the re-drive what a restarted storefront runs
      first, untrue once its first cycle waits an interval; the constants' comment
      placement; `TESTING.md` and `vm-storefront-fulfillment/architecture.md` passages
      added to 12.9; and these notes' claims for the VM re-drive case, the interval
      cases' level and the restart reads. Declined: correcting `core/storefront-client`'s
      docstrings naming `fulfillment-resume`, which would take that published client a
      version for a docstring — recorded as an unowned row; and reading the pending seller
      stop through the typed client, whose clock would then be behind the storefront's.

Section 9 handoff:

- The four loops are `deal_servicing`, `delivery_recovery`, `payment_reconciliation` and
  `settlement_servicing` in both storefronts, registered whatever is composed. Section
  10's lane rows step `deal-servicing` for stops and teardown and `delivery-recovery`
  for activation; the recurring purchases' drivers already name `deal-servicing`.
- VM's re-drive still builds its capacity effects from the configured sites when
  stepped as its loop (an unowned row), so a VM application test of a re-drive through
  the loop's route cannot reach a fake site.
- The restart cases build a fresh site fake per restarted world; a lane or test that
  asserts teardown after a restart needs the site to outlive it (section 2A's handoff).
- The chart is 0.5.0 (the bare-metal values schema accepts the two new keys);
  `make helm-values-schema` regenerates it when the bare-metal settings change again.

Round 1 triage fix, 34 O1's U4 (`reviews/34-implementation-owner.triage.md`), outside
the plan: `core/storefront-client`'s `admin_run_lifecycle_cycle` docstrings, sync and
async, list the loops the compute storefronts register; the client is 0.29.1, and
`provisioning/compute/service`, its one exact pin moved, 0.25.1. The unowned row is
removed. `drive-the-storefront-clock-in-lanes` also edits that client, so whichever
change merges second resolves its version line.

Round 1 triage fixes' evidence (32 F1, 32 F2, 34 O1's U2, U3, U4):
- library integration, `kit/deal-servicing`: 133 passed;
- unit, VM storefront: 1197 passed, 1 skipped, the new failure-policy case among them;
- application integration, VM storefront: 623 passed, the three moved re-drive cases
  among them; bare-metal storefront: 663 passed;
- `scripts/change-workflow run pre-commit`: `after-functional-change … passed, exit 0`
  and `pre-commit-functional … passed, exit 0` (every package's suite, the e2e unit
  suite 911 passed, 1 skipped, the release tooling 3123); its `pre-commit` hook
  refused once on history wording and once on a function-level import in the new
  unit case, both fixed, and `make check-repository CHANGE=serve-running-rate-deals
  CHANGE_BASE=dev` then passed every check, with the VM unit suite run again (1197
  passed, 1 skipped);
- `run test-before` on `test_watch_and_seller.py` exits at collection (no
  `market_deal_lifecycle` in its environment), showing nothing;
- fresh-context check: found no correctness defect; fixed — `resume_incomplete_fulfillments_once`'s
  docstring, the release failure action's untested lifecycle branch (now the unit case
  above) and its comment and attribute read, the payment rig's dead `clock=`, an
  ordering guard in `test_lifecycle_admin.py` (`teardown` unset before the interruption),
  `VmDealLifecycle`'s docstring and its `physical is not None` test, `_ended` failing the report on an
  unreadable view (now reported and logged), and `examples/payment_smoke.py`'s
  post-construction replacement.

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

Note from 44 F1's fix (`reviews/44-implementation.triage.md`): a lane deal names a
dispute authority, so 10.1's `ended` also needs the lane storefront's servicing cycle to
have saved one verified read of that authority; until then the seller list shows the
deal `ending` with `case_unobserved`.

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
