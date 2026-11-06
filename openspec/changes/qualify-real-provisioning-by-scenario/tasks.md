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

- [x] 3.1 The stage set (D1, D15's table). `buyer_purchase_stages.py` defines, like
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
  Done. `PurchaseState(ComputeDealState)`, the `PurchaseDriver(ComputeDealDriver)`
  protocol and `Purchase01_PayerBalanceBefore`, `Purchase02_ListingDiscovered`,
  `Purchase03_Bought`, `Purchase04_PurchaseCorrelated` (3.2's `Purchase05` and 3.3's
  `Purchase10` beside them). The bare-metal driver is `BareMetalPurchaseDriver` in
  `scenarios/bare_metal/purchase_driver.py`, over `BareMetalComputeDealDriver`: a
  payments-only pool override in `seed_supply`, the registry read as the purchase
  profile, the CLI arguments, the buyer's fulfillment status, and a lease view finding
  the hold by negotiation (the site's commit keeps the reserve's `deal_ref`,
  `kit/site/.../ledger.py`). Differed from the plan, each recorded for review:
  "hold the loops" is the canonical deal's readiness stages, reused rather than
  restated (`Stage00`–`00c2`, a mock lane's `00e`, `00f1` seeding through the driver,
  `00h`, which `09c2` requires; not `00d`, typed negotiation, or `00g`, Alkahest).
  `seller_listing_id` is written by the module's own listing stage, as
  `ComputeDealState` gives listing stages to the domain (bare metal's publication step;
  the VM purchase creates its listing); the purchase stages require it. `07a`'s
  prerequisite was `real_escrow_uid`, which a purchase never writes: it is now
  `_settlement_imminent`, a new `ComputeDealState` field `07` writes beside the escrow
  and `Purchase02` writes once the option is found, so an Alkahest lane behaves as
  before and no rule is armed for a deal that will not settle. `08c` (the mock job
  evaluation) is not run: its preview is 08a's, by escrow. `test_compute_deal_stages.py`
  gains `PURCHASE_LANES` in `ALL_LANES`, resolving the purchase stages' bodies, so the
  bare-metal purchase is held to the prerequisite, read-before-write, one-producer,
  own-fields and handoff checks; the real lane's consumption check now counts as
  consumed a field that a mock-lane stage reads and no shared stage reads (`07`'s
  `_settlement_imminent`, read only by `07a`). `Purchase05` verifies against the
  configuration's `receipt_trust`, as the buyer and seller roles do, so a retiring
  receipt key a target configures is accepted. Unit (source checks): `make
  test-e2e-unit` passes, the purchase row included.
  Amended by section 4: `Purchase03` runs the command in the background and waits for
  `payment_approved`, then the driver's `committed_event`. `Purchase04` correlates from
  `negotiation_completed` and `payment_approved` alone, with the Agreement naming the
  listing and option. The `run_ended` checks moved to a new shared `Purchase09`, through
  the driver's `check_run_ended` (4.1's note).
- [x] 3.2 Payment records (D4). A stage checks each transaction: bound to its Agreement,
  its receipt over that mandate, its snapshot naming the configured payer and payee, its
  parts' gross equal to the Agreement's price for its duration. The balance sum check reads
  the payer's own balance through `PaymentsClient.get_balance` with the buyer's token
  before the first purchase and after the last approval, and asserts the drop in
  `available` equals the sum of the scenario's own transactions' debits, logging the
  dedicated-account precondition beside the result.
  Done as `Purchase01_PayerBalanceBefore` (before discovery) and
  `Purchase05_PaymentRecordsChecked` (after `08b2`): `require_bound_to` at correlation,
  then `verify_snapshot` and `verify_receipt` against the pinned service identity,
  Agreement and mandate, the receipt's `from`/`to` against `BUYER_ACCOUNT` and
  `SELLER_ACCOUNT`, its parts' gross against the Agreement's `amount` and `asset` (the
  mandate's once part is the Agreement's amount for its duration, `derive_mandate`),
  and the drop in `available` against that gross, which is what approval debits
  (`PaymentsAuthority.approve`). It checks one transaction: a module with two purchases
  (section 8's observation 2) needs the sum over both. Its first proof is
  `e2e_bare_metal_payment_deal` in the pipeline.
- [x] 3.3 The buyer-teardown ending (D15, D16, D10). A shared stage runs
  `market bare-metal teardown --run-id <run>`, records `teardown_fulfillment_id` from the
  deal's fulfillment as delivery status reports it, and ends where `11b` starts; in a mock
  lane `09c2` arms the teardown gate before it and `11a2` drains after it. The delivery-end
  filing's `Unknown` outcome at the unanswerable authority neither fails the stage nor is
  read as delivery, access-end or refund evidence. If a buyer teardown releases the lease
  outside `check_leases`, the section stops and the change returns to design (D15).
  Done as `Purchase10_BuyerTeardown`: the CLI teardown, then the lease read `releasing`
  (a released lease fails the stage, the D15 case), `teardown_fulfillment_id` from the
  buyer's fulfillment status (checked equal to the lease's), the fulfillment
  `teardown_dispatch_pending`, and one convergence advance to `tearing_down` with the
  machine still held, which is what `11a` does in the expiry ending: `11a2` then has the
  teardown job to release. The D15 rule is not triggered as far as the code reads: the
  seller's end-delivery route drives the physical end synchronously
  (`market_deal_servicing/routes.py`), bare metal's `apply_end` terminates the lease at
  provisioning, and `LeaseLifecycle.terminate_lease` requests release as expiry does;
  the pipeline run is the first observation. The filing's outcome is never read; the
  stage's docstring states why.
- [x] 3.4 The bare-metal lane purchase (D16). `test_bare_metal_payment_deal.py` runs, in
  order: the purchase stages and `09a`–`09c`; its re-drive of the run's commit (its own
  stage, as today); the shared buyer-teardown ending; the seller refund of the still-held
  payment (its own stage, the snapshot showing every part reversed); `11b`. Its
  compensating cleanup (`PurchaseCompensation`) and the mock rules' removal are unchanged.
  The module's wall-clock poll of the buyer's fulfillment status goes with the step `09b`
  replaces. If the reverse after the teardown is refused, the section stops and the change
  returns to design (D16). The marker's description in `e2e-tests/pyproject.toml` says
  the buyer's CLI teardown precedes the refund.
  Done. The module declares the canonical readiness stages, its own `03` publication,
  `Purchase01`–`02`, `07a`, `Purchase03`–`04`, `08b2`, `Purchase05`, `09a`, bare metal's
  `09a2` publication close (which `09b` needs for `_listing_reconciled`), `09b`, `09c`,
  its own `09d` re-drive, `09c2`, `Purchase10`, `11a2`, its own `11` refund, `11b`, and
  its own `12`, which reads the deal released and the whole machine available and
  records the teardown evidence: the cleanup's compensation runs unless `12` recorded
  it, as it ran unless the old refund stage had. The wall-clock poll is gone with the
  step `09b` replaces; the fixture's ungated mock rules are gone too, since `07a` and
  `09c2` arm the gates, and the cleanup now opens any gate still closed before the
  compensation (a removed rule leaves its held job waiting) and removes the rules after
  it. `PurchaseCompensation`, its refund retry and the mock rules' removal are otherwise
  unchanged. `e2e-tests/README.md`'s rerun line no longer says "three ordered calls".
  The refund after the teardown is not known refused: D16 found no such refusal in the
  code, and the pipeline run is the first observation. Unit: the module collects and
  resolves its fixtures under `test_scenario_cleanup_order.py`'s `--setup-plan` (holds
  released after `purchase_cleanup`).
  Amended by section 4: the module also declares the shared `Purchase09` after `09c`,
  where the run's `run_ended` is now checked.
