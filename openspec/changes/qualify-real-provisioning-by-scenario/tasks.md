# Tasks

Planned against the design settled in `design.md` and advanced by
`reviews/31-design.triage.md`; replanned from section 2 onwards against D22's revised
cadence and D23, advanced by `reviews/44-design.triage.md`. Section 1 is implemented as
first planned. The buyer-purchase section, first numbered 2, stopped before its first task
under its settlement-wait rule; it is replanned as section 3, its stop notes kept there,
behind a new section 2 that answers the stop (D23), and every later section moves up one
number. Section numbers inside section 1's notes and handoff are the first plan's: their
"section 2" is now section 3.

Every implementation task answers to a decision (D1–D10, D12, D15–D23), a delta
requirement under `specs/`, or a repository obligation cited at the task:
`openspec/README.md#plan-closeout-requirements`, the task rules in `openspec/config.yaml`,
`docs/development/TESTING.md`'s level definitions, `docs/development/RELEASING.md`'s
versioning policy, and `AGENTS.md`.

Test levels follow `docs/development/TESTING.md`: unit (including the e2e harness's
source checks, which read a scenario module without collecting it); library integration;
application integration (an in-process app through its typed client); and system (the
`e2e-tests` markers).

The sections follow D22's cadence. Sections 1–6 are the local and product round:
section 1 keys the shared post-settlement stages on the settlement reference (D15);
section 2 moves the settle wait's resolution into the settlement runtime kit and binds the
three storefronts to it (D23); section 3 adds the buyer-purchase stage set and restructures
the bare-metal payment purchase onto it (D16, D4, D10); section 4 adds the VM lane's
`market buy` purchase (D17, D3); section 5 adds the real VM listing helper (D2); section 6
adds the host diagnostics job (D5). Sections 7–8 are the external round: section 7 the
target fields and the admission-log reader (D9, D8), section 8 the three qualification
modules (D1, D3, D5, D6, D8, D9, D10). Section 9 is the closeout. Each section needs only
the sections before it. No dependency gates implementation: `add-mvp-payments-lane-double`
is archived (D20). D18 owes no task: the chart CA option and the kit's transport rule
already serve a deployment.

Return-to-design rules the design states, which a section's implementer applies rather
than working around: a buyer teardown that releases the lease outside `check_leases`
(D15); a reverse after the buyer's teardown refused (D16). Each stops the section and
returns the change to design; neither is settled in a task. The settlement-wait rule that
stopped the buyer-purchase section is answered by D23: once section 2 is complete, a
bare-metal payments deal the settle wait does not resolve by its negotiation is a defect
of section 2, not a design question.

