# Tasks

Each section bumps the version of every package it changes, once per change, as
[`package-versions.md`, "A version changes when its contents change"](../../../docs/guidance/repository/package-versions.md#a-version-changes-when-its-contents-change)
asks; `make check-version-bumps`, which `change-workflow run pre-commit` runs, holds it.

## 1. The servicing pass and the unanswered-filing code

Delivers D7's leading physical pass and D11's fifth ending code, in the kit and both
storefronts. Implements `deal-lifecycle`'s modified "Each deal's servicing steps run in
one kit-owned order" and "The seller half lists deals". Touches `kit/deal-servicing`,
`kit/deal-lifecycle-contracts`, `kit/deal-lifecycle-client`, and the two compute
storefronts' integration tests.

- [ ] 1.1 In `kit/deal-servicing/src/market_deal_servicing/servicing.py`, make
  `ServicingCycle.cycle` drive `EndService.drive_physical` for every deal on the page,
  each in its own error isolation, before `discover` and the per-deal steps, which keep
  today's order; update the module and method docstrings to the new order (D7). Verify
  with library integration in `kit/deal-servicing/tests/integration/test_servicing_order.py`:
  a later deal with an end recorded before the cycle has its `terminate` dispatched
  before any authority read or respondent listing while every authority hangs; a deal
  whose own payment read records a stop is torn down in its own steps, before later
  deals' steps; a failing physical end in the leading pass skips no other deal's (the
  delta's scenarios "A recorded end waits behind no authority read" and "An end a deal's
  own read discovers is torn down after its steps").
- [ ] 1.2 In `kit/deal-lifecycle-contracts/src/market_deal_lifecycle_contracts/models.py`,
  add `filing_unanswered` to `EndingCode` and its text, "A filing of the deal's own has
  no answer from the dispute authority.", to `ENDING_TEXT` (D11). Confirm
  `kit/deal-lifecycle-client` interprets no code itself and renders reasons through
  `DealSummary.ending_reasons`. Verify with the contracts' unit tests: every
  `EndingCode` has its text, and a `DealSummary` listing `filing_unanswered` validates
  only while `ending`.
- [ ] 1.3 In `kit/deal-servicing/src/market_deal_servicing/seller.py`, have
  `_outstanding` name `filing_unanswered` for any `delivery_end` filing intent whose
  outcome is neither accepted nor rejected — unsent, waiting for the Agreement's start,
  pending or unknown — reading the journal's filing intents, in `_list` and in
  `_ended`, which the unserviceable report uses (D11). Verify with library integration
  in `kit/deal-servicing/tests/integration/test_watch_and_seller.py`: the delta's
  scenarios "A filing waits for the Agreement's start" and "A filing's answer was
  lost", a filing of unknown outcome, an accepted filing whose case is closed listed
  `ended`, a rejected filing still repair required, and an unserviceable deal with an
  unanswered filing still reported.
- [ ] 1.4 Prove both through each storefront's typed lifecycle client, at application
  integration: in the VM storefront (`domains/vms/storefront/tests/integration/test_lifecycle_cycle.py`
  and `test_lifecycle_ends.py`) and the bare-metal storefront
  (`domains/bare_metal/storefront/tests/integration/test_servicing_composition.py` and
  `test_lifecycle_ends.py`), a deal ended before its Agreement's start is listed
  `ending` with `filing_unanswered`, and a deal with a recorded end is torn down by a
  cycle whose authorities do not answer before any read times out.
- [ ] 1.5 Verify the section: `make -C kit/deal-servicing test`,
  `make -C kit/deal-lifecycle-contracts test`, `make -C kit/deal-lifecycle-client test`,
  both storefronts' integration suites, and `change-workflow run pre-commit
  converge-ongoing-compute-leases` passing. End-to-end: none of the existing markers
  asserts `filing_unanswered` or the pass order; the rate rows of sections 5 and 6
  exercise both once deployed (`e2e_vm_rate_servicing`, `e2e_vm_rate_dispute`,
  `e2e_bare_metal_rate_servicing`, `e2e_bare_metal_rate_dispute`).

## 2. A revised `delivery_end` filed at once

Delivers D6's adapter path and D14's `describe` client method. Implements
`deal-lifecycle`'s modified "Filing identities and revised requests are safe across
callers" and "Revised cases carry their prior rulings". Touches `kit/arkhai-mediation`
and the two compute storefronts' integration tests.

- [ ] 2.1 In `kit/arkhai-mediation/src/market_arkhai_mediation/adapter.py`, replace the
  `repair required: delivery-end revision requires resolved prior rulings and effects`
  answer in `MediationAdapter.submit`: adopt a filed `delivery_end` equal to the claim,
  whoever filed it; otherwise file the claim at once as a new case, its single-writer
  reservation and idempotency key bound to its own fixed request, staying `Pending`
  only while the caller's own earlier `delivery_end` filing is of unknown outcome; keep
  `repair required` only for a mapping the adapter cannot prove safe (D6). The filing
  carries no reference to an earlier case. Verify with library integration in
  `kit/arkhai-mediation/tests/integration`, replaying the vendored traces: a payee
  claim after the buyer's `delivery_end(cause=payer)` case and after the seller's own
  earlier filing is filed as a second case, never refused; an equal claim adopts the
  filed case; a revision behind an unknown earlier filing of the same caller stays
  pending; a buyer's claim after a seller's case is filed too (the delta's scenario "A
  changed claim follows a filed one").
- [ ] 2.2 Add `describe()` to `MediationClient`
  (`kit/arkhai-mediation/src/market_arkhai_mediation/client.py`), reading the
  authority's public description route and returning its `Description`, validated
  against the vendored schema (D14). Verify with the kit's tests against the vendored
  vectors' `description`, and a refusal of a body the schema refuses.
- [ ] 2.3 Prove the revision through each storefront at application integration: in the
  VM storefront (`domains/vms/storefront/tests/integration/test_lifecycle_mediation_trust.py`
  or `test_lifecycle_ends.py`) and the bare-metal storefront
  (`domains/bare_metal/storefront/tests/integration/test_lifecycle_mediation_trust.py`),
  a deal holding the buyer's accepted surrender case whose site report proves an
  earlier seller failure files the payee's `delivery_end` as a new case, is listed with
  that case open, never repair required, and records the delivery end a programmed
  ruling of it applies, classified as a ruling, sending no stop or reverse of its own.
- [ ] 2.4 Verify the section: `make -C kit/arkhai-mediation test`, both storefronts'
  integration suites, and `change-workflow run pre-commit converge-ongoing-compute-leases`
  passing. End-to-end: none today; `e2e_vm_rate_dispute` and
  `e2e_bare_metal_rate_dispute` exercise it once sections 5 and 6 add row 2 and row 3's
  revision, and `e2e_vm_live_dispute` live, through section 5's scenario.

## 3. The site's sends to a storefront held by a pause

Delivers D8's provisioning half. Implements `physical-provisioning`'s added "A storefront
hears from its site only through steps a pause holds". Touches
`provisioning/compute/src/compute_provisioning/lease_lifecycle.py`,
`provisioning/compute/service/src/compute_provisioning_service/services/operator_events.py`,
`provisioning/compute/service/src/compute_provisioning_service/services/capacity_reservation_watchdog.py`,
the service's composition (`container.py`, `app_runtime.py`) and system routes
(`controllers/system_controller.py`), `provisioning/compute/contracts` (`routes.py`,
`system.py`) and `provisioning/compute/client`.

- [ ] 3.1 Make the lease lifecycle's inline delivery (`_deliver_events`, through the
  composed `EventDeliveryWorker.deliver`) send nothing while event delivery is paused,
  leaving the recorded events for `POST /api/v1/system/event-delivery/run-cycle`; a pause
  holds the inline sends that start after it is acknowledged, an inline delivery already
  under way may complete, and the worker's gate keeps counting its timer cycles only
  (D8, 13 F2). Unpaused, delivery stays inline. Verify with application integration in
  `provisioning/compute/service/tests/integration`: with event delivery paused, a
  terminate, a retry-release and a force-release each record their events and send
  nothing to a stub storefront peer, and one `run-cycle` delivers each with its original
  identity and instant; a stepped lease-watchdog cycle the same; unpaused, a terminate's
  report is delivered before it returns (the delta's first three scenarios).
- [ ] 3.2 Give the capacity-reservation watchdog a gate its timer holds at while paused,
  and pause, resume and one-cycle routes beside the lease watchdog's, each a route
  contract in `provisioning/compute/contracts` bound by a typed method of
  `provisioning/compute/client`, answering `paused` and `at_gate` as
  `WorkerPauseResponse` does (D8). Verify with application integration through the typed
  client: paused and at its gate, the watchdog records no expiry of a hold past its
  time, and one stepped cycle expires it and records its event (the delta's scenario
  "The capacity-reservation watchdog is held").
- [ ] 3.3 Verify the section: the provisioning service's, contracts' and client's unit and
  integration suites and `change-workflow run pre-commit converge-ongoing-compute-leases`
  passing. End-to-end: every compute-lane marker meets the site's sends; section 4 holds
  them and steps event delivery, after which `e2e_deal`, `e2e_bare_metal_mock_deal`,
  `e2e_bare_metal_payment_deal`, `e2e_vm_recurring_purchase`,
  `e2e_bare_metal_recurring_purchase`, `e2e_vm_rate_servicing` and
  `e2e_bare_metal_rate_servicing` exercise them.

## 4. The lanes hold the site's sends

Delivers D8's lane half and the rule it writes. Implements `test-compatibility`'s modified
"Scenarios hold shared services for the whole module". Touches
`e2e-tests/tests/e2e/roles/helpers/compute_deal.py`, the compute lanes' `conftest.py`
files (`e2e-tests/tests/e2e/roles/scenarios/vms/`, `.../bare_metal/` and the rate and
dispute subdirectories), `e2e-tests/tests/unit/test_scenario_lane_holds.py`, the stages
that wait for a release or a report, `docs/guidance/engineering/system-tests.md` and
`docs/guidance/repository/deterministic-tests.md`.

- [ ] 4.1 Add `event_delivery_held` and `capacity_reservation_watchdog_held` hold helpers
  beside `lease_watchdog_held` in `compute_deal.py`, with their assertions, and the lanes'
  fixtures of the same names, the VM lane's also holding Alice's provisioning timers; take
  them in every compute-lane module, listed with the other holds (D8). Verify with
  `e2e-tests/tests/unit/test_scenario_lane_holds.py`, extended to require both of every
  compute-lane module and Alice's provisioning holds of every VM-lane module, failing on
  a module that omits one (the delta's scenario "A compute-lane module omits a hold"),
  and `e2e-tests/tests/unit/test_scenario_holds.py` and
  `test_scenario_cleanup_order.py` passing.
- [ ] 4.2 Make every stage that waits today for a site's report or release step event
  delivery once instead: the VM lifecycle deal's Stage12c
  (`e2e-tests/tests/e2e/roles/scenarios/vms/lifecycle_deal.py`), the bare-metal mock
  deal's Stage12e (`test_bare_metal_mock_deal.py`), the bare-metal payment deal's
  `_release` (`test_bare_metal_payment_deal.py`), the recurring-purchase and rate stages
  that prove a release (`e2e-tests/tests/e2e/roles/helpers/recurring_purchase_stages.py`
  and the rate stages), and the VM cleanup that releases reservations through the site's
  release route (`e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`,
  `release_reserved_resources`) (D8; the delta's scenario "A release reaches the
  storefront by a step"). Correct the comment in `e2e-tests/tests/e2e/roles/helpers/buy.py`
  that says the settle request dispatches the fulfillment before it answers, which is
  not so for VM Alkahest. Verify by running each touched marker against its lane locally
  (`make -C e2e-tests test-e2e-vm` and `test-e2e-bare-metal`, `E2E_MODULE` naming the
  markers) and by validation's pipeline run.
- [ ] 4.3 Write the rule into the guidance (D8): in
  `docs/guidance/engineering/system-tests.md`, "A scenario is a sequence of state
  changes", that a request a test makes may carry its own effect into the service it
  addresses and any further delivery from that service to another is a pausable step
  the test takes, with a neutral example; in
  `docs/guidance/repository/deterministic-tests.md`, "Pause the loop, then advance it
  explicitly", the capacity-reservation watchdog's row in the control table, event
  delivery and that watchdog among the holds every compute-lane module takes, and the
  rule's instance here. Verify with `make check-guidance` and `make check-doc-citations
  CHANGE=converge-ongoing-compute-leases`.
- [ ] 4.4 Verify the section: the e2e unit suite (`make -C e2e-tests test-unit`) and `change-workflow run pre-commit converge-ongoing-compute-leases`
  passing. End-to-end: every compute-lane marker takes the new holds; the release
  stages run in `e2e_deal`, `e2e_bare_metal_mock_deal`, `e2e_bare_metal_payment_deal`,
  `e2e_vm_recurring_purchase`, `e2e_bare_metal_recurring_purchase`,
  `e2e_vm_rate_servicing` and `e2e_bare_metal_rate_servicing`, which validation's
  pipeline run must show passing.

## 5. The VM lane's rows and the revision's live verification

Delivers D9's VM rows, D10's lane-only setup option, row 3's revision (D6) and D14's live
verification scenario. Implements `test-compatibility`'s added "The remaining rate rows are
qualified on lane time" (its VM rows and the both-lane rows' VM half) and modified "Rate
deals and dispute filings are verified live against a prepared topology". Touches
`domains/vms/storefront/storefront.bob.lane.toml`,
`e2e-tests/tests/e2e/roles/scenarios/vms/rate_servicing/`, `.../vms/rate_dispute/`,
`.../vms/live/`, the shared stage helpers, `e2e-tests/pyproject.toml` and
`e2e-tests/Makefile`.

- [ ] 5.1 Add the lane's setup-priced option: the VM lane storefront declares
  `setup = true` beside `[charged, returned]` in `storefront.bob.lane.toml` only, with a
  recurring clause pricing a setup amount, every existing row keeping today's setup-free
  option (D10). Verify that the existing rate rows' fixtures select the setup-free
  option and that the storefront starts with the declaration (its startup refusal
  passes).
- [ ] 5.2 Add the servicing rows to `vms/rate_servicing/` under `e2e_vm_rate_servicing`,
  each on its own deal on lane time with every timer held: the baseline's setup variant;
  the buyer's earlier stop during a spot notice; the on-demand notice refused at
  `market-storefront deals preempt`, naming `delivery_end`; an undelivered rate deal past
  its delivery deadline, filed at the Agreement's start, setup returned with
  `delivered: false`; both orders of an activated deal never available, the setup
  variant among them; a late start and an end inside a period at the maximum term (D9,
  D10; the delta's scenario "A setup charge is returned for a deal never delivered").
  Verify each locally with `make -C e2e-tests test-e2e-vm E2E_MODULE=<marker>`.
- [ ] 5.3 Add the dispute rows to `vms/rate_dispute/` under `e2e_vm_rate_dispute`, each
  ruling programmed at the mediation double from the producer's published traces and
  gated with `pause_before_effects` where servicing is stepped while it waits: the
  buyer's end with the payment authority unreachable; the site's end of a lease the
  storefront has not heard of — event delivery held, the buyer's `market end` case, the
  report delivered by a step, the payee's revision ruled mechanically and netted (D6,
  D8); a lost filing answer and a held ruling's resend on a rate deal, and earlier
  evidence after a filed end revised (row 3); a spot seller's emergency filing and the
  ends of the penalty's cap, the setup charge alone held among them; a seller that never
  files, the storefront's loops held throughout and the buyer filing through the
  harness's dispute adapter; the contested case asserting the `seller_assertion` and
  `buyer_observation` evidence classes; a case over a rate part already paid out (D9;
  the delta's scenarios "The site's report arrives after the buyer's case" and "The
  seller never files"). Verify each locally with `make -C e2e-tests test-e2e-vm E2E_MODULE=<marker>`.
- [ ] 5.4 Add the revision's live verification scenario to `vms/live/` under
  `e2e_vm_live_dispute`, extending the live seller-filing scenario on a deal of its own in
  the live verification form: after the seller's filing is ruled and closed, the
  storefront records an earlier seller failure and files the payee's revision, and the
  scenario reads the ruled entry and the payment snapshot through the public clients
  and holds them to one assertion shared with row 3's lane twin — basis `payee_filed`,
  the earlier delivery end, a stop whose reversal covers only the earnings between the
  two ends, no second penalty, the case closed. It reads the authority's advertisement
  through `MediationClient.describe()` and leaves the observation unproven, naming the
  requirement, against an authority that does not advertise mechanical revisions; it
  states its topology requirements as `system-tests.md` asks (D14; the delta's scenarios
  "A revision is ruled live" and "The authority does not rule revisions"). Verify it
  collects and skips with its blocked reason with no external target, and that its
  shared assertion passes in the lane twin.
- [ ] 5.5 Register any marker these rows add in `e2e-tests/pyproject.toml` and the VM
  lane's marker expression in `e2e-tests/Makefile`, keeping `e2e_vm_live_dispute` in no
  lane, and update the Makefile's comments on the VM rows. Verify with
  `e2e-tests/tests/unit/test_scenario_lane_holds.py` and the lane's collection.
- [ ] 5.6 Verify the section: the VM lane's rate markers pass locally and
  `change-workflow run pre-commit converge-ongoing-compute-leases` passes. End-to-end:
  `e2e_vm_rate_servicing` and `e2e_vm_rate_dispute`, which validation's pipeline run must
  show passing; `e2e_vm_live_dispute`'s revision scenario is live evidence the
  coordinator supplies (section 7).

## 6. The bare-metal lane's rows and twins

Delivers D9's bare-metal rows. Implements `test-compatibility`'s added "The remaining rate
rows are qualified on lane time" (the both-lane rows' bare-metal half) and the renamed and
modified "A dispute on a running rate deal is qualified in both compute lanes". Touches
`e2e-tests/tests/e2e/roles/scenarios/bare_metal/rate_servicing/`, a new
`e2e-tests/tests/e2e/roles/scenarios/bare_metal/rate_dispute/`, `e2e-tests/pyproject.toml`
and `e2e-tests/Makefile`.

- [ ] 6.1 Add to `bare_metal/rate_servicing/` under `e2e_bare_metal_rate_servicing`: the
  buyer's earlier stop during a spot notice and the on-demand notice refused at the
  bare-metal storefront's `deals preempt` (D9). Verify each locally with
  `make -C e2e-tests test-e2e-bare-metal E2E_MODULE=<marker>`.
- [ ] 6.2 Add `bare_metal/rate_dispute/` under a new marker `e2e_bare_metal_rate_dispute`,
  sharing the VM rows' stages where their bodies agree: the twins of the VM lane's
  seller's filing ruled mechanically and buyer's contested case ruled by an operator;
  the buyer's end with the payment authority unreachable; the site's end of a lease the
  storefront has not heard of with the payee's revision; a seller that never files; the
  contested case asserting both evidence classes — each through the bare-metal
  storefront's administrator end, the bare-metal buyer's commands and its teardown (D9;
  the delta's scenario "The bare-metal lane rules both"). Register the marker in
  `e2e-tests/pyproject.toml` and the bare-metal lane's marker expression in
  `e2e-tests/Makefile`. Verify each locally with `make -C e2e-tests test-e2e-bare-metal
  E2E_MODULE=e2e_bare_metal_rate_dispute`, and the hold check accepting the new module.
- [ ] 6.3 Verify the section: the bare-metal lane's rate markers pass locally and
  `change-workflow run pre-commit converge-ongoing-compute-leases` passes. End-to-end:
  `e2e_bare_metal_rate_servicing` and `e2e_bare_metal_rate_dispute`, which validation's
  pipeline run must show passing.

## 7. The revision's live verification evidence

Records D14's evidence. Implements the live half of `test-compatibility`'s modified "Rate
deals and dispute filings are verified live against a prepared topology". Touches
`docs/attachments/converge-ongoing-compute-leases/live-verification.md`, which the
coordinator writes.

- [ ] 7.1 The coordinator deploys the change's branch and a dispute authority meeting
  R1–R4 to a prepared topology, runs section 5's revision scenario, and writes
  `docs/attachments/converge-ongoing-compute-leases/live-verification.md`: a sanitized,
  free-form summary naming no host, project or path, the commit it ran, and the
  revision observation made, failed or unproven, as
  [`system-tests.md`](../../../docs/guidance/engineering/system-tests.md#locally-verifiable-and-external-topology-scenarios)
  asks (D14). This section's session runs no live scenario: it takes the summary in
  good faith, confirms it is present, public-safe and names the observation's outcome,
  and commits it if the coordinator left it uncommitted. Without the summary the
  session stops, the change waiting on it. A failed or unproven observation goes to
  the round's triage.
- [ ] 7.2 Verify the section: `make check-doc-citations CHANGE=converge-ongoing-compute-leases`
  and `change-workflow run pre-commit converge-ongoing-compute-leases` passing.
  End-to-end: `e2e_vm_live_dispute`'s revision scenario, run by the coordinator; no
  pipeline lane runs it.

## 8. Closeout

- [ ] 8.1 Comment hygiene: run `make check-comment-hygiene`; any finding, or a comment
  this change added that names a change, task, review or migration, returns the change
  to implementation.
- [ ] 8.2 Import placement: check the imports this change added in `kit/deal-servicing`,
  `kit/arkhai-mediation`, `kit/deal-lifecycle-contracts`, `provisioning/compute` and
  `e2e-tests`; one that should move returns the change to implementation.
- [ ] 8.3 Documentation compliance: re-check D1–D14 against
  [`openspec/README.md`, "Documentation placement"](../../README.md#documentation-placement)
  and the workflow's placement rules, and confirm each permanent document written
  describes the current state with no wording relative to the change.
- [ ] 8.4 Narrative compression: shorten completed-task notes to final behaviour,
  material evidence, deferred work and destinations, moving any rationale into
  `design.md` first.
- [ ] 8.5 Roadmap currency: in `docs/development/ROADMAP.md`, Goal 8, remove this
  change's gap row from the open-gap table and its name from "Done when"'s list as the
  goal's text requires, and state in the goal's current state what landed: the
  revision ruled by the dispute authority, netted, and observed live; the list's
  `filing_unanswered`; the leading physical pass; the site's sends held as lane steps;
  the remaining rate rows as lane-double evidence in the lanes D9 names. Name the
  update in the design promotion record.
- [ ] 8.6 Campaign index currency: update this change's row in
  `openspec/changes/README.md` and the Goal 8 campaign's dependency graph, and run
  `make check-change-index`; name the update in the design promotion record.
- [ ] 8.7 Packaging: run `make check-packaging` and resolve every failure; run
  `make check-architecture-change CHANGE=converge-ongoing-compute-leases`; the change
  touches no `.agents/`, `.claude/` or `.codex/` path, so `make check-agent-skills` is
  not owed.
- [ ] 8.8 End-to-end pipeline: record the pipeline run the latest passing validation
  gathered, its result, and the scenarios that exercise this change — the markers named
  in sections 1–6 — from that validation's record, and the coordinator's live evidence
  (section 7); a run that could not be made is recorded as unrun with its cause.
- [ ] 8.9 Promotion: write the permanent documents and complete the design promotion
  record:
  - `openspec/specs/deal-lifecycle/architecture.md`, "External authorities": what SCM
    relies on the dispute authority for, R1–R4, without naming where they are built;
    "One end instant, transactional admission": the leading physical pass and
    `filing_unanswered`; and the promoted diagrams cited (D6, D7, D11, D12);
  - `openspec/specs/physical-provisioning/architecture.md`, "Lease-end report delivery"
    and "Operator events": the pause holding inline delivery, and the
    capacity-reservation watchdog's controls (D8);
  - `openspec/specs/test-compatibility/architecture.md`, "The in-lane mediation
    double" and "Lane time and the doubles' controls": rulings programmed from the
    producer's traces, and the lanes' holds of the site's sends (D8, D12);
  - `docs/development/TESTING.md`, "The canonical compute deal" and "Live
    verification": the rows by lane, the lane-only setup option, and the revision's
    live scenario with its coordinator-supplied evidence (D9, D10, D14);
  - `docs/operator-handbook.md`: "A deal ending on a pending release" and "Draining
    payment deals before a receipt key change", step 3, with `filing_unanswered`;
    "What each dispute outcome shows", a deal a 0.4.0 storefront left repair required
    on a revision and how to raise it with the dispute authority by hand; "Operator
    events", that pausing event delivery holds inline delivery too (D3, D6, D8, D11);
  - `docs/development/diagrams/`: pairs 00, 02, 03 and 05, redrawn to the design and
    regenerated from their sources, promoted from the change's `diagrams/` (D12);
  - the guidance written in section 4 confirmed as current (D8);
  - `openspec/specs/deal-lifecycle/spec.md`, `openspec/specs/physical-provisioning/spec.md`
    and `openspec/specs/test-compatibility/spec.md` are written by the archive from
    the deltas, and named in the record.
  None of the three capabilities has an `index.md`, so no index entry is owed; run
  `make check-spec-index CHANGE=converge-ongoing-compute-leases`.
- [ ] 8.10 Guidance placement: read the guidance sections section 4 wrote and any
  promotion touched against the layer test — the rule in `system-tests.md` holds in any
  repository, its instance here in `deterministic-tests.md` — and run
  `make check-guidance`.
- [ ] 8.11 Documentation citations: run `make check-doc-citations
  CHANGE=converge-ongoing-compute-leases` and resolve every match, then
  `change-workflow openspec validate converge-ongoing-compute-leases --strict`.
- [ ] 8.12 Archival: `change-workflow openspec archive converge-ongoing-compute-leases -y`,
  merging the `deal-lifecycle`, `physical-provisioning` and `test-compatibility` deltas.