- [x] 3.5 The source check (D1; delta "defined once"). `test_buyer_purchase_stages.py`, on
  the pattern of `test_compute_deal_stages.py` and `stage_sources.py`: every scenario
  buying through the shipped buyer declares the purchase stages in order without replacing
  a body, inserts only its own stages between them, and runs the shared ending its lease
  ends by; the bare-metal lane purchase is one row. Unit: a constructed module replacing a
  shared body, or running the buyer-teardown ending and the expiry stages both, fails.
  Done. `purchase_faults` holds a row's shared stages (purchase and canonical) to one
  run order, `expected_order(mock=..., ending=...)`, each declared as `Test<base>` with
  an empty body, with exactly one ending; own stages sit anywhere between. Further
  checks: the purchase stages are not collected where defined, every one is in the
  order, none names a mock gate or the mock test client, each takes `PurchaseDriver`,
  and `PurchaseState` extends `ComputeDealState`. Unit (source checks): the bare-metal
  row passes; constructed modules pass with either ending and fail on a replaced body,
  both endings, and two purchase stages swapped.
- [x] 3.6 **Verification checkpoint.** Unit: `make test-e2e-unit`, with
  `test_buyer_purchase_stages.py` and `test_compute_deal_stages.py`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_bare_metal_payment_deal` (bare-metal lane) runs the purchase stages,
  the shared post-settlement stages with `09b` on a payments deal, the buyer-teardown
  ending and the refund after it.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the purchase
  source check.
  Unit: `make test-e2e-unit`, 582 passed (unit, the source checks of both stage sets and
  `test_scenario_cleanup_order.py`'s `--setup-plan` over the restructured module among
  them), run again after the fresh-context fixes. `make test` passed (every unit and
  integration suite) before those fixes, which touched only `e2e-tests` sources, its
  README and this file. `make check-change` passed all 12 checks, comment hygiene among
  them. No dependency or lock changed, so `make check-packaging` was not run. No
  end-to-end lane was run locally: the restructured module's stages are proven first by
  validation's pipeline.
  End-to-end scenarios, confirmed and extended: `e2e_bare_metal_payment_deal`
  (bare-metal lane) runs every purchase stage, `09a`–`09c` with `09b` on the
  negotiation, the buyer-teardown ending and the refund after it. `07`'s and `07a`'s
  changed prerequisite runs in `e2e_deal` (VM lane) and `e2e_bare_metal_mock_deal`
  (bare-metal lane); the real modules run `07` but are in no lane.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the purchase
  source check (confirmed).

Handoff from section 3:

- **For section 4.** The VM purchase declares `expected_order(mock=True, ending=EXPIRY)`
  (`test_buyer_purchase_stages.py`) and joins `PURCHASES` there and `PURCHASE_LANES` in
  `test_compute_deal_stages.py`, its state a `PurchaseState` subclass. `Purchase03`
  runs the buy in the foreground and waits for it to exit: bare metal's buy returns
  after its commit, with the create job held at `07a`'s gate. If `market buy` keeps
  polling its settlement until delivery, `Purchase03` cannot step convergence meanwhile;
  that needs a `PurchaseDriver` part, or a background run the stage drives, decided
  there. `Purchase02` requires `listing_published`, which the VM module's listing stage
  writes beside `seller_listing_id`. The VM driver needs `declared_host_id` (the host it
  registers), `discover`, `check_purchase_option`, `buy_arguments`,
  `teardown_arguments` (unused by an expiry ending, but in the protocol),
  `purchase_fulfillment` and a lease view by negotiation (VM already finds holds that
  way).
- **For section 8.** `Purchase05` checks one transaction against the balance drop since
  `Purchase01`; observation 2's two purchases need the sum over both. `PURCHASES` is a
  hand-kept table: each new purchase module adds its row.
- **Not proven locally.** The buyer teardown leaving the lease `releasing` and the
  fulfillment `teardown_dispatch_pending`, the settle wait answering the payments deal,
  and the refund after the teardown are read from the code (3.3's and 3.4's notes cite
  it); the pipeline is their first run. A failure at `Purchase10` with the lease
  `released` is D15's return-to-design case; a refused refund at stage 11 is D16's.
- **Fresh-context check.** No correctness defect found. Fixed: the README's stale
  description of the scenario (the authority filing, order, cleanup); a stale
  `TESTING.md` paragraph, added to 9.9 for closeout; the real-lane consumption
  exemption, narrowed to fields only a mock-lane stage reads; `Purchase05`'s trust,
  now `receipt_trust`; `Purchase10`'s message for a lease still `leased`; log lines in
  the module's own stages; the docstring's account of `09a2`. Declined: stage 12
  depending on `11b` (it writes no state; 12's own release and capacity reads fail if
  `11b` did not release, and a failure after the release leaves nothing to
  compensate); folding the two rule removals into `disarm_gates`, which swallows
  failures the cleanup reports; the private `_pinned` import from the lane's conftest,
  which the bare-metal mock deal module already makes. Left for triage: the delta's
  "three ordered calls" (`specs/test-compatibility/spec.md`, the bare-metal purchase
  scenario), which still reads as discovery, negotiation and approval, now through the
  shared stages. Reconciled since: the round's triage (review 55's documentation answer)
  made the scenario read "the shared purchase stages discover …".

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

- [x] 4.1 The VM purchase driver and module (D17). The module declares its own resource id,
  registers its host enabled and its pool in `host_registry.py` (as `E2E_PAYMENT_DEAL_HOST`
  and `E2E_PAYMENT_DEAL_POOL_ID` do), and creates its listing with an
  `arkhai.payments.v1` settlement through the seller client. It runs the purchase stages
  with `market buy`, the buyer CLI polling its settlement while the stages step
  convergence, as `test_full_deal_buyer_cli.py` does, then `09a`–`09c`, the payment-record
  and balance checks, `09c2`, `10a`, `10b`, `11a`, `11a2` and `11b`. It holds the loops for
  the whole module.
  Done as `test_vm_payment_purchase.py` (`VmPurchaseState`) over `VmPurchaseDriver` in
  `scenarios/vms/purchase_driver.py`, a `VmComputeDealDriver` with its own resource
  (`compute-e2e-payment-purchase-001`), host and pool (`E2E_PAYMENT_PURCHASE_HOST`,
  `E2E_PAYMENT_PURCHASE_POOL_ID`) and GPU model (`RTX 4080`, in no other scenario).
  `VmComputeDealDriver` gained a `gpu_model` field (default the canonical deal's) for that.
  The module declares the readiness stages, its own `03` listing (open, so published),
  `Purchase01`–`02`, `07a`, `Purchase03`–`04`, `08b2`, `Purchase05`, `09a`, its own `09a2`
  capacity-event step (which `09b` needs for `_listing_reconciled`), `09b`, `09c`,
  `Purchase09`, `09c2`, `10a`, `10b`, `11a`, `11a2`, `11b`.
  Decided here, as section 3's handoff left it: `market buy` takes no listing and polls its
  settlement until delivery, and it logs differently from `market bare-metal buy`. So the
  shared stages changed, and each domain's difference is a driver part:
  - `Purchase03` runs the command in the background and waits for `payment_approved`,
    then the driver's `committed_event` (VM `settlement_submitted`, bare metal
    `run_ended`), stopping a run that never commits.
  - `Purchase04` correlates from the events both buyers write (`negotiation_completed`,
    `payment_approved`), and checks that the Agreement names the discovered listing and
    option. `market buy` selects its listing by discovery (`--resource
    gpu_model="RTX 4080"`), so this check is what ties the purchase to its listing.
  - A new shared `Purchase09_PurchaseRunEnded`, after `09c`, waits for the command to
    end (30s once the settlement reads ready) and passes its `run_ended` to the driver's
    `check_run_ended`: VM `ready` with the negotiation as its reference; bare metal the
    checks `Purchase04` held before (`agreed`, the transaction, the fulfillment).
  - VM's `purchase_fulfillment` waits for the storefront's `job_submitted` event by
    negotiation, then reads the buyer's settle status. `assert_delivery` reads that status
    by negotiation rather than the escrow.
  The buyer is the lane's own (`BUYER.MARKETPLACE_CREDENTIAL`, its scheme), not the
  payments section's Ed25519 seed, so the lane buyer's storefront client reads the deal's
  settle status. It is profiled with no wallet, with Arkhai payments as its only
  settlement, and its prices are the hourly gross in base units (the CLI scales only
  Alkahest prices by decimals).
  The lane's `reap_buyer_settle_subprocess` now also stops a `purchase_run` still running,
  so the module keeps the lane cleanup `test_scenario_cleanup_order.py` requires. The
  module's own `purchase_cleanup` opens and removes its mock rules. `payments_config` is
  listed first, so a run with no target is a blocked skip before any hold.
  Unit (source checks and stage bodies against fakes): `make test-e2e-unit`, 599 passed.
  That covers the VM row of both stage-set checks, its `--setup-plan` cleanup order and
  hold checks, and `test_buyer_purchase_run.py`: `Purchase03` runs in the background,
  waits for approval then commit, and stops a run that never commits; `Purchase09` hands
  the run's end to the driver, and fails on a run still running or ended for another
  negotiation. Not run: no VM lane locally, so no `market buy` against a storefront. The
  driver's run-log events, arguments and routes are read from the code, and the pipeline
  is their first run.
- [x] 4.2 The expiry ending on a payments deal (D17). The back-dated lease, stepped with
  the watchdog held, tears the guest down and releases capacity while the pinned authority
  is unreachable; the module's `11b` asserts it. A stall caused by the unreachable
  authority is product behaviour the change does not alter, and stops the section for the
  owner rather than being worked around.
  Done: the module runs the canonical deal's `09c2`, `10a`, `10b`, `11a`, `11a2` and `11b`
  unchanged on the payments deal. Read from the code, no stall is expected. The lease
  watchdog and convergence are mechanism-neutral. The VM storefront's capacity-released
  callback records the release locally and calls no authority
  (`admin_controller.py` `_record_capacity_released`, `deal_lifecycle.py`
  `capacity_released`). The storefront's settlement-servicing loop, which reads the
  authority, is held and never stepped by these stages. The pipeline run is the first
  observation; a stall there stops the change for the owner, as this task says.
- [x] 4.3 Lane membership. `e2e_vm_payment_purchase` is registered in
  `e2e-tests/pyproject.toml` and added to `E2E_MODULE`; `test_buyer_purchase_stages.py`
  gains the VM row; `e2e-tests/README.md` lists the marker.
  Done. `test_buyer_purchase_stages.py`'s rows now state their ending (`ending=EXPIRY`
  for VM, `BUYER_TEARDOWN` for bare metal), and a row declaring the other ending fails (a
  constructed case). `test_compute_deal_stages.py` gains the `vms_purchase` lane. The
  README gains the marker in the payment scenarios' list and a "VM buyer purchase"
  section.
- [x] 4.4 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_vm_payment_purchase` (VM lane) runs the purchase, the shared
  post-settlement stages and the expiry ending against the lane's payments double.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the VM row.
  Unit: `make test-e2e-unit`, 599 passed, after the fresh-context fixes. `make test`
  passed before those fixes. The fixes touched only `e2e-tests` sources, the VM conftest
  and this file, and the e2e unit suite was run again after them. `make check-change`
  passed all 12 checks, comment hygiene among them. No dependency or lock changed, so
  `make check-packaging` was not run. No lane was run locally.
  End-to-end scenarios, confirmed and extended:
  - `e2e_vm_payment_purchase` (VM lane) runs the purchase, `09a`–`09c` with `09b` on the
    negotiation, `Purchase09`, and the expiry ending.
  - `e2e_bare_metal_payment_deal` (bare-metal lane) runs the changed `Purchase03`–`04`
    and the new `Purchase09`.
  - `e2e_deal` (VM lane) runs the `gpu_model` field's default.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the VM row
  (confirmed).