Permanent specifications, `TESTING.md`, `ARCHITECTURE.md`, the runbook and the roadmap are
written at closeout; a section writes only the package and harness documentation its code
needs (the VM IaC README entry, the target example, `e2e-tests/README.md`'s marker list).

## 1. Shared post-settlement stages keyed on the settlement reference

Delivers D15: `09a`, `09b`, `09c`, `10a`, `10b`, `11a` and `11b` read the deal's
settlement reference and the handoff state D15's table names instead of
`real_escrow_uid` and `_evaluate_settle_host_id`, with every existing compute lane
unchanged in behaviour (test-compatibility delta, MODIFIED "The canonical compute deal's
shared stages are defined once", its shared-stage paragraph and input-independence rule).

Files: `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`; the stages' existing
writers and readers in `e2e-tests/tests/e2e/roles/scenarios/vms/{test_full_deal.py,
test_real_provisioning_deal.py, real_compute_deal_driver.py, compute_deal_driver.py}` and
`.../bare_metal/{test_bare_metal_mock_deal.py, test_real_provisioning_deal.py,
real_compute_deal_driver.py, compute_deal_driver.py}`; `e2e-tests/tests/unit/{test_compute_deal_stages.py,
stage_sources.py, test_real_vm_lane.py, test_real_bare_metal_lane.py}`.

- [x] 1.1 The settlement reference (D15). `ComputeDealState` gains `settlement_ref`, the
  reference the shared stages from fulfillment onwards read: `Stage07_OnChainEscrow`
  writes it beside `real_escrow_uid` (the escrow), and section 2's purchase stages write
  the payments negotiation. `09b` waits on it (`wait_for_settlement`), `09c`, `09c2`,
  `10a` and the logs require and name it, and `11b` names its re-reservation
  `f"{settlement_ref}-reuse"`. The Alkahest-only stages (`07a`–`08b2`) keep reading
  `real_escrow_uid`. Unit, in `test_compute_deal_stages.py`: no stage from `09a` onwards
  requires or reads `real_escrow_uid`.
  Done. `11b` also requires `settlement_ref`, and `10a`, `10b`, `11a` and `11b` gained a
  log line naming the deal identifiers they read (none had one; no test reads a log
  line). Unit (source check):
  `test_no_stage_from_fulfillment_onwards_reads_the_escrow` passes; the 09b case in
  `test_real_vm_lane.py` constructs `settlement_ref`. The Alkahest drivers
  (`vms/compute_deal_driver.py`, both `real_compute_deal_driver.py`) still read
  `real_escrow_uid` in `settle_dispatched`, `assert_delivery` (VM: settle status and the
  primary escrow), bare metal's `lease_view` and both real drivers' recovery: those are
  the Alkahest set's driver parts, which a purchase driver replaces, not stage bodies, so
  only the stage bodies' own source is escrow-free, which is what the check reads. The
  reference is written by a stage (07), as this task says, where D15 and the delta say
  "the driver supplies" it: an unreconciled wording for triage, not a behaviour gap.
  Reconciled since: D15 and the delta now say an earlier stage writes it.
- [x] 1.2 The expected host (D15's table). `_evaluate_settle_host_id` becomes
  `expected_host_id` for every writer and reader: `08a` writes it, `08c`, `09c`, the VM
  real module's previewed-host check (`test_real_provisioning_deal.py:443`) and the
  bare-metal real module's (`:273`) read it, and `test_real_vm_lane.py` and
  `test_real_bare_metal_lane.py` construct it. Unit: the renamed cases pass, and a
  source check finds no remaining `_evaluate_settle_host_id`.
  Done; `09c` now also requires `expected_host_id`, and its failure message names the
  expected host rather than 08a's preview. Unit: the renamed preflight cases in
  `test_real_vm_lane.py` and `test_real_bare_metal_lane.py` pass. Differed from the plan:
  no source check for the former name was kept. One was written, and the fresh-context
  check rightly read it as a tombstone (it guards a rename, and had to split the name to
  miss itself). The existing checks hold the invariant instead:
  `test_the_stages_use_only_declared_fields` and `test_a_lane_stage_uses_only_its_states_fields`
  refuse an undeclared field in a stage, and a dataclass refuses one at construction; a
  search of `e2e-tests` at commit time found the former name nowhere.
- [x] 1.3 The handoff is checked from source (delta: each shared input written
  independently of the lease under check). `test_compute_deal_stages.py` asserts, per
  lane row, that every state field a shared stage from `09a` onwards requires is written
  by an earlier stage of that lane — the table's `fulfillment_id`,
  `_create_job_completed`, `expected_host_id`, `teardown_fulfillment_id`,
  `_teardown_job_completed` and `settlement_ref` — and by no stage that reads the lease
  it is compared with. Unit: a lane row whose only writer of `expected_host_id` reads the
  lease fails the check (a constructed source in the test).
  Done as `handoff_faults` over a lane's running stages, with `HANDOFF` (the table's six
  fields) and `COMPARED_WITH_THE_LEASE`. Only `expected_host_id` is compared with the
  lease (`09c`, against its `host_id`), so only its writers are held to not reading the
  lease; `teardown_fulfillment_id` is *read from* the lease by expiry's `10b`, as D15's
  table says, and `11b` advances it rather than comparing it, so holding it to the rule
  would fail the Alkahest set it describes. "Reads the lease" is read from the writer's
  own source, as the mock-gate check is: an attribute named `lease_view`, `deal_lease`,
  `get_lease`, `backdate` or `truncate_lease` anywhere in it. A lease reached through a
  helper the writer calls is not seen, and a writer naming one of those for another
  purpose is refused. The "written by an earlier stage" half overlaps
  `test_every_prerequisite_is_produced_by_an_earlier_stage`; it is kept so the handoff
  rows read as one check. Unit (source checks):
  `test_the_handoff_is_what_the_stages_from_fulfillment_onwards_read` keeps the table
  honest; `test_each_handoff_is_written_earlier_and_independently_of_the_lease` passes
  for the four rows (`vms`, `bare_metal`, `vms_real`, `bare_metal_real`); the
  constructed-source case fails for a writer reading the host through the driver's
  lease view or the provisioning service's `get_lease`, and passes for one reading the
  driver's declared host. Section 2 adds the bare-metal purchase as a row.
- [x] 1.4 **Verification checkpoint.** Unit: `make test-e2e-unit`, with
  `test_compute_deal_stages.py`, `test_real_vm_lane.py`, `test_real_bare_metal_lane.py`
  and the other stage-source suites. Run `make test` and `make check-comment-hygiene`.
  End-to-end: `e2e_deal` and `e2e_deal_buyer_cli` (VM lane) and `e2e_bare_metal_mock_deal`
  (bare-metal lane) run every re-keyed shared stage; `e2e_vm_real_provisioning` and
  `e2e_bare_metal_real_provisioning` run them too but are in no lane, so their unit
  suites are this section's evidence for the real lanes.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the re-keyed
  source checks.
  Unit: `make test-e2e-unit`, 563 passed (unit, including the stage-source checks). The
  first run failed 23 cases in `test_payments_helper.py` (`ca_bundle_path` refused as an
  unknown field): a stale `.dist` payments-kit wheel, unrelated to this section; `make
  dist-ci` rebuilt the wheelhouse and the rerun passed. `make test` passed (every unit
  and integration suite); `make check-comment-hygiene` passed.
  End-to-end scenarios, corrected: `e2e_deal` (VM lane, `test_full_deal.py`) and
  `e2e_bare_metal_mock_deal` (bare-metal lane) run every re-keyed shared stage.
  `e2e_deal_buyer_cli` does not: `test_full_deal_buyer_cli.py` declares its own stage
  classes rather than subclassing the shared ones, so it is no evidence for this section.
  The real modules are in no lane, as planned.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the re-keyed
  source checks (confirmed).

Handoff from section 1: `ComputeDealDriver.reserve_released_capacity` keeps its
`escrow_uid` keyword, the storefront's `admin_reserve_capacity` field it forwards; `11b`
passes it `f"{settlement_ref}-reuse"`. `HANDOFF_LANES` was not introduced: the handoff
check is parametrized over `ALL_LANES`, so section 2 adds its purchase row there or
parametrizes `handoff_faults` over a row list of its own, passing the purchase stages'
classes to `running_stages` beside `STAGES`. The 1.3 lease rule binds only
`expected_host_id`, so a purchase writer of `teardown_fulfillment_id` from delivery
status needs no exception.

## 2. The settle wait's resolution in the settlement runtime kit

Delivers D23: the settlement runtime kit's settle wait resolves a reference by its
settlement reference, then by its negotiation, for any mechanism, and owns its terminal
states; the VM, bare-metal and API-credit storefronts bind it with their settlement-evidence
lookups and delivery status, and the opaque `settle_status`/`is_terminal` form is removed
(settlement-servicing delta, ADDED "The settle wait resolves a settlement by its reference
or its negotiation", every scenario).

Files: `kit/settlement-runtime/src/market_settlement_runtime/{admin_routes.py,
__init__.py}` and `kit/settlement-runtime/tests/unit/test_admin_routes.py`;
`domains/vms/storefront/src/market_storefront/{controllers/settle_controller.py,
payment_repository.py}` and `domains/vms/storefront/tests/integration/test_settle_controller.py`;
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/{deal_controls.py,
sqlite_client.py}` and `domains/bare_metal/storefront/tests/test_deal_controls.py`;
`domains/apicredits/storefront/src/apicredits_storefront/{controllers/settle_controller.py,
settlement_repository.py, utils/sqlite_client.py}` and its settle-wait tests
(`domains/apicredits/storefront/tests/integration/test_force_accept_api.py`); every
`pyproject.toml` whose version or pin on `arkhai-kit-settlement-runtime` moves, and every
lock `make lock` rewrites.

- [x] 2.1 The kit's resolution (D23). `SettlementAdminRouteService` takes the domain's two
  settlement-evidence lookups — by settlement reference and by negotiation, each returning
  `market_core.SettlementEvidence` or `None` — and its delivery status for a resolved
  settlement, in place of `settle_status` and `is_terminal`, which are removed. The wait
  resolves a reference by the settlement reference first, then by the negotiation; ends on
  `ready` or `failed`; treats an unresolved reference as a poll that found nothing
  terminal; and keeps the failed-read rule (an exception from a lookup or the delivery
  status is a failed read; a `LookupError` or `SettlementAdminRouteError` is an answer),
  the deadline and the injected `poll_seconds` and `clock`. The resolution is a public
  operation of the kit, exported in `__all__`. The names are fixed here; D23's are
  illustrative. Unit (`test_admin_routes.py`): a reference some evidence records resolves
  to it without the negotiation lookup being consulted; a negotiation resolves when no
  evidence records it as a reference; an unresolved reference polls to the deadline and
  reports `ready: false`; `ready` and `failed` end the wait and another status does not; a
  failing lookup is polled through and reported as `last_error` at the deadline; a refusal
  raised by the delivery status ends the wait; the existing failed-read cases pass on the
  new form.
  Done. The names: `SettlementAdminRouteService(settlements=SettlementLookup(by_reference=…,
  by_negotiation=…), delivery_status=…)`; `SettlementLookup.resolve(reference)` is the
  public resolution; `SettlementEvidenceLookup` and `DeliveryStatusHook` are the hook
  protocols (positional-only, so a binder names its parameter freely);
  `TERMINAL_SETTLEMENT_STATUSES` is `{"ready", "failed"}`. All are in both `__all__`s.
  Each poll resolves afresh, since evidence or its reference may appear while the wait
  runs. A refusal raised by a lookup ends the wait too, as the failed-read rule says.
  `wait`'s parameter is renamed `reference`; every caller passes it positionally. Unit
  (`test_admin_routes.py`, injected clock, `poll_seconds=0`): every case the task names
  passes, plus evidence recorded mid-wait being resolved and a refusal raised by a lookup;
  `make test-kits` passed (settlement runtime 186 before the fresh-context fixes, then
  every kit suite).
- [x] 2.2 The VM storefront's binding (D23). A by-reference lookup on
  `vm_settlement_evidence.settlement_ref` beside `load_vm_settlement_evidence`; the delivery
  status reads the delivery record by the evidence's negotiation, as `load_vm_delivery`
  reports it (an ended deal included), and reports the evidence's own status when there is
  none, as a refund before delivery leaves it. `provisioning_job_id` and `fulfillment_id` in
  the wait's response come from the delivery record. The escrow-row fallback is not carried
  over: an escrow from before `vm_settlement_evidence` has no evidence and is unsupported
  (design review 44's triage, F1). The buyer-facing status route keeps
  `load_vm_settlement_job`, which D23 leaves alone. Application integration
  (`test_settle_controller.py`, through the typed admin client): an `arkhai.payments.v1`
  deal waited on by its negotiation and by its transaction reports ready once its delivery
  is ready; an Alkahest deal waited on by its escrow reports as it did; a deal refunded
  before delivery is not terminal.
  Done: `load_vm_settlement_evidence_by_ref` and `load_vm_delivery_status` in
  `payment_repository.py`, bound in `AdminSettleController`. With no delivery record the
  delivery status reports the evidence's status (`pending`, `verified`, `refunding`,
  `refunded`: none terminal). Application integration (`TestSettleWait`, typed admin
  client): the payments deal waited on by negotiation and by transaction reports ready
  with the delivery record's `provisioning_job_id`; the Alkahest deal waited on by its
  escrow reports `failed` from its delivery record with no `escrows` row. Differed from
  the plan: "refunded before delivery is not terminal" is proved one level lower, by
  `test_a_deal_without_delivery_reports_its_evidence_status_to_the_wait` (the
  repository against its real SQLite database, outside the app), because the
  controller's wait runs on the real clock and a wait that must not end would spend its
  deadline (`TESTING.md`, "Tests wait on events, never on durations"); that a
  non-terminal status keeps the wait polling is 2.1's unit case. `make test-storefront`:
  1215 unit and 530 integration passed.
- [x] 2.3 The bare-metal storefront's binding (D23). The lookups read
  `bare_metal_settlement_records` by reference and by negotiation through the existing
  queries, adapted to `SettlementEvidence`. The delivery status keeps today's hook body,
  keyed on the evidence's negotiation: the lifecycle, the live fulfillment read and its
  delivery-conflict answer, the mapping to `ready` and `failed`, and the
  servicing-obligation wake, which runs only for evidence whose source names an
  `obligation_ref`. Application integration (`tests/test_deal_controls.py`, through the
  typed admin client, as `test_wait_returns_once_the_settled_lease_is_active` does): an
  `arkhai.payments.v1` deal waited on by its negotiation and by its transaction reports
  ready once its fulfillment is active, and wakes no obligation; the Alkahest cases — ready
  once the settled lease is active, a delivery conflict answered as the fulfillment reads
  answer it — pass unchanged.
  Done in `deal_controls.py`: `_settlement_evidence` adapts a record; the wake now reads
  `source.obligation_ref` (the Alkahest paths write it, `settlement_stages.py:417, 518`)
  and calls the worker's `wake` directly instead of matching the aggregate's obligations
  by escrow. Before a fulfillment decides, the record's own status is reported
  (`accepted`, `settlement_verified`, as the escrow row's status was before). Application
  integration (`tests/test_deal_controls.py`):
  `test_wait_resolves_a_payments_deal_by_its_negotiation_and_its_transaction` settles
  through the buyer's typed `settle_agreement`, then waits on the negotiation and on the
  transaction through the typed admin client until ready. Its non-terminal waits (before
  payment, and before the fulfillment is active) run through
  `settlement_admin_routes(runtime, poll_seconds=0.0, clock=…)` on a clock that passes a
  second a read, not through the client, for the same real-clock reason as 2.2. "Wakes no
  obligation" is shown as no obligation adopted and a stepped servicing cycle processing
  nothing; the old code would not have woken one either, so this guards the payments path
  rather than discriminating the wake's new condition, which the existing lease-active
  test's `processed == 1` covers for Alkahest. The two Alkahest cases pass unchanged. The
  payments setup moved out of `test_payment_evidence_gates_replay_and_rechecks_receipt_after_restart`
  into `_payment_deal` in `test_http_settlement.py`, shared by both. `make test-bare-metal`:
  storefront 590 passed.
- [x] 2.4 The API-credit storefront's binding (D23). A by-reference lookup on
  `api_credit_settlement_evidence.settlement_ref` beside `SettlementRepository.get`; the
  delivery status is its issuance progress by the evidence's negotiation. An Alkahest deal's
  escrow resolves by reference, as its evidence records it (D23). Application integration
  (its existing settle-wait cases, `test_force_accept_api.py`, through the typed admin
  client): a payments deal waited on by its negotiation and an Alkahest deal by its escrow
  report as they did.
  Done: `SettlementRepository.get_by_reference` (sharing `get`'s read and validation) and
  `SQLiteClient.load_settlement_evidence_by_ref`; the delivery status is
  `load_issuance_progress` under the evidence's negotiation, and the evidence's own status
  when issuance has not begun. The schema admits `failed` evidence, which would end a wait;
  nothing writes it today, and a failed settlement is one never to be delivered, so the
  comment states it as intended. Application integration (`test_force_accept_api.py`,
  typed admin client): the former case seeded issuance progress with no evidence, which
  the kit's resolution rightly no longer answers, so it is replaced by
  `test_settle_wait_reports_a_payments_deal_by_its_negotiation` (waited on by negotiation
  and by transaction) and `test_settle_wait_reports_an_alkahest_deal_by_its_escrow`; the
  evidence is set up directly, as no route writes it without a payment or an escrow.
  `make test-apicredits`: storefront 255 passed.
- [x] 2.5 Versions and locks (D23; `docs/development/RELEASING.md`, "Versioning policy";
  `AGENTS.md`, "Package and dependency discipline"). `arkhai-kit-settlement-runtime` takes
  a minor bump against `dev`, its constructor's incompatible change; each of the three
  storefronts is bumped once against `dev` as the policy reads its change, and raises its
  lower bound on the kit to the new minor. Every exact pin on the kit moves with it —
  today `core/buyer`, `kit/config`, `kit/contact-exchange`, `kit/arkhai-payments`,
  `domains/vms/buyer` and `domains/bare_metal/buyer` — each package whose `pyproject.toml`
  changes bumped once against `dev`. Run `make check-uv-version` and `make lock`, and
  commit every lock it rewrites.
  Done. No package was already bumped on the branch. Kit 0.6.0 → 0.7.0. Storefronts, each
  minor for the references its wait now answers: VM 0.26.0 → 0.27.0, bare metal 0.26.0 →
  0.27.0, API credits 0.19.0 → 0.20.0, each `arkhai-kit-settlement-runtime>=0.7.0`. The six
  exact pinners, patch for the pin alone: `core/buyer` 0.6.1, `kit/config` 0.5.1,
  `kit/contact-exchange` 0.4.1, `kit/arkhai-payments` 0.6.1, `domains/vms/buyer` 0.10.2,
  `domains/bare_metal/buyer` 0.7.2. The pins those bumps move stay inside the set:
  contact-exchange (both storefronts' and both buyers'), arkhai-payments and core-buyer
  (bare-metal storefront and buyer), and the VM storefront's pin on the bare-metal
  storefront. `make check-uv-version` passed; `make lock` rewrote 29 locks, only moving
  versions.
- [x] 2.6 **Verification checkpoint.** Unit: `make test-kits` (the settlement runtime's
  admin-route cases). Application integration: `make test-storefront` (VM),
  `make test-bare-metal` (the bare-metal storefront), `make test-apicredits`. Run
  `make test`, `make check-packaging` (2.5 changes versions and locks) and
  `make check-comment-hygiene`.
  End-to-end: the lanes' existing settle-wait callers exercise the kit's resolution —
  `e2e_deal` (VM lane, the shared `09b` by escrow), `e2e_vm_payment_deal` (VM lane, a
  payments deal by its negotiation) and `e2e_bare_metal_mock_deal` (bare-metal lane, `09b`
  by escrow). No API-credit scenario calls the settle wait; its application-integration
  cases are its evidence. Section 3's `e2e_bare_metal_payment_deal` is the first scenario
  to wait on a bare-metal payments deal.
  Owed by validation: `tests.yml`, jobs `test · test-kits`, `test · test-storefront`,
  `test · test-bare-metal` and `test · test-apicredits` — pass with the kit's resolution
  and the three storefronts' bindings.
  Unit: `make test-kits` passed (every kit, the settlement runtime's admin-route cases
  among them). Application integration: `make test-storefront` (1215 unit, 530
  integration), `make test-bare-metal` (storefront 590) and `make test-apicredits`
  (storefront 255) passed. `make test` passed twice, the second time on the final tree.
  `make check-packaging` passed after the fresh-context fixes to the kit's protocols,
  tests and comments, which changed no version or lock. `make check-change` passed all 12
  checks, comment hygiene, version bumps and local imports among them. Before the kit's
  wheel was rebuilt, the storefront suites failed to import `SettlementLookup` from the
  stale `.dist` wheel; `make dist-ci`, then `make lock`, rebuilt it.
  End-to-end scenarios, confirmed and extended: `e2e_deal` (the shared `09b` by escrow),
  `e2e_deal_buyer_cli` (its own stage waits by escrow) and `e2e_non_erc20_settlement` (by
  escrow), all VM lane, resolve by reference, since VM Alkahest evidence records the escrow
  as its settlement reference (`settlement_stages.py`, `reference=source["escrow_uid"]`);
  `e2e_vm_payment_deal` (VM lane) by negotiation; `e2e_bare_metal_mock_deal`
  (bare-metal lane, `09b` by escrow) by reference. No API-credit scenario calls the wait.
  Owed by validation: `tests.yml`, jobs `test · test-kits`, `test · test-storefront`,
  `test · test-bare-metal` and `test · test-apicredits` — pass with the kit's resolution
  and the three storefronts' bindings (confirmed).

Handoff from section 2:

- **For section 3.** `09b` may wait on a bare-metal payments deal by its negotiation (or
  by its transaction). The bare-metal storefront reports `settlement_verified` while the
  fulfillment is not yet active, and `ready` from the live fulfillment read once it is.
  `_payment_deal` in the bare-metal storefront's `test_http_settlement.py` is a ready
  accepted-payments-deal fixture for storefront tests, not for e2e.
- **Real-clock waits in storefront tests.** None of the three admin wait routes takes an
  injected clock, and the route refuses a zero timeout. So a storefront test proves a
  non-terminal answer through the route service with a ticking clock (bare metal's
  `settlement_admin_routes(runtime, poll_seconds=…, clock=…)`), or through the delivery
  status read directly (VM's `load_vm_delivery_status`). Through the typed client it waits
  only on what ends on the first poll. The bare-metal file's existing Alkahest wait tests
  still spend `timeout=0.1` waits; they predate this section and were left alone.
- **Outside the plan.** `tasks.md` named section 3's two new files by full path, which the
  citation check rejects until they exist; those mentions in sections 3, 4 and 8 now name
  each file within its existing directory. Closeout's 9.9 gains the
  `settlement-servicing/architecture.md` settle-wait paragraph, whose sentence on bare
  metal's "settle-status read" names the removed hook, as the fresh-context check found.
- **Fresh-context check.** No blocking finding. Fixed: the real-clock deadlines in the new
  VM and bare-metal tests; positional-only hook protocols; a kit test that could spin
  forever if resolution regressed; import order; comments stating that `failed` evidence
  ends a wait on purpose (API credits, bare metal). Recorded rather than changed: the weak
  "wakes no obligation" discrimination (2.3's note says why).

## 3. The buyer-purchase stage set and the bare-metal lane purchase

Delivers the shared buyer-purchase stages (D1), with the payment-record and balance checks
(D4) and the bare-metal buyer-teardown ending (D15), and restructures
`test_bare_metal_payment_deal.py` onto them with its re-drive and refund as its own
stages, the buyer's teardown before the refund (D16, D10) (test-compatibility delta:
MODIFIED "A configured bare-metal payment purchase is qualified end to end"; MODIFIED
shared-stage requirement's scenario "A buyer purchase reaches fulfillment"; ADDED "A
compute buyer purchase settled through Arkhai payments runs in each compute lane", its
bare-metal scenarios, "A purchase is checked against its payment records" and "The
buyer's delivery-end filing reaches no authority"). Replanned against the reviewed
design: first numbered 2, it now follows section 2, whose settle wait resolves the
purchase's negotiation.

Files: a new `buyer_purchase_stages.py` in `e2e-tests/tests/e2e/roles/helpers/`; a bare-metal
purchase driver in `e2e-tests/tests/e2e/roles/scenarios/bare_metal/` (beside
`compute_deal_driver.py`); `.../bare_metal/test_bare_metal_payment_deal.py`;
`e2e-tests/tests/e2e/roles/helpers/payments.py` if the balance read needs a helper; a new
`test_buyer_purchase_stages.py` in `e2e-tests/tests/unit/`; `e2e-tests/tests/unit/test_compute_deal_stages.py`
(the purchase's handoff row); `e2e-tests/pyproject.toml`'s `e2e_bare_metal_payment_deal`
description.

- [ ] 3.1 The stage set (D1, D15's table). `buyer_purchase_stages.py` defines, like
  `compute_deal_stages.py`, the stages every scenario buying through the shipped buyer
  runs: hold the loops; discover through the purchase profile; buy through the domain's
  command (`market buy` or `market bare-metal buy`), the mock gates around it in a mock
  lane (`07a` armed before, `08b2` after dispatch); correlate the run's events (Agreement,
  settlement data bound to it, transaction, fulfillment); then the shared `09a`, `09b`,
  `09c` from `compute_deal_stages.py`, `09b` waiting on the negotiation through the settle
  wait section 2 unified. The purchase stages write `settlement_ref` (the negotiation),
  `fulfillment_id`, `expected_host_id` (the driver's declared host) and
  `seller_listing_id`. A per-domain purchase driver supplies the command, its arguments
  and the buyer's configuration; each stage logs the identifiers it reads (buyer run,
  Agreement, transaction, reservation, jobs). The purchase's row joins the handoff check
  of 1.3 (section 1's handoff note says how).
- [ ] 3.2 Payment records (D4). A stage checks each transaction: bound to its Agreement,
  its receipt over that mandate, its snapshot naming the configured payer and payee, its
  parts' gross equal to the Agreement's price for its duration. The balance sum check reads
  the payer's own balance through `PaymentsClient.get_balance` with the buyer's token
  before the first purchase and after the last approval, and asserts the drop in
  `available` equals the sum of the scenario's own transactions' debits, logging the
  dedicated-account precondition beside the result.
- [ ] 3.3 The buyer-teardown ending (D15, D16, D10). A shared stage runs
  `market bare-metal teardown --run-id <run>`, records `teardown_fulfillment_id` from the
  deal's fulfillment as delivery status reports it, and ends where `11b` starts; in a mock
  lane `09c2` arms the teardown gate before it and `11a2` drains after it. The delivery-end
  filing's `Unknown` outcome at the unanswerable authority neither fails the stage nor is
  read as delivery, access-end or refund evidence. If a buyer teardown releases the lease
  outside `check_leases`, the section stops and the change returns to design (D15).
- [ ] 3.4 The bare-metal lane purchase (D16). `test_bare_metal_payment_deal.py` runs, in
  order: the purchase stages and `09a`–`09c`; its re-drive of the run's commit (its own
  stage, as today); the shared buyer-teardown ending; the seller refund of the still-held
  payment (its own stage, the snapshot showing every part reversed); `11b`. Its
  compensating cleanup (`PurchaseCompensation`) and the mock rules' removal are unchanged.
  The module's wall-clock poll of the buyer's fulfillment status goes with the step `09b`
  replaces. If the reverse after the teardown is refused, the section stops and the change
  returns to design (D16). The marker's description in `e2e-tests/pyproject.toml` says
  the buyer's CLI teardown precedes the refund.
- [ ] 3.5 The source check (D1; delta "defined once"). `test_buyer_purchase_stages.py`, on
  the pattern of `test_compute_deal_stages.py` and `stage_sources.py`: every scenario
  buying through the shipped buyer declares the purchase stages in order without replacing
  a body, inserts only its own stages between them, and runs the shared ending its lease
  ends by; the bare-metal lane purchase is one row. Unit: a constructed module replacing a
  shared body, or running the buyer-teardown ending and the expiry stages both, fails.
- [ ] 3.6 **Verification checkpoint.** Unit: `make test-e2e-unit`, with
  `test_buyer_purchase_stages.py` and `test_compute_deal_stages.py`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_bare_metal_payment_deal` (bare-metal lane) runs the purchase stages,
  the shared post-settlement stages with `09b` on a payments deal, the buyer-teardown
  ending and the refund after it.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the purchase
  source check.

Stopped before 2.1 (now 3.1), under that task's then return-to-design rule (D15): `09b`'s
settlement wait does not resolve the bare-metal payments deal, by its negotiation or by any
reference. Nothing of the section was implemented; no task is checked. D23 answers it.

- **The evidence.** `09b` calls `storefront_admin_client.wait_for_settlement(settlement_ref)`,
  `GET /api/v1/admin/settle/{ref}/wait`. The bare-metal storefront serves it
  (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py:1315-1339`)
  through `settlement_admin_routes`, whose `settle_status` hook
  (`deal_controls.py:133-136`) reads `runtime.db.load_escrow(escrow_uid=ref)`, a plain
  lookup in the `escrows` table (`core/storefront/src/core_storefront/sqlite_client.py:3385-3402`),
  and returns `None` when there is no row. The bare-metal storefront writes an `escrows`
  row only on the Alkahest verified path (`settlement_stages.py:495`); an
  `arkhai.payments.v1` deal writes none. The wait
  (`kit/settlement-runtime/src/market_settlement_runtime/admin_routes.py:92-125`) treats
  `None` as nothing terminal and polls until its timeout, so `09b` would fail every run
  with `ready=False`, whether the reference is the negotiation or the transaction.
- **Where the design's premise held.** The VM storefront's wait reads
  `load_vm_settlement_job(reference=…)` (`domains/vms/storefront/src/market_storefront/controllers/settle_controller.py:201-202`),
  the reference D15 relied on, so section 3's VM purchase is not affected. The
  bare-metal buyer-facing status route already resolves a payments deal, by its
  settlement record's reference or its negotiation (`api.py:913-915`); only the admin
  wait does not. The other input `09c` needs on this path is available: `DealLease`
  finds a hold by negotiation (`e2e-tests/tests/e2e/roles/helpers/compute_deal.py:442-444`),
  so a purchase driver's `lease_view` needs nothing new.
- **What the design must decide.** (1) The bare-metal storefront's admin settle wait
  resolves a settlement as its buyer status route does — by its settlement record's
  reference, then its negotiation — reporting from the deal's fulfillment lifecycle as
  it does now: a small product change in the bare-metal storefront, against the
  proposal's "no payment or provisioning behaviour change", with a storefront unit or
  application-integration test, and a version bump. (2) `09b`'s readiness read becomes a
  driver part (`ComputeDealDriver`), the Alkahest drivers keeping the admin wait and the
  purchase driver reading the buyer's fulfillment status: no product change, but the
  wait leaves the shared body and the stage's "server-side long-poll" becomes a
  driver's choice. (3) The bare-metal purchase keeps its own readiness stage in place of
  `09b`, and runs `09a` and `09c` shared: against D15's single-body rule for `09b`.
  The implementer's recommendation is (1): the admin wait is the readiness oracle every
  other shared stage's reader assumes, the buyer route already has the lookup it needs,
  and the gap is the storefront's, not the scenario's.
- **What the design decided.** D23: neither a bare-metal patch nor (2) or (3); the
  settle wait's resolution moves into the settlement runtime kit for all three
  storefronts, which section 2 implements. "Section 3's VM purchase" above is now
  section 4.

## 4. The VM lane purchase through `market buy`

Delivers the VM lane's buyer purchase in `arkhai.payments.v1`, its own resource, host and
pool, ending by back-dating and a stepped watchdog cycle through the shared expiry stages
(D17, D3, D15) (test-compatibility delta ADDED "A compute buyer purchase settled through
Arkhai payments runs in each compute lane", scenario "A VM lane purchase completes").
Replanned against the reviewed design: first numbered 3.

Files: a VM purchase driver in `e2e-tests/tests/e2e/roles/scenarios/vms/` (beside
`compute_deal_driver.py`); a new `.../vms/test_vm_payment_purchase.py`;
`.../vms/host_registry.py` (its host and pool); `e2e-tests/pyproject.toml` (marker
`e2e_vm_payment_purchase`); `e2e-tests/Makefile` (`E2E_MODULE`);
section 3's `test_buyer_purchase_stages.py` (its row); `e2e-tests/README.md`'s
marker list.

- [ ] 4.1 The VM purchase driver and module (D17). The module declares its own resource id,
  registers its host enabled and its pool in `host_registry.py` (as `E2E_PAYMENT_DEAL_HOST`
  and `E2E_PAYMENT_DEAL_POOL_ID` do), and creates its listing with an
  `arkhai.payments.v1` settlement through the seller client. It runs the purchase stages
  with `market buy`, the buyer CLI polling its settlement while the stages step
  convergence, as `test_full_deal_buyer_cli.py` does, then `09a`–`09c`, the payment-record
  and balance checks, `09c2`, `10a`, `10b`, `11a`, `11a2` and `11b`. It holds the loops for
  the whole module.
- [ ] 4.2 The expiry ending on a payments deal (D17). The back-dated lease, stepped with
  the watchdog held, tears the guest down and releases capacity while the pinned authority
  is unreachable; the module's `11b` asserts it. A stall caused by the unreachable
  authority is product behaviour the change does not alter, and stops the section for the
  owner rather than being worked around.
- [ ] 4.3 Lane membership. `e2e_vm_payment_purchase` is registered in
  `e2e-tests/pyproject.toml` and added to `E2E_MODULE`; `test_buyer_purchase_stages.py`
  gains the VM row; `e2e-tests/README.md` lists the marker.
- [ ] 4.4 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_vm_payment_purchase` (VM lane) runs the purchase, the shared
  post-settlement stages and the expiry ending against the lane's payments double.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the VM row.

## 5. One listing offers every composed mechanism on a real resource

Delivers D2: one shared helper creates or adopts the real VM resource's listing, stating a
settlement for each mechanism the storefront reports ready, and adoption requires the
adopting module's own mechanism (test-compatibility delta ADDED "A real resource's listing
offers every composed mechanism"). Replanned against the reviewed design: first numbered 4.

Files: `e2e-tests/tests/e2e/roles/helpers/real_provisioning.py` (or a sibling helper
module); `e2e-tests/tests/e2e/roles/scenarios/vms/test_real_provisioning_deal.py` (its
listing stage, lines ~350–380); `e2e-tests/tests/unit/test_real_vm_lane.py`.

- [ ] 5.1 The helper (D2). Given the storefront's ready mechanisms, the target's resource
  and the module's own mechanism, it adopts the resource's existing listing when it offers
  that mechanism, fails naming the listing and its options when it does not (changing
  nothing), and otherwise creates the listing with one settlement per ready mechanism. The
  VM Alkahest real module's listing stage calls it. Bare metal needs no helper: its
  published options are the composed mechanisms (D2).
- [ ] 5.2 Unit, in `test_real_vm_lane.py`: creation states one settlement per ready
  mechanism; an Alkahest module and a payments module, in either order, adopt the same
  listing and create no second one; a listing lacking the adopting module's mechanism
  fails naming the listing and its options before any deal; a one-mechanism stack yields
  one option.
- [ ] 5.3 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_vm_real_provisioning` runs the helper but is in no lane; no pipeline
  marker covers it, and none is owed, since a real resource exists only on a target.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the helper's
  cases.

## 6. The host diagnostics VM operator job

Delivers D5's host diagnostics: the `host-diagnostics` playbook task, the operator action
and route, the mock profile's default output, and the operator client's `diagnose_host`
submission with the typed `HostDiagnostics.from_job_result` parse (physical-provisioning
delta ADDED "A VM host's diagnostics are read through an operator job"). Replanned against
the reviewed design: first numbered 5.

Files: `domains/vms/provisioning/iac/ansible/roles/vm-management/tasks/` (a new
`host-diagnostics.yml`, wired from `tasks/main.yml` and the
`playbooks/single-tenant/vm-operations.yaml` dispatch); `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/{codec.py,
bundle.py, controllers/vms_controller.py, services/host_operations_service.py,
services/mock_output.py}` and its request model; `domains/vms/provisioning/client/src/vm_provisioning_operator/{routes.py,
client.py, models.py, __init__.py}`; tests in
`provisioning/compute/service/tests/{unit/services/test_host_operations_service.py,
integration/test_hosts_api.py, integration/test_provisioning_client_endpoint_coverage.py,
unit/test_provisioning_client_contract.py}` and the adapter's own tests;
`domains/vms/provisioning/iac/scripts/validate_playbooks.sh` coverage if it enumerates
tasks; `domains/vms/provisioning/iac/README.md`; both packages' `pyproject.toml`; every
lock `make lock` rewrites.

- [ ] 6.1 The playbook task (D5). `host-diagnostics.yml` prints one fact for the action
  with boot ID, uptime, kernel, the count of running guests, and for
  `libvirtd.service`, `frpc-buyers.service` and the optional management unit: active
  state, invocation ID, main PID, restart count, active-enter time and result. The
  management unit arrives as a job parameter. The VM IaC README documents the action and
  its fact. Check: `make test-provisioning-iac` (syntax and the native gate's coverage).
- [ ] 6.2 The action (D5). A host-scoped action (`diagnose`), registered in `codec.py`'s
  result-fact and fact-action maps and `bundle.py`'s actions, submitted by
  `host_operations_service.py` beside `check` and routed by the controller. A
  `management_unit` not matching systemd's unit-name syntax is refused at submission, no
  job queued; an unknown host is the route's error. The mock profile's default output
  (`mock_output.py`) renders a fact from the job's parameters. Unit: the unit-name
  validation (valid names, a path, a space, an empty name). Application integration
  (`test_hosts_api.py`, through the typed client): a submitted job succeeds in the mock
  profile with a fact the parse accepts; an invalid unit is refused with no job queued.
- [ ] 6.3 The client (D5's interface). `diagnose_host(host_id, management_unit=None)` on
  `VmOperatorClient` and `SyncVmOperatorClient` returns the `JobSubmitResponse`, and the
  client gains no polling. `HostDiagnostics.from_job_result(result)` in
  `vm_provisioning_operator` returns the typed facts or raises a named error naming the
  missing or malformed field, returning no partial result. Unit: a well-formed result
  parsed; each missing field and a wrong-typed field refused naming it. The endpoint
  coverage and client contract tests include the new route.
- [ ] 6.4 Versions and locks (`docs/development/RELEASING.md`, "Versioning policy";
  `AGENTS.md`, "Package and dependency discipline"). Bump the adapter's and the client's
  versions once each against `dev`, raise any exact pin that moves, run
  `make check-uv-version` and `make lock`, and commit every lock it rewrites. A package
  section 2 already bumped is bumped again only if this section needs a larger bump.
- [ ] 6.5 **Verification checkpoint.** Unit and application integration:
  `make test-provisioning`, `make test-provisioning-adapter`, `make test-provisioning-iac`.
  Run `make test`, `make check-packaging` (6.4 changes versions and locks) and
  `make check-comment-hygiene`.
  End-to-end: no pipeline marker runs the job; section 8's observation 2 module, in no
  lane, is its first system-level caller. None is owed in the pipeline.
  Owed by validation: `tests.yml`, jobs `test · test-provisioning`,
  `test · test-provisioning-adapter` and `test · test-provisioning-iac` — pass with the
  new action, client and playbook task.

## 7. Target fields and the admission-log reader

Delivers the target's optional `management_unit` on a VM host and `admission_log` on relay
access (D5, D9), the admission-log reader and its comparison with the relay's lease record
(D9), and the per-observation outcome the qualification modules record (D8)
(test-compatibility delta ADDED "The real-provisioning target names diagnostics and
admission inputs"; the qualification requirement's scenarios "Grant admission is read from
the plugin's log" and "A topology input is absent"). Replanned against the reviewed design:
first numbered 6.

Files: `e2e-tests/src/e2e_harness/real_provisioning_target.py`; the target example
(`config-real-provisioning-target.yml.example`, under `e2e-tests/config/`); a new helper under
`e2e-tests/tests/e2e/roles/helpers/` for the admission log and observation outcomes;
`e2e-tests/tests/unit/test_real_provisioning_target.py` and a new unit test module for the
helper.

- [ ] 7.1 Target fields (D5, D9). `VmHost.management_unit: str | None`, checked against
  systemd's unit-name syntax; `RelayAccess.admission_log: str | None`, an absolute
  harness-local path validated as `CleanupOperator.key_path` is. Both join version 2
  without a bump; an older checkout refuses them by name as an unknown field. The target
  example shows both, commented as optional. Unit (`test_real_provisioning_target.py`): a
  valid unit and path accepted; an invalid unit and a relative or `..` path refused before
  any stage, naming the field.
- [ ] 7.2 The admission-log reader (D9). It reads the file's lines as the plugin's
  documented log contract (`tools/frp-grant-admission/README.md#the-log`) and, for one
  delivered lease, finds an `admit` line with `verified` true, `jti` equal to the
  reservation, `remote_port` equal to the lease record's `remote_port`, and `kid` equal to
  its `grant_key_id`, the record read through the relay's leases
  (`GET /api/v1/relays/{relay_id}/leases`). Unit: a matching line found; a line under the
  relay's newer active key but not the lease's recorded key refused; an earlier `admit`
  under a retired key ignored when the latest grant's line is present; a missing, unverified
  or mismatched line failing naming the lease.
- [ ] 7.3 Per-observation outcome (D8). Each qualification stage declares the observations
  that require it; at module end a hook logs each observation's outcome by D8's rule —
  made when every requiring stage passed, failed when one failed, unproven when none failed
  and one skipped, naming the skip's prerequisite — writing no file. Unit: observation 2
  recorded unproven naming `management_unit` when its diagnostics stage skipped and every
  other stage passed; observations 4 and 5 resolved independently in one module; a failure
  outranking a skip.
- [ ] 7.4 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: none; the fields and the reader are read by section 8's modules, in no
  lane. None is owed in the pipeline.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the target and
  helper cases.

## 8. The qualification modules

Delivers the three external-topology modules making observations 2, 4, 5 and 6 (D1, D3,
D5, D6, D8, D9, D10), each in no lane, blocked without the real-provisioning target and the
payments target (test-compatibility delta ADDED "An external-topology scenario extends a
locally verifiable scenario" and "Real-provisioning qualification scenarios make the owed
observations", every scenario of both). Replanned against the reviewed design: first
numbered 7.

Files: new modules under `e2e-tests/tests/e2e/roles/scenarios/vms/` (observation 2),
`.../bare_metal/` (observations 4 and 5), and one for observation 6 where both domains'
fixtures are reachable; their conftest fixtures; `e2e-tests/pyproject.toml` (markers
`e2e_vm_qualification`, `e2e_bare_metal_qualification`, `e2e_real_provisioning_reapply`);
section 3's `test_buyer_purchase_stages.py` (their rows) and a unit module for
their wiring; `e2e-tests/README.md`'s marker list.

- [ ] 8.1 Observation 2 (D1, D3, D5, D9). Two CPU-only VM purchases through the shared
  purchase stages on the target's host, the listing through section 5's helper. A
  heartbeat over SSH on the first guest runs across the second guest's create and
  teardown and shows no gap over five seconds; host diagnostics (section 6) are read before,
  during and after, and the pass criterion is D5's (the management unit keeps one
  invocation ID, stays active and adds no restarts; libvirtd adds no restarts, has no
  failed result, and keeps one invocation ID across the reads taken while the first guest
  runs), a changed invocation or a grown restart count failing the module naming the unit;
  both leases end through `10a`/`10b` back-dating and stepped watchdog cycles. Without
  `management_unit` the diagnostics' management reads skip naming it.
- [ ] 8.2 Observations 4 and 5 (D1, D6, D10, D16's ending). The normal cycle through the
  purchase stages and the buyer-teardown ending, then the successor and refusal cycle in
  the same module, using the first cycle's consumed UID: the reclaim meets the planted
  foreign descendant, is queued for retry with its error recorded and a next retry time,
  its log names the descendant, the lease stays `releasing`, and after fixture-only repair
  the same job completes. The cycle reuses the cleanup-qualification fixtures
  (`working_data_qualification.py`, `working_data_probe.py`). No GPU is checked.
- [ ] 8.3 Observation 6 (D5's consumed-UID read). It reapplies both hosts' canonical
  registrations and runs a publication cycle; existing listings are adopted with
  identities, states and pauses intact, no duplicate host, pool, resource, allocator or
  listing appears, unexpired relay quarantine is retained, and the consumed-UID history,
  read through the working-data operator route's `policy` operation before and after, is
  unchanged. It needs both hosts and reports a blocked skip naming the missing one.
- [ ] 8.4 Common to the three (D1, D8, D9, D10). Each module is in no lane, reports a
  blocked skip and writes nothing to the stack without both targets, reads the runner's
  `PAYMENTS` section (D19), holds the loops for the whole module, and never waits out the
  wall clock for a state it can step to. Every relayed lease (observations 2, 4 and 5)
  runs section 7's admission check, skipping naming `admission_log` without it. Each stage
  logs the identifiers it reads and declares the observations requiring it, so the
  module's outcomes are D8's. The delivery-end filing's `Unknown` never fails a stage. No
  module funds the payer: a payer that cannot approve fails the purchase naming the payer
  (D1's topology rule).
- [ ] 8.5 Wiring checks. Unit: each module registered under its marker in no lane
  (absent from every `E2E_*_MODULE`); the observation 2 and observations 4 and 5 modules
  as rows of the purchase source check, extending the purchase stages without replacing a
  body; a module with no target configured reporting a blocked skip before any stage
  (with injected settings). `e2e-tests/README.md` lists the three markers and how an
  operator runs them through `test-module`.
- [ ] 8.6 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_vm_qualification`, `e2e_bare_metal_qualification` and
  `e2e_real_provisioning_reapply` are in no lane; the deployment's operator runs them on
  the post-merge candidate (D7), and their sanitized findings are triaged as the owner's
  notes on that round. In the pipeline they collect and skip, which the unit wiring checks
  prove. The lanes' `e2e_vm_payment_purchase` and `e2e_bare_metal_payment_deal` exercise
  the shared stages these modules extend.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the wiring
  checks.

## 9. Closeout

The closeout task's eleven parts, in order (`openspec/README.md#plan-closeout-requirements`).
Closeout changes documentation only; a part needing a code edit returns the change to
implementation. Replanned against the reviewed design: first numbered 8, now covering D23
and the `settlement-servicing` delta.

- [ ] 9.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read the
  comments sections 1–8 added against `AGENTS.md`'s "Python comments and docstrings". A
  finding returns the change to implementation.
- [ ] 9.2 **Import placement — confirm.** Every import sections 1–8 added is at module
  level, or local for a stated reason. One that should move returns the change to
  implementation.
- [ ] 9.3 **Documentation compliance.** Check D1–D10, D12 and D15–D23 against
  `openspec/README.md`'s placement rules: normative behaviour in the deltas, rationale in
  `openspec/specs/test-compatibility/architecture.md` and `TESTING.md`, nothing durable
  left only in `design.md`. D18, D20 and D22 have no permanent destination, as the proposal
  records. D23's normative rule is the `settlement-servicing` delta's.
- [ ] 9.4 **Narrative compression.** Compress section notes to final behaviour, material
  evidence, deferred work and destinations, moving any rationale into `design.md` first.
  Section 3's stop notes compress to the stop, its cause, and D23 as the answer.
- [ ] 9.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 1 (D12):
  - the row "Real provisioning is not yet qualified" names this change as owner, narrows
    to observations 1 and 3 as owed elsewhere, and closes only if observations 2, 4, 5 and
    6 are each made by D8's per-observation outcome; otherwise its prose states each
    outcome and its owner;
  - new unowned gaps: a paid purchase with checked GPU work for each GPU offer (D6); no
    pushed operator notification for a cleanup refusal or held teardown (D5); a
    payer-scoped debit listing at the payments service, as future work outside this
    repository (D4); each storefront's buyer-facing settle status route resolving through
    the settlement runtime kit's resolver (D23); one settlement evidence store owned by a
    kit in place of each domain's table (D23);
  - the row recording the real modules' first run stays unowned.
  Name the update in the promotion record.
- [ ] 9.6 **Campaign index currency.** In `openspec/changes/README.md`, set this change's
  row to `in closeout` with notes matching the outcome, and update its campaign's
  dependency lines (`qualify-arkhai-real-provisioning` and `add-mvp-payments-lane-double`,
  both archived) to what is true. Run `make check-change-index`. Name the update in the
  promotion record.
- [ ] 9.7 **Packaging.** Run `make check-packaging` and resolve every failure, then
  `make check-architecture-change CHANGE=qualify-real-provisioning-by-scenario`; the change
  owns no architecture exception row.
- [ ] 9.8 **End-to-end pipeline.** Confirm the pipeline passes on the closeout candidate
  and record the run, its result, and the scenarios exercising this change:
  `e2e_bare_metal_payment_deal`, `e2e_bare_metal_mock_deal` (bare-metal lane);
  `e2e_vm_payment_purchase`, `e2e_deal`, `e2e_vm_payment_deal` (VM lane; the last for the
  settle wait's resolution of a payments deal by its negotiation). Record the operator's
  run of `e2e_vm_qualification`, `e2e_bare_metal_qualification` and
  `e2e_real_provisioning_reapply` on the post-merge candidate (D7): each observation made,
  or failed or unproven with a named cause outside this change, as triaged from the
  owner's notes. An observation failed or unproven by the scenario itself returns the
  change to implementation (D7).
- [ ] 9.9 **Promotion.** Write, and record in the promotion record:
  - `docs/development/TESTING.md`, a new "#### Locally verifiable and external-topology
    scenarios" under "### 4. System Integration Tests (End-to-End)", before "#### The
    real-provisioning lane": the two kinds and their coverage, minimal extension, topology
    ownership, externally supplied and free-form evidence, the per-observation outcome,
    and stepping a lease's end as the application of "Tests wait on events, never on
    durations" (D1, D8, D21; principles 1–5);
  - `docs/development/TESTING.md`, "#### The canonical compute deal": the buyer-purchase
    stage set, the settlement reference and D15's handoff, the two lane purchases (D15,
    D16, D17);
  - `docs/development/TESTING.md`, "#### The real-provisioning lane": the shared listing,
    `management_unit`, `admission_log` and the qualification markers (D2, D5, D9);
  - `docs/development/ARCHITECTURE.md`, "Testing strategy": the repository-wide rule that
    an external-topology scenario minimally extends a locally verifiable one (D1);
  - `openspec/specs/test-compatibility/architecture.md`, "Ordinary Arkhai purchase
    evidence": the lane purchases, the qualification scenarios, the balance sum check and
    its dedicated-account precondition, and the pinned unanswerable authority (D4, D10);
  - `docs/development/VALIDATION_RUNBOOK.md` §25, "Run The Real-Provisioning Scenario":
    running the qualification markers on a candidate, after each storefront chart's
    `helm test` payments check (D7, D19);
  - `docs/development/VALIDATION_RUNBOOK.md` §29, "Observations the qualification owes":
    observation 2's leases end through the watchdog's expiry path (D3); observation 4
    drops its GPU clause (D6); observation 5's notification is the reclaim job's recorded
    error and scheduled retry (D5); the per-observation outcome (D8);
  - `openspec/specs/settlement-servicing/architecture.md`, its settle-wait paragraph (D23):
    the kit resolves a waited reference by its settlement reference, then its negotiation,
    afresh at each poll, and owns `ready` and `failed`; each storefront supplies two evidence
    lookups and a delivery status; bare metal's delivery status wakes an adopted obligation
    only for evidence whose source names one. The paragraph's sentence on "Bare metal's
    settle-status read" names the hook section 2 removed (added by section 2, which found
    it);
  - `openspec/specs/test-compatibility/spec.md`, `openspec/specs/physical-provisioning/spec.md`
    and `openspec/specs/settlement-servicing/spec.md` (D23), written by the archive in
    9.11.
  No new capability or companion, so `openspec/specs/README.md` is unchanged. The
  kit-unification principle D23 applies is not promoted (`design.md`, Open Questions).
- [ ] 9.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=qualify-real-provisioning-by-scenario`, resolve every
  match, then `openspec validate qualify-real-provisioning-by-scenario --strict`.
- [ ] 9.11 **Archival.** `openspec archive qualify-real-provisioning-by-scenario -y`,
  merging the test-compatibility, physical-provisioning and settlement-servicing deltas;
  the change's row then links to its archive directory.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