Handoff from section 4:

- **For section 8.** A qualification module adds its `PURCHASES` row with its `ending`
  and a `PURCHASE_LANES` row. It declares `Purchase09` after `09c`. Its driver supplies
  `committed_event` and `check_run_ended`. A VM qualification module can build on
  `VmPurchaseDriver`, and must supply a real-lane `purchase_fulfillment`, since
  `job_submitted` is the storefront's event, not the mock's.
- **Not proven locally.** That `market buy` accepts the arguments as given, reads its
  configuration, and writes the events as read from the code. That the lane buyer, a
  wallet-free profile, can negotiate a payments option at the VM storefront. That the
  expiry ending completes on a payments deal (4.2). The pipeline is the first run of
  each. If `market buy` derives its prices or selects its option otherwise than read,
  the failure shows at `Purchase03` with the run's events and stderr.
- **Fresh-context check.** Blocking finding fixed: the buyer's configuration sections
  were never passed to `create_profiled_buyer_cli`. Also fixed:
  - `payments_config` listed first, so a run with no target is a blocked skip (before,
    the module went on to register supply and list with a payee of `"None"`);
  - `Purchase03` now waits for `payment_approved` first, so a bare-metal run ending
    refused fails at the buy stage with its exit status;
  - the module builds its buyer configuration from the SSH key alone, not the lane
    buyer's wallet settings, so it does not skip naming a wallet it never uses;
  - the purchase's mock rules are removed in cleanup, after its gates are opened;
  - the reap fixture's docstring.

  Declined: making `PURCHASE_RUN_EXIT_SECONDS` a driver part. It bounds the wait for a
  command that has already read its settlement ready or ended. A driver whose command
  polls more slowly fails at `Purchase09`, naming the run.
- **Round 1 triage fix (validation 57 V1).** The pipeline's first run of
  `e2e_vm_payment_purchase` (run 42267053852) failed at `Purchase04`:
  `VmPurchaseDriver.purchase_fulfillment` called `model_dump` on the typed client's
  `SettleStatusResponse`, a dataclass. It now returns `dataclasses.asdict` of it. Unit
  (`tests/unit/test_vm_purchase_driver.py`, the driver against fake clients returning
  the storefront client's real `SettleStatusResponse`): the method waits for the
  storefront's `job_submitted` by negotiation, reads the buyer's settle status, and
  returns its `fulfillment_id`. `make test-e2e-unit`: 608 passed. The 15 stages after
  `Purchase04` have still never run against the lane; the fix commit's validation is
  their first run.

## 5. One listing offers every composed mechanism on a real resource

Delivers D2: one shared helper creates or adopts the real VM resource's listing, stating a
settlement for each mechanism the storefront reports ready, and adoption requires the
adopting module's own mechanism (test-compatibility delta ADDED "A real resource's listing
offers every composed deal mechanism", so renamed by the round's triage). Replanned against the reviewed design: first numbered 4.

Files: `e2e-tests/tests/e2e/roles/helpers/real_provisioning.py` (or a sibling helper
module); `e2e-tests/tests/e2e/roles/scenarios/vms/test_real_provisioning_deal.py` (its
listing stage, lines ~350–380); `e2e-tests/tests/unit/test_real_vm_lane.py`.

- [x] 5.1 The helper (D2). Given the storefront's ready mechanisms, the target's resource
  and the module's own mechanism, it adopts the resource's existing listing when it offers
  that mechanism, fails naming the listing and its options when it does not (changing
  nothing), and otherwise creates the listing with one settlement per ready mechanism. The
  VM Alkahest real module's listing stage calls it. Bare metal needs no helper: its
  published options are the composed mechanisms (D2).
  Done as `create_or_adopt_listing` in `scenarios/vms/composed_listing.py`, not under
  `helpers/` as the plan offered. It is VM's, built on the VM conftest's
  `capacity_source_for`, and `helpers/real_provisioning.py` holds only domain-neutral
  parts.
  - **Readiness.** The storefront reports it in its system status's `settlement`, one
    `MechanismReadiness` projection per composed mechanism (`ready_mechanisms`). It is
    read only on the creation path, so adoption never depends on it.
  - **Creation.** One settlement clause per ready deal mechanism, paused, then read back
    offering exactly those mechanisms (compared as sets, since a mechanism may publish
    several options). A ready mechanism the run states no settlement for fails before
    anything is created; so does the module's own mechanism not being ready.
  - **Adoption.** The former `RealVmComputeDealDriver.listing_for_run`, moved here
    (exactly one listing, open, of the target's shape; paused unless already), plus the
    own-mechanism check, made before the pause so a refused listing is left unchanged.
    Failures name each listing's options. The driver's `listing_for_run` and
    `_listings_on_resource` are removed.

  Differed from the plan, for triage: "ready mechanisms" means the ready *deal*
  mechanisms, Alkahest and Arkhai payments (`DEAL_MECHANISMS`). The VM storefront also
  composes `contact-exchange.v1` and reports it ready wherever contact profiles are set,
  as `helm/local-values.yaml` and Bob's storefront configurations do. Stating it would make
  creation require a contact settlement that no module on the resource deals by. D2's
  intent is both kinds of module on one stack; the delta's "each mechanism the storefront
  composes and reports ready" reads wider, and its wording is left for triage to reconcile.
  Reconciled since: the round's triage (review 55's documentation answer) made D2, the
  proposal and the delta say "each deal mechanism", contact exchange stated on no compute
  listing.
  The real module's `02b` now states its Alkahest terms as a clause (`ALKAHEST_SETTLEMENT`:
  the deal token, 10 whole tokens an hour, `escrow_kind` `erc20_escrow_obligation_default`
  on `anvil`) in place of `accepted_escrows`. A create request with clauses builds options
  only for its clauses' mechanisms (`settlement_composition.py`, `publication_artifacts`),
  so a listing offering two mechanisms needs a clause for each. The clause publishes the
  former escrow: the storefront resolves the escrow address from its own address book,
  and the token's decimals over RPC. `listing_settlements()` adds the Arkhai payments
  clause where the run names `PAYMENTS.SELLER_ACCOUNT`. `payments_settlement` is shared
  with section 4's `VmPurchaseDriver`, which now builds its listing settlement through it.
  Outside the plan: `e2e-tests/pyproject.toml` now declares `arkhai-core`, whose
  `market_core.schemas` sections 3–5 import, and `make lock` added it to
  `e2e-tests/uv.lock` (two lines).
- [x] 5.2 Unit, in `test_real_vm_lane.py`: creation states one settlement per ready
  mechanism; an Alkahest module and a payments module, in either order, adopt the same
  listing and create no second one; a listing lacking the adopting module's mechanism
  fails naming the listing and its options before any deal; a one-mechanism stack yields
  one option.
  Done, against a fake storefront that publishes an option per stated settlement whose
  mechanism is ready, refuses a second listing on a resource, and reports contact
  exchange ready beside the deal mechanisms. Unit cases:
  - creation states one settlement per ready deal mechanism, not contact exchange;
  - a stack with one deal mechanism ready gets one option;
  - in either order, an Alkahest and a payments module end with one listing and one
    creation;
  - a listing lacking the module's mechanism fails naming the listing and an option id,
    pausing and creating nothing;
  - a ready mechanism with no stated settlement, or the module's own mechanism not ready,
    creates nothing;
  - the former adoption cases pass on the helper: closed, two listings, another shape,
    other resources, a later page, already paused;
  - `02b` adopts and creates none;
  - `ALKAHEST_SETTLEMENT`'s rate is `LISTED_HOURLY_RATE` in whole tokens.

  Not covered at unit level: `listing_settlements()`'s payments branch, which reads the
  run's settings, and the storefront's own suppression of an unready option, which the
  fake models rather than exercises.
- [x] 5.3 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_vm_real_provisioning` runs the helper but is in no lane; no pipeline
  marker covers it, and none is owed, since a real resource exists only on a target.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the helper's
  cases.
  Unit: `make test-e2e-unit`, 607 passed, after the fresh-context fixes. `make lock`
  rewrote `e2e-tests/uv.lock` only; `make check-packaging` passed after it.
  `make check-change` passed all 12 checks, comment hygiene and version bumps among them.
  `make test` passed before the fixes and again after them, on the final tree.
  End-to-end scenarios, confirmed:
  - `e2e_vm_real_provisioning` runs the helper, in no lane; no pipeline marker covers
    it, and none is owed.
  - `e2e_vm_payment_purchase` (VM lane) runs `payments_settlement` through its driver.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the helper's
  cases (confirmed).

Handoff from section 5:

- **For section 8.** The observation 2 module calls `create_or_adopt_listing` with
  `mechanism=ARKHAI_PAYMENTS_MECHANISM`, the real target's resource
  (`REAL_RESOURCE_ID`, the real module's `offer_resource` shape), and settlements for
  both deal mechanisms: the real module's `listing_settlements()` gives both where
  `PAYMENTS.SELLER_ACCOUNT` is set. The listing is created or adopted paused, so the
  module resumes it into publication as the real module's `03b` does.
- **Not proven.** The clause-built Alkahest option on a real target, and the storefront
  reading `settlement` readiness there; the real module's first run is the first
  observation.
- **Fresh-context check.** Fixed:
  - contact exchange, a ready seller mechanism, would have failed every creation on the
    local stack; readiness now counts deal mechanisms only;
  - the created listing's mechanisms are compared as sets;
  - readiness is read only when creating;
  - option schemas are read without full validation;
  - the Alkahest rate is computed exactly;
  - comments naming modules not yet on the branch are rephrased as the rule;
  - `composed_listing.py`'s docstring now owns the shared payments settlement;
  - import order in `test_real_vm_lane.py`;
  - the undeclared `arkhai-core` dependency.

  Recorded: `TESTING.md`'s real-lane adoption paragraph is stale until closeout's 9.9
  writes the shared listing there.

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

- [x] 6.1 The playbook task (D5). `host-diagnostics.yml` prints one fact for the action
  with boot ID, uptime, kernel, the count of running guests, and for
  `libvirtd.service`, `frpc-buyers.service` and the optional management unit: active
  state, invocation ID, main PID, restart count, active-enter time and result. The
  management unit arrives as a job parameter. The VM IaC README documents the action and
  its fact. Check: `make test-provisioning-iac` (syntax and the native gate's coverage).
  Done. The host is read by a new script, `roles/vm-management/files/host_diagnostics.sh`,
  which `host-diagnostics.yml` runs through Ansible's `script` module with the unit
  quoted, then sets `host_diagnostics_data` from its JSON, adding `action: diagnose`,
  `host` and `status`. `main.yml` includes it for `vm_action == "diagnose"`, and
  `json-output.yml` prints the fact in the shipped `var:` and `msg:` forms. The fact's
  fields: `timestamp`, `boot_id`, `uptime_seconds`, `kernel`, `running_guests`,
  `management_unit` (or null), and `units` keyed by unit name. Each unit carries
  `active_state`, `invocation_id`, `main_pid`, `restart_count` (`NRestarts`),
  `active_enter_timestamp` and `result`. Differed from the plan, each needed for the read
  to be right:
  - **The prerequisites skip "Ensure libvirtd is running" for `diagnose`.** That task
    starts libvirtd for every action. Started by the read, an idle socket-activated
    daemon would show a new invocation ID.
  - **The script reads the units before `virsh` counts guests,** for the same reason.
    The count itself still starts an idle libvirtd, so a later read may see the
    generation an earlier read started. D5's pass criterion compares libvirtd only
    across reads taken while a guest runs, when the daemon is up anyway. The script,
    the task and the README say so; none claims the read changes nothing.
  - **A number systemd does not report is printed as text,** such as `NRestarts` on an
    old systemd, so the typed parse refuses that field by name.
  - **A failed `systemctl show` or `virsh` fails the job,** naming what failed. Neither
    is reported as an empty value or zero guests. `unit_state` runs in a command
    substitution, where `set -e` does not apply, so it returns its failure explicitly.
  - **A management unit equal to one of the two host units is read once.**
  The parse-only `vm-management-task-files.yaml` imports the new file, so the syntax
  check reads it. `test_ansible_structure.py`'s list moved with it. The README gains
  "6. Read Host Diagnostics": the command, `management_unit`, and the fact's fields.
  Library integration (`tests/test_host_diagnostics.py`): the real script runs through
  `shell_harness` against faked `systemctl`, `virsh`, `uname` and a temporary `/proc`.
  It covers both unit sets, a duplicate unit, zero guests, and the read order. It
  covers a missing number, and escaping of quotes, backslashes and a tab (not CR, LF or
  other control characters). It covers a failed `systemctl` and a failed `virsh`.
  Structure cases read the YAML for the include, the `quote` filter in the task, the two
  `debug` tasks printing the fact, and the prerequisite's condition; none reads printed
  output through the codec, which the adapter's mock-output cases do for the Python
  renderer. Where ansible-core 2.17–2.19 is installed, the shipped task file also runs
  through `ansible-playbook` against localhost with the same fakes. Those runs cover a
  plain unit, a unit with a backslash (`dev-disk-by\x2dlabel-data.device`, which reaches
  the script whole only quoted), no unit, and an explicit null. They check the fact
  the task sets, exported through `to_json`. So the module joins the native gate's
  `NATIVE` list (`domains/vms/provisioning/iac/scripts/native_ansible_gate.sh`), which
  `test_ansible_structure.py` requires of any module with an `_ansible` guard.
  `make test-provisioning-iac`: VM 182 passed, 6 skipped (the native cases, no local
  Ansible). `make test-provisioning-iac-native` (after `make build-provisioning`) passed:
  the six playbooks' syntax checks, `vm-management-task-files.yaml` among them, and 20
  native VM tests, the three native host-diagnostics cases among them. Running
  `domains/vms/provisioning/iac/scripts/validate_playbooks.sh` directly was denied in
  this session; the native
  target runs the same script in the image instead.
- [x] 6.2 The action (D5). A host-scoped action (`diagnose`), registered in `codec.py`'s
  result-fact and fact-action maps and `bundle.py`'s actions, submitted by
  `host_operations_service.py` beside `check` and routed by the controller. A
  `management_unit` not matching systemd's unit-name syntax is refused at submission, no
  job queued; an unknown host is the route's error. The mock profile's default output
  (`mock_output.py`) renders a fact from the job's parameters. Unit: the unit-name
  validation (valid names, a path, a space, an empty name). Application integration
  (`test_hosts_api.py`, through the typed client): a submitted job succeeds in the mock
  profile with a fact the parse accepts; an invalid unit is refused with no job queued.
  Done.
  - **The route** is `GET /api/v1/hosts/{host}/diagnostics?management_unit=…`, signed as
    `provisioning_host_diagnostics`, admin only, declared in the client's `routes.py`. It
    is a GET like the capacity check's.
  - **Where it lives.** The route is bound in `controllers/hosts_controller.py`, where the
    capacity check is, not `vms_controller.py` as the file list said. The router factory
    is renamed `make_host_operations_router` (one caller, `routers.py`).
  - **Submission.** The refusal is the wire model's. `HostDiagnosticsRequest`
    (`VmActionRequest` plus `management_unit`) validates the unit with
    `check_unit_name`, as `ARCHITECTURE.md`'s order of checks puts a check the request
    settles by itself. The route binds it as a query model (`Annotated[…, Query()]`), so
    FastAPI answers the refusal as 422 before the route service runs, and the typed
    client builds it, so it raises before sending. `HostOperationsService.diagnose`
    then only submits. The unit travels as a new `VmJobParams.management_unit`, which
    `vm_job_params` reads back and `variables` passes to the playbook only when set.
  - **The result.** The codec copies `VM_DIAGNOSTICS_FIELDS` from the fact into the
    result, whenever the fact has them, so a zero guest count and a null unit survive.
    Its kind is `vm_diagnose`, the client's `HOST_DIAGNOSTICS_RESULT_KIND`.
  - **Mock default output.** A host with no guest whose units are each active, with
    restart count 0. The boot ID is fixed, and each invocation ID is a UUIDv5 of host and
    unit, so repeated reads agree. The management unit is included when the job names
    one.

  Unit (`provisioning/compute/service/tests/unit/services/test_host_operations_service.py`,
  the service against a mocked job engine): the job carries the unit, or none; an
  unregistered host is refused with nothing submitted.
  Unit (`provisioning/compute/service/tests/unit/models/test_host_diagnostics.py`):
  `check_unit_name` accepts templates, escapes, `-.mount` and 255 characters. It refuses
  the empty name, no type, a path, `../agent.service` (for its `/`), a space, `;`, a
  newline, an unknown type, an empty prefix, and 256 characters. `a..b.service`, with
  `..` but no `/`, is accepted (a case): systemd's own syntax allows it, and the name
  only reaches `systemctl` as one quoted argument. `HostDiagnosticsRequest` refuses four
  malformed names (`../agent.service`, a space, the empty name, `agent`), naming
  `management_unit`.
  Unit (adapter, `test_vm_codec.py`, `test_vm_mock_output.py`): the fact map and the
  stored, rendered and reported fields; the mocked output read back through the real
  codec and `HostDiagnostics.from_job_result`, with and without a unit; two renders
  agreeing.
  Application integration (`test_hosts_api.py::TestHostDiagnostics`, the in-process app
  through the typed clients, the VM runner the `MockAnsibleRunner` with
  `vm_mock_output`): a job naming a unit succeeds, and the parse reads its result with
  the unit; a job naming none reports the two host units. Both wait on the job queue's
  `wait_until_idle`, not a poll. For `../agent.service`, the typed client raises before
  sending. A rejection-path test writes the request by hand, signs it through the
  family transport's `authenticated_request` with the route's declaration, and sees
  422; per `TESTING.md`'s rule it asserts the status and the stored jobs, not the body.
  An unknown host is refused with 404. The job count is unchanged in all three.
  `make test-provisioning-adapter`: 292 passed. `make test-provisioning`: 703 unit and
  584 integration passed.
- [x] 6.3 The client (D5's interface). `diagnose_host(host_id, management_unit=None)` on
  `VmOperatorClient` and `SyncVmOperatorClient` returns the `JobSubmitResponse`, and the
  client gains no polling. `HostDiagnostics.from_job_result(result)` in
  `vm_provisioning_operator` returns the typed facts or raises a named error naming the
  missing or malformed field, returning no partial result. Unit: a well-formed result
  parsed; each missing field and a wrong-typed field refused naming it. The endpoint
  coverage and client contract tests include the new route.
  Done. `diagnose_host` builds the request model, so an invalid unit raises
  `pydantic.ValidationError` before anything is sent. `from_job_result` takes the job's `ResultEnvelope` (`JobStatusResponse.result`) and
  raises `HostDiagnosticsError` (a `ValueError`) whose `field` names what is wrong. That
  is `result` for none; `result_kind` for another action's; the dotted path of the first
  missing or wrong-typed field (`units.libvirtd.service.restart_count`); and
  `units.<name>` for a unit the result names but does not report. Fields are strict.
  The tested cases: integer fields refuse `"1"`, `True`, `""` and `812.0`; string fields
  refuse `7` and `None`; the uptime refuses `"3600.5"` and takes an int or a float. The
  dotted `field` cannot be split back into unit and field by a program, since unit names
  contain dots; it is for a reader. `HostDiagnostics` exposes `libvirtd`, `relay_client`, `management` (or
  `None`) and `reported_units()`. All of these, `check_unit_name`, `HostDiagnosticsRequest`,
  `UnitDiagnostics`, `LIBVIRTD_UNIT` and `RELAY_CLIENT_UNIT` are in `models.py` and the
  package's `__all__`.
  Unit (`test_host_diagnostics.py`, as in 6.2): a well-formed result read whole; each of
  the eight top-level and six unit fields refused by name when missing; seven wrong types
  refused by name; each asked-for unit missing refused by name; no result; another kind.
  The client package has no suite of its own; the service suite owns VM's client
  contract, as `test_provisioning_client_contract.py` says. That contract test (async and
  sync signatures equal) passes with the new method. The endpoint coverage test submits
  `diagnose_host`. Both are in `make test-provisioning`'s counts above.
- [x] 6.4 Versions and locks (`docs/development/RELEASING.md`, "Versioning policy";
  `AGENTS.md`, "Package and dependency discipline"). Bump the adapter's and the client's
  versions once each against `dev`, raise any exact pin that moves, run
  `make check-uv-version` and `make lock`, and commit every lock it rewrites. A package
  section 2 already bumped is bumped again only if this section needs a larger bump.
  Done. Neither was bumped on the branch before. Client 0.11.0 → 0.12.0 and adapter
  0.17.0 → 0.18.0, minor each for new public API. The adapter's bound on the client rises
  to `>=0.12.0`, since it imports the new models. No exact pin names either package.
  `compute-provisioning-service`'s dev group raises its bounds to adapter `>=0.18.0` and
  client `>=0.12.0`, which its tests need. The service is not bumped: a dependency group
  is not in its wheel's metadata. `make check-uv-version` passed. `make lock` rewrote four
  locks, only moving these two versions: the adapter's, the client's, the service's and
  `e2e-tests`'.
- [x] 6.5 **Verification checkpoint.** Unit and application integration:
  `make test-provisioning`, `make test-provisioning-adapter`, `make test-provisioning-iac`.
  Run `make test`, `make check-packaging` (6.4 changes versions and locks) and
  `make check-comment-hygiene`.
  End-to-end: no pipeline marker runs the job; section 8's observation 2 module, in no
  lane, is its first system-level caller. None is owed in the pipeline.
  Owed by validation: `tests.yml`, jobs `test · test-provisioning`,
  `test · test-provisioning-adapter` and `test · test-provisioning-iac` — pass with the
  new action, client and playbook task.
  On the final tree, after both fresh-context passes' fixes:
  - `make test-provisioning`: 703 unit and 584 application-integration passed.
  - `make test-provisioning-adapter`: 292 passed.
  - `make test-provisioning-iac`: VM 182 passed, 6 native cases skipped.
  - `make test-provisioning-iac-native`: passed in a freshly built provisioning image,
    before the second pass, whose IaC edits touched only comments and a docstring.
  - `make test`: passed before the second pass, whose edits touched only comments, one
    test's assertion and one added unit case; the suites covering them were run again.
  - `make check-packaging`: every check OK.
  - `make check-change`: all 12 checks passed, comment hygiene, version bumps and local
    imports among them.

  End-to-end scenarios, corrected: no pytest marker runs the job, as planned. The
  pipeline (`e2e.yml`) does run the task file natively: job `e2e-vm`, step "VM IaC native
  Ansible gate", runs `make test-provisioning-iac-native` in the provisioning image that
  lane built, and `test_host_diagnostics.py` is now in that gate's `NATIVE` list.
  Validation's pipeline run is therefore evidence for 6.1's task file and script against
  fakes, run in a test play with the script beside it, not for the role's include and
  dispatch (read only structurally) and not for a real host.
  Owed by validation: `tests.yml`, jobs `test · test-provisioning`,
  `test · test-provisioning-adapter` and `test · test-provisioning-iac` — pass with the
  new action, client and playbook task (confirmed).

Handoff from section 6:

- **For section 8 (observation 2).** Submit with
  `client.vm.diagnose_host(host_id, management_unit=…)`, with the unit from section 7's
  `VmHost.management_unit`. Wait with `JobWatch.until_succeeded`, then read
  `HostDiagnostics.from_job_result(job.result)`. `management` is `None` when no unit is
  named, and the stage skips naming `management_unit` (D5). Compare `invocation_id`,
  `restart_count`, `active_state` and `result` across reads. A read can itself start an
  idle libvirtd, so compare libvirtd only across reads taken while the first guest runs,
  as D5's criterion already says. A unit that is not a systemd service unit name raises
  `pydantic.ValidationError` in the client before any request.
- **Seams.** `client.vm` is `VmOperatorClient` over the family transport. In the service's
  integration suite, a class-level `fake_ansible` fixture returning
  `MockAnsibleRunner(default_output=vm_mock_output)` runs VM jobs through the mock
  profile's output, and `queue.wait_until_idle()` waits for them. A request the typed
  client refuses reaches the route through `client.family.authenticated_request(…,
  route=vm_route(…))`.
- **The IaC wheelhouse trap.** The provisioning image's builder stage caches `.dist`.
  The native gate reads the IaC tree, which is copied fresh, so it needs only
  `make build-provisioning`. The service and adapter suites read the client from
  `.dist`, so a client change needs `make dist` (or `make check-packaging`) before they
  see it.
- **Outside the plan.** The router factory rename (`make_host_capacity_router` →
  `make_host_operations_router`). The prerequisites' libvirtd start skipped for
  `diagnose`. The native gate's `NATIVE` list. A 9.9 item for `TESTING.md`'s native-test
  paragraph.
- **Denied in this session.** Running `domains/vms/provisioning/iac/scripts/validate_playbooks.sh`
  directly; `make test-provisioning-iac-native` ran it in the image instead. A chained
  Python one-liner probing pydantic's strict mode; the unit tests settled it instead. A
  `make test` with its output redirected to a file; it ran in the background instead.
- **Fresh-context check.** Fixed:
  - the unit-name check moved from the route service to the wire model, per
    `ARCHITECTURE.md`'s order of checks;
  - wording claiming the read changes nothing;
  - a failed `systemctl show` being swallowed;
  - overstated task notes (the `..` case, the strict-type cases, the structure cases,
    the escaping);
  - polling waits replaced by `wait_until_idle`;
  - a test docstring naming a scenario not yet on the branch;
  - an explicit null unit breaking the task's Jinja;
  - a duplicate unit read twice;
  - a test-name typo.

  Declined:
  - escaping control characters other than tab, CR and LF: systemd's properties here
    are words, IDs, numbers and timestamps;
  - a machine-splittable error path: `field` is for a reader, and the note says so;
  - renaming `diagnose_host`'s `host_id`: D5 names the signature;
  - the endpoint-coverage module's "not exercised elsewhere" docstring, which already
    described its existing VM list loosely.

  A second pass, after those fixes, found and fixed: a rejection-path test asserting on
  the response body; a note claiming an untested `..` case, now a case; "writes nothing"
  (the `script` module copies the script to the host), reworded; the client's
  `pyproject.toml` comment, now naming the result the parse reads. Declined, for triage:
  - **A missing unit reads as stopped.** A mistyped or absent `management_unit` reads
    back `inactive` with an empty invocation ID, since `systemctl show` answers for a
    unit not loaded. D5's "stays active" check then fails naming the unit, not the
    name. Reporting `LoadState` would tell them apart, but it is a field beyond D5's
    list and the delta's. Section 8's stage can say a not-started unit may be a wrong
    name.
  - **The service's published `adapters` extra keeps `>=0.17.0`.** The deployed image
    installs from the service's lock, which has 0.18.0. Raising the extra changes the
    service's published metadata and would bump it.
  - **Smaller points.** The query model's parameter is named `body`, as the capacity
    check's is. `HostDiagnosticsError` does not pickle.

  The round's triage disposed of these: the missing-unit reading is left to section 8's
  stage message, and the `adapters` extra stays as it is (deployments install from the
  lock).
- **Round 1 triage fix (review 55 F1).** A management unit of another type than a
  service (`.socket`, `.timer`, `.mount` …) was accepted, but `systemctl show` reports
  no `MainPID` or `NRestarts` for it, so every such job's result failed the typed parse.
  The management unit is now restricted to systemd service unit names (D5 amended, both
  deltas with it): `check_unit_name` became `check_service_unit_name`, its pattern ending
  in `.service`; the request model, the client's and adapter's docstrings, the task
  file's comment and the IaC README say so. The earlier notes above that name
  `check_unit_name` or accept `-.mount` describe the code before this fix. Unit
  (`provisioning/compute/service/tests/unit/models/test_host_diagnostics.py`): service
  names with templates, an escape, `..` and 255 characters accepted; `.socket`,
  `.device`, `.mount`, `.slice`, `.timer` and `.target` names refused beside the earlier
  malformed ones; the request refuses `agent.socket`, naming `management_unit`. The IaC
  native case's escaped unit is now a service (`operator-agent@by\x2dlabel.service`).
  After `make check-packaging` (every check OK, the client wheel rebuilt into `.dist`):
  `make test-provisioning` 708 unit and 584 application-integration passed;
  `make test-provisioning-adapter` 292 passed; `make test-provisioning-iac` VM 182
  passed, 6 native cases skipped. `make test-provisioning-iac-native` passed, but in the
  provisioning image built during section 6: rebuilding it (`make build-provisioning`)
  was denied in the triage session, so that run read the earlier copy of the changed
  native case. The pipeline's `e2e-vm` job builds the image and runs the gate.
- **Round 1 triage checks (both fixes, 57 V1 and 55 F1).** `make test` passed;
  `make test-e2e-unit` 608 passed on the final tree; `make check-packaging` every check
  OK; `make check-change` all 12 checks passed. A fresh-context check of the diff found
  no code defect. Fixed from it: the new driver test now carries the response's
  principals (the nested case `asdict` copies); the driver's comment sits above the
  line it explains; D2's heading and the delta requirement's heading say "deal
  mechanism"; this note and the section 8 handoff's wording; long delta lines rewrapped.
  Declined: writing the compensation clause into the qualification requirement now; the
  triage's disposition puts it in 8.4, which says so.

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

- [x] 7.1 Target fields (D5, D9). `VmHost.management_unit: str | None`, a systemd service
  unit name checked by the operator client's `check_service_unit_name` (review 55 F1
  restricted it to services); `RelayAccess.admission_log: str | None`, an absolute
  harness-local path validated as `CleanupOperator.key_path` is. Both join version 2
  without a bump; an older checkout refuses them by name as an unknown field. The target
  example shows both, commented as optional. Unit (`test_real_provisioning_target.py`): a
  valid unit and path accepted; an invalid unit and a relative or `..` path refused before
  any stage, naming the field.
  Done. `_harness_local_path` now serves both `admission_log` and `key_path`. `e2e-tests`
  raises its bound on `arkhai-vms-provisioning-operator-client` to `>=0.12.0`, the release
  with `check_service_unit_name`; `make lock` moved only that specifier in
  `e2e-tests/uv.lock`. Unit (`test_real_provisioning_target.py`): both fields absent by
  default; both accepted; the example's two commented lines valid once uncommented;
  `agent`, `agent.socket`, `../agent.service`, a name with a space and the empty name
  refused, naming `hosts.0.vm.management_unit`; a relative, `./`, `..` and empty path
  refused, naming `hosts.1.bare_metal.access.relay.admission_log`; each field refused on
  the other domain's host or the other access mode.
- [x] 7.2 The admission-log reader (D9). It reads the file's lines as the plugin's
  documented log contract (`tools/frp-grant-admission/README.md#the-log`) and, for one
  delivered lease, finds an `admit` line with `verified` true, `jti` equal to the
  reservation, `remote_port` equal to the lease record's `remote_port`, and `kid` equal to
  its `grant_key_id`, the record read through the relay's leases
  (`GET /api/v1/relays/{relay_id}/leases`). Unit: a matching line found; a line under the
  relay's newer active key but not the lease's recorded key refused; an earlier `admit`
  under a retired key ignored when the latest grant's line is present; a missing, unverified
  or mismatched line failing naming the lease.
  Done in a new `helpers/qualification.py`: `relay_lease_record` (the reservation's one
  unreleased `fulfillment` row), `require_admitted` (the matching rule, `remote_port`
  required an integer) and `check_admission(target, provisioning_client, reservation)`.
  The grant's `jti` is the lease's `owner_id`, the reservation
  (`compute_provisioning/relays/grants.py`). Beyond the plan, each found needed:
  - **A direct target** delivers no relayed lease, so the check returns `None` and
    passes; only a relayed target without `admission_log` skips, naming
    `REAL_PROVISIONING_TARGET.hosts.<domain>.access.admission_log`.
  - **The copy may trail the relay's log.** The check re-reads it within a bound (60s,
    injectable clock and sleep) before failing; a file that cannot be read fails at once,
    naming the field and the path.
  - **Lines that are not decisions are skipped**: a load line, or a partial last line.
  Unit (`test_qualification_helper.py`): the latest grant's admit found; an admit under
  the newer active key refused; an earlier retired-key admit ignored beside the latest;
  missing, unverified, refused, other reservation, other port, port as text and other key
  each failing naming the lease, its reservation, port and grant key; a lease with no
  signed grant; the record lookup (released and other rows passed over, none found named);
  the check against a file, its skip naming the field, a direct target, the re-read
  finding a line that arrives, the bound reached, and an unreadable file.
- [x] 7.3 Per-observation outcome (D8). Each qualification stage declares the observations
  that require it; at module end a hook logs each observation's outcome by D8's rule —
  made when every requiring stage passed, failed when one failed, unproven when none failed
  and one skipped, naming the skip's prerequisite — writing no file. Unit: observation 2
  recorded unproven naming `management_unit` when its diagnostics stage skipped and every
  other stage passed; observations 4 and 5 resolved independently in one module; a failure
  outranking a skip.
  Done in `helpers/qualification.py`. A module names its `OBSERVATIONS` (the runbook's
  numbers, as strings) and each stage class its `observations`. The roles conftest's
  `pytest_runtest_makereport` wrapper keeps each declared stage's reports in its item's
  stash (`record_report`), and once the module's last item has reported its teardown it
  logs the module's outcomes: made at INFO, failed at ERROR, unproven at WARNING with each
  skip's reason. The conftest's `pytest_sessionfinish` logs a module a stopped run (`-x`)
  left unlogged; each module is logged once. A module needs no fixture. Decided here:
  - **Stages are read from the module's classes**, not the run's items, so a stage the
    run deselected or never collected reads "did not run", and its observations unproven.
  - **Any failed phase fails the stage**, its teardown's included. The last item's
    teardown finalizes the module's fixtures, so a failure in the module's cleanup fails
    that item's stage when it is a declared one: conservative, and stated in
    `record_report`'s docstring.
  - **An observation no stage of the module declares** is unproven, "no stage requiring
    it ran".
  Unit (`test_qualification_helper.py`): the three planned cases on `observation_outcomes`;
  an observation with no stage; each phase's outcome (passed, failed, setup error, setup
  and call skips, teardown failure, not run); reports kept only for declared stages; a
  declared stage not collected reads not run. Two further cases run pytest in a
  subprocess over a constructed module with the roles conftest's two hooks, no stack or
  service involved, as `test_scenario_cleanup_order.py` runs `--setup-plan`. With `-k`
  deselecting one stage, the log shows observation 2 unproven naming the skip's reason, 4
  failed at the last stage, whose teardown failed, 5 made, and 6 unproven at the
  deselected stage, each once. With `-x` after a first failing stage, the session's end
  logs 2 failed and 5 unproven, its stage not run.
- [x] 7.4 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: none; the fields and the reader are read by section 8's modules, in no
  lane. None is owed in the pipeline.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the target and
  helper cases.
  Unit: `make test-e2e-unit`, 659 passed, after both fresh-context passes' fixes.
  `make lock` rewrote `e2e-tests/uv.lock` only; `make check-packaging` passed after it.
  `make check-change` passed all 12 checks, comment hygiene among them. `make test` is
  deferred to section 8's checkpoint, by the owner's direction given in this round's
  implementation invocation: focused suites and packaging before each intermediate commit,
  one full `make test` for the round's frozen implementation. This section touched only
  `e2e-tests`, whose unit suite is the one above; section 8's note records the full run.
  End-to-end scenarios, confirmed: none; section 8's modules, in no lane, are the first
  callers. None is owed in the pipeline.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the target and
  helper cases (confirmed).

Handoff from section 7:

- **For section 8.** A qualification module sets `OBSERVATIONS = ("2",)` (or `("4", "5")`,
  `("6",)`) and gives each stage class an `observations` tuple; the roles conftest does the
  rest. A check an observation needs is a stage, not a fixture's teardown. Admission:
  `check_admission(target, provisioning_client, reservation)`, the reservation the first
  element of the driver's `reservation_of(fulfillment_id)`; it skips naming
  `admission_log` itself. The management unit is `target.management_unit` (VM host); the
  stage reading it skips naming `REAL_PROVISIONING_TARGET.hosts.vm.management_unit` when it
  is `None`, which section 8 writes.
- **Fresh-context check.** First pass, fixed: stages read from the module rather than the
  run's items (a deselected stage had read as made); a teardown failure counted; the hook
  run under pytest in a unit case; an unreadable log named; a trailing copy re-read within
  a bound; the example's optional lines loaded, not only searched. Second pass, fixed: the
  outcomes logged from the report hook after the last item's teardown report, not a
  fixture inside it (a last stage's failed teardown had read as made), with a session-end
  fallback; a lease with no grant failing without the re-read; non-callable `test*`
  attributes; the runbook's heading cited; the management unit's comments describing only
  the field until section 8 reads it; this section's note on `make test`. Declined:
  `pytester` for the subprocess cases, which needs a root-conftest plugin, where the suite
  already runs pytest in a subprocess for `--setup-plan`.

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
  Compensation (review 55 F2, added by its triage): each module's cleanup, after a stage
  fails past the buyer's payment approval, refunds an unrefunded payment and ends a
  delivered guest or host, through `helpers/payment_compensation.py`'s
  `PurchaseCompensation` with the domain's status, refund and real-lane release (a VM
  guest's through the expiry path, back-dated and stepped); what it cannot refund or end
  it reports by negotiation and transaction, as the bare-metal payment purchase does.
  This task writes the matching clause and scenario into the qualification requirement
  in the test-compatibility delta, and the design's rationale beside D8. Unit: a failure after approval refunds and releases; a refund that stays
  refused, or a guest that cannot be ended, is reported naming the purchase.
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
  - `docs/development/TESTING.md`, the bare-metal lane's entry under "### 4. System
    Integration Tests (End-to-End)": `e2e_bare_metal_payment_deal` runs the shared
    purchase stages, the buyer's CLI teardown before the seller's refund, and a cleanup
    that opens any gate still closed and runs unless the last stage recorded the deal
    ended (D16) (added by section 3, which found the paragraph's order and cleanup
    stale);
  - `docs/development/TESTING.md`, "#### The real-provisioning lane": the shared listing,
    `management_unit`, `admission_log` and the qualification markers (D2, D5, D9);
  - `docs/development/TESTING.md`, the paragraph on tests that run shipped tasks through
    real `ansible-playbook`, under "## Ansible Syntax and Native Checks": the
    VM suite also runs the host diagnostics task file against faked `systemctl` and
    `virsh` (D5) (added by section 6, whose fresh-context check found the paragraph
    incomplete);
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
