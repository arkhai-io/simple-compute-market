# Tasks

## Current validation job mapping

The merged CI matrix runs domain suites through `test · test-domains`.
That job runs `make -C domains test`, including the storefront, bare-metal,
API-credit, VM provisioning adapter and VM IaC suites. The root
`test · test-provisioning-iac` job runs common provisioning IaC separately.
The obligations below name the current jobs; completed command results and
historical job names remain evidence for the revisions that produced them.
Validation must inspect the aggregate job's logs for the owed domain suites.

Planned against the design settled in `design.md` and advanced by
`reviews/31-design.triage.md`; replanned from section 2 onwards against D22's revised
cadence and D23, advanced by `reviews/44-design.triage.md`. The buyer-purchase section,
first numbered 2, stopped before its first task (section 3 records the stop); it is
section 3 now, behind a new section 2 that answers the stop (D23), and every later section
moved up one number. Section numbers inside section 1's planned text are the first plan's:
their "section 2" is now section 3.

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
of section 2, not a design question. Neither rule was triggered.

Permanent specifications, `TESTING.md`, `ARCHITECTURE.md`, the runbook and the roadmap are
written at closeout; a section writes only the package and harness documentation its code
needs (the VM IaC README entry, the target example, `e2e-tests/README.md`'s marker list).

Implementation findings worth keeping beyond these notes are in `design.md`,
"Implementation findings".

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
  Done; `11b` also requires `settlement_ref`, and `10a`–`11b` log the identifiers they
  read. The Alkahest drivers' own parts still read `real_escrow_uid`; only stage bodies are
  held escrow-free. D15 and the delta say an earlier stage writes the reference. Unit:
  `test_no_stage_from_fulfillment_onwards_reads_the_escrow` passes.
- [x] 1.2 The expected host (D15's table). `_evaluate_settle_host_id` becomes
  `expected_host_id` for every writer and reader: `08a` writes it, `08c`, `09c`, the VM
  real module's previewed-host check (`test_real_provisioning_deal.py:443`) and the
  bare-metal real module's (`:273`) read it, and `test_real_vm_lane.py` and
  `test_real_bare_metal_lane.py` construct it. Unit: the renamed cases pass, and a
  source check finds no remaining `_evaluate_settle_host_id`.
  Done; `09c` also requires `expected_host_id`. Differed: no source check for the former
  name was kept, since it would be a tombstone; the declared-field checks
  (`test_the_stages_use_only_declared_fields`, `test_a_lane_stage_uses_only_its_states_fields`)
  hold the invariant. Unit: the renamed preflight cases pass.
- [x] 1.3 The handoff is checked from source (delta: each shared input written
  independently of the lease under check). `test_compute_deal_stages.py` asserts, per
  lane row, that every state field a shared stage from `09a` onwards requires is written
  by an earlier stage of that lane — the table's `fulfillment_id`,
  `_create_job_completed`, `expected_host_id`, `teardown_fulfillment_id`,
  `_teardown_job_completed` and `settlement_ref` — and by no stage that reads the lease
  it is compared with. Unit: a lane row whose only writer of `expected_host_id` reads the
  lease fails the check (a constructed source in the test).
  Done as `handoff_faults` (`HANDOFF`, `COMPARED_WITH_THE_LEASE`). Only `expected_host_id`
  is compared with the lease, so only its writers are held to not reading it (by name in
  the writer's own source; a lease reached through a called helper is not seen);
  `teardown_fulfillment_id` is read from the lease by expiry's `10b`, as D15's table says.
  Unit: `test_each_handoff_is_written_earlier_and_independently_of_the_lease` passes for
  the four lanes; the constructed-source cases fail and pass as planned.
- [x] 1.4 **Verification checkpoint.** Unit: `make test-e2e-unit`, with
  `test_compute_deal_stages.py`, `test_real_vm_lane.py`, `test_real_bare_metal_lane.py`
  and the other stage-source suites. Run `make test` and `make check-comment-hygiene`.
  End-to-end: `e2e_deal` and `e2e_deal_buyer_cli` (VM lane) and `e2e_bare_metal_mock_deal`
  (bare-metal lane) run every re-keyed shared stage; `e2e_vm_real_provisioning` and
  `e2e_bare_metal_real_provisioning` run them too but are in no lane, so their unit
  suites are this section's evidence for the real lanes.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the re-keyed
  source checks.
  `make test-e2e-unit` 563 passed; `make test` and `make check-comment-hygiene` passed.
  Corrected: `e2e_deal_buyer_cli` declares its own stages, so only `e2e_deal` and
  `e2e_bare_metal_mock_deal` run the re-keyed shared stages.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the re-keyed
  source checks (confirmed).

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
  Done: `SettlementAdminRouteService(settlements=SettlementLookup(by_reference=…,
  by_negotiation=…), delivery_status=…)`; `SettlementLookup.resolve(reference)` is the
  public resolution, run afresh at each poll; `SettlementEvidenceLookup` and
  `DeliveryStatusHook` (positional-only); `TERMINAL_SETTLEMENT_STATUSES`. Unit: every
  planned case, plus evidence recorded mid-wait and a refusal raised by a lookup;
  `make test-kits` passed.
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
  Done: `load_vm_settlement_evidence_by_ref` and `load_vm_delivery_status`. Application
  integration (`TestSettleWait`) passes for the payments and Alkahest cases. Differed:
  "refunded before delivery is not terminal" is proved by the repository against its real
  database (`test_a_deal_without_delivery_reports_its_evidence_status_to_the_wait`), since
  the route's wait runs on the real clock (`design.md`, "Implementation findings").
  `make test-storefront`: 1215 unit, 530 integration passed.
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
  Done in `deal_controls.py`. Application integration:
  `test_wait_resolves_a_payments_deal_by_its_negotiation_and_its_transaction`, its
  non-terminal waits through the route service on a ticking clock; the Alkahest cases pass
  unchanged. The payments setup moved into `_payment_deal` in `test_http_settlement.py`.
  `make test-bare-metal`: storefront 590 passed.
- [x] 2.4 The API-credit storefront's binding (D23). A by-reference lookup on
  `api_credit_settlement_evidence.settlement_ref` beside `SettlementRepository.get`; the
  delivery status is its issuance progress by the evidence's negotiation. An Alkahest deal's
  escrow resolves by reference, as its evidence records it (D23). Application integration
  (its existing settle-wait cases, `test_force_accept_api.py`, through the typed admin
  client): a payments deal waited on by its negotiation and an Alkahest deal by its escrow
  report as they did.
  Done: `SettlementRepository.get_by_reference`, `SQLiteClient.load_settlement_evidence_by_ref`;
  the evidence's own status before issuance begins. The former case seeded issuance with no
  evidence, which the kit rightly no longer answers; it is replaced by
  `test_settle_wait_reports_a_payments_deal_by_its_negotiation` and
  `test_settle_wait_reports_an_alkahest_deal_by_its_escrow`. `make test-apicredits`:
  storefront 255 passed.
- [x] 2.5 Versions and locks (D23; `docs/development/RELEASING.md`, "Versioning policy";
  `AGENTS.md`, "Package and dependency discipline"). `arkhai-kit-settlement-runtime` takes
  a minor bump against `dev`, its constructor's incompatible change; each of the three
  storefronts is bumped once against `dev` as the policy reads its change, and raises its
  lower bound on the kit to the new minor. Every exact pin on the kit moves with it —
  today `core/buyer`, `kit/config`, `kit/contact-exchange`, `kit/arkhai-payments`,
  `domains/vms/buyer` and `domains/bare_metal/buyer` — each package whose `pyproject.toml`
  changes bumped once against `dev`. Run `make check-uv-version` and `make lock`, and
  commit every lock it rewrites.
  Done. Kit 0.6.0 → 0.7.0; storefronts VM 0.27.0, bare metal 0.27.0, API credits 0.20.0,
  each `>=0.7.0`; the six exact pinners patch-bumped (`core/buyer` 0.6.1, `kit/config`
  0.5.1, `kit/contact-exchange` 0.4.1, `kit/arkhai-payments` 0.6.1, `domains/vms/buyer`
  0.10.2, `domains/bare_metal/buyer` 0.7.2). `make check-uv-version` passed; `make lock`
  rewrote 29 locks, moving versions only.
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
  Owed by validation: `tests.yml`, jobs `test · test-kits` and `test · test-domains`
  — pass with the kit's resolution
  and the three storefronts' bindings.
  `make test-kits`, `make test-storefront`, `make test-bare-metal`, `make test-apicredits`,
  `make test`, `make check-packaging` and `make check-change` (12 checks) passed. Extended:
  `e2e_deal_buyer_cli` and `e2e_non_erc20_settlement` (VM lane) also wait by escrow, which
  VM Alkahest evidence records as its settlement reference.
  Owed by validation: `tests.yml`, jobs `test · test-kits` and `test · test-domains`
  — pass with the kit's resolution
  and the three storefronts' bindings (confirmed).

Handoff from section 2: the bare-metal storefront reports `settlement_verified` until the
fulfillment is active, then `ready`. Closeout's 9.9 gained the
`settlement-servicing/architecture.md` settle-wait paragraph, which named the removed hook.

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

Stopped before its first task as first planned: the bare-metal storefront's settle wait
could not see an `arkhai.payments.v1` deal, since its `settle_status` hook read only the
`escrows` table, which only Alkahest verification writes, so `09b` would have failed every
run by negotiation or transaction. Nothing was implemented then. D23 answers it, and
section 2 implements the answer.

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
  Done: `PurchaseState`, the `PurchaseDriver` protocol, `Purchase01`–`04`; the bare-metal
  driver is `BareMetalPurchaseDriver` (`scenarios/bare_metal/purchase_driver.py`).
  Differed: "hold the loops" is the canonical readiness stages, reused; `seller_listing_id`
  is the module's own listing stage's; `07a` requires `_settlement_imminent`; `08c` is not
  run (`design.md`, "Implementation findings"). `PURCHASE_LANES` joins
  `test_compute_deal_stages.py`'s checks, the handoff's included. `Purchase05` verifies
  against `receipt_trust`. Amended by section 4: `Purchase03` runs the command in the
  background, `Purchase04` correlates from `negotiation_completed` and `payment_approved`,
  and a shared `Purchase09` checks `run_ended`. Unit: `make test-e2e-unit` passes.
- [x] 3.2 Payment records (D4). A stage checks each transaction: bound to its Agreement,
  its receipt over that mandate, its snapshot naming the configured payer and payee, its
  parts' gross equal to the Agreement's price for its duration. The balance sum check reads
  the payer's own balance through `PaymentsClient.get_balance` with the buyer's token
  before the first purchase and after the last approval, and asserts the drop in
  `available` equals the sum of the scenario's own transactions' debits, logging the
  dedicated-account precondition beside the result.
  Done as `Purchase01_PayerBalanceBefore` and `Purchase05_PaymentRecordsChecked`
  (`verify_snapshot`, `verify_receipt`, payer and payee, gross against the Agreement, the
  drop in `available` against that gross). It checks one transaction; observation 2's sum
  over two is section 8's.
- [x] 3.3 The buyer-teardown ending (D15, D16, D10). A shared stage runs
  `market bare-metal teardown --run-id <run>`, records `teardown_fulfillment_id` from the
  deal's fulfillment as delivery status reports it, and ends where `11b` starts; in a mock
  lane `09c2` arms the teardown gate before it and `11a2` drains after it. The delivery-end
  filing's `Unknown` outcome at the unanswerable authority neither fails the stage nor is
  read as delivery, access-end or refund evidence. If a buyer teardown releases the lease
  outside `check_leases`, the section stops and the change returns to design (D15).
  Done as `Purchase10_BuyerTeardown`: the teardown, the lease read `releasing` (a released
  one fails, the D15 case), `teardown_fulfillment_id` checked against the lease's, and one
  convergence advance to `tearing_down`. The D15 case did not arise (`design.md`,
  "Implementation findings"); the filing's outcome is never read.
- [x] 3.4 The bare-metal lane purchase (D16). `test_bare_metal_payment_deal.py` runs, in
  order: the purchase stages and `09a`–`09c`; its re-drive of the run's commit (its own
  stage, as today); the shared buyer-teardown ending; the seller refund of the still-held
  payment (its own stage, the snapshot showing every part reversed); `11b`. Its
  compensating cleanup (`PurchaseCompensation`) and the mock rules' removal are unchanged.
  The module's wall-clock poll of the buyer's fulfillment status goes with the step `09b`
  replaces. If the reverse after the teardown is refused, the section stops and the change
  returns to design (D16). The marker's description in `e2e-tests/pyproject.toml` says
  the buyer's CLI teardown precedes the refund.
  Done; the module also runs bare metal's `09a2` publication close, `Purchase09` and its
  own `12`, which reads the deal released and records the teardown evidence, so the
  cleanup's compensation runs unless `12` recorded it. The cleanup opens any mock gate still
  closed before the compensation and removes the rules after it. The refund after the
  teardown was not refused (D16). Unit: the module's fixtures resolve under
  `test_scenario_cleanup_order.py`'s `--setup-plan`.
- [x] 3.5 The source check (D1; delta "defined once"). `test_buyer_purchase_stages.py`, on
  the pattern of `test_compute_deal_stages.py` and `stage_sources.py`: every scenario
  buying through the shipped buyer declares the purchase stages in order without replacing
  a body, inserts only its own stages between them, and runs the shared ending its lease
  ends by; the bare-metal lane purchase is one row. Unit: a constructed module replacing a
  shared body, or running the buyer-teardown ending and the expiry stages both, fails.
  Done as `purchase_faults` against `expected_order(mock=..., ending=...)`, with checks
  that the purchase stages are not collected where defined, name no mock gate, take
  `PurchaseDriver`, and that `PurchaseState` extends `ComputeDealState`. Unit: the row
  passes; constructed modules fail on a replaced body, both endings, and two stages
  swapped.
- [x] 3.6 **Verification checkpoint.** Unit: `make test-e2e-unit`, with
  `test_buyer_purchase_stages.py` and `test_compute_deal_stages.py`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_bare_metal_payment_deal` (bare-metal lane) runs the purchase stages,
  the shared post-settlement stages with `09b` on a payments deal, the buyer-teardown
  ending and the refund after it.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the purchase
  source check.
  `make test-e2e-unit` 582 passed; `make test` and `make check-change` (12 checks) passed.
  Extended: `07`'s and `07a`'s changed prerequisite runs in `e2e_deal` and
  `e2e_bare_metal_mock_deal`.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the purchase
  source check (confirmed).

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
  Done as `test_vm_payment_purchase.py` over `VmPurchaseDriver`
  (`scenarios/vms/purchase_driver.py`), with its own resource
  (`compute-e2e-payment-purchase-001`), host, pool and GPU model; it also runs its own
  `09a2` capacity-event step and `Purchase09`. The background purchase run,
  `committed_event`, `Purchase09` and the lane buyer are recorded in `design.md`,
  "Implementation findings". The lane's reap fixture also stops a running purchase, and
  `payments_config` is listed first, so a run with no target is a blocked skip before any
  hold. Unit: `make test-e2e-unit` 599 passed, `test_buyer_purchase_run.py` among them.
  Round-1 triage fix (validation 57 V1): the first pipeline run (42267053852) failed at
  `Purchase04` on `model_dump` of a dataclass; the driver now returns `dataclasses.asdict`,
  unit-tested in `tests/unit/test_vm_purchase_driver.py`.
- [x] 4.2 The expiry ending on a payments deal (D17). The back-dated lease, stepped with
  the watchdog held, tears the guest down and releases capacity while the pinned authority
  is unreachable; the module's `11b` asserts it. A stall caused by the unreachable
  authority is product behaviour the change does not alter, and stops the section for the
  owner rather than being worked around.
  Done: the canonical expiry stages run unchanged on the payments deal; no stall arose
  (`design.md`, "Implementation findings").
- [x] 4.3 Lane membership. `e2e_vm_payment_purchase` is registered in
  `e2e-tests/pyproject.toml` and added to `E2E_MODULE`; `test_buyer_purchase_stages.py`
  gains the VM row; `e2e-tests/README.md` lists the marker.
  Done; each row states its ending and a row declaring the other fails;
  `test_compute_deal_stages.py` gains `vms_purchase`; the README gains "VM buyer purchase".
- [x] 4.4 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_vm_payment_purchase` (VM lane) runs the purchase, the shared
  post-settlement stages and the expiry ending against the lane's payments double.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the VM row.
  `make test-e2e-unit` 599 passed (608 after the 57 V1 fix); `make test` and
  `make check-change` (12 checks) passed. Extended: `e2e_bare_metal_payment_deal` runs the
  changed `Purchase03`–`04` and `Purchase09`.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the VM row
  (confirmed).

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
  Done as `create_or_adopt_listing` in `scenarios/vms/composed_listing.py` (VM's, not under
  `helpers/`). Ready mechanisms are the deal mechanisms only (`DEAL_MECHANISMS`), as D2 now
  says. Adoption is the former driver's `listing_for_run` plus the own-mechanism check,
  made before the pause. The Alkahest real module states its terms as a clause
  (`ALKAHEST_SETTLEMENT`); `listing_settlements()` adds the payments clause where
  `PAYMENTS.SELLER_ACCOUNT` is set; `payments_settlement` is shared with `VmPurchaseDriver`.
  Outside the plan: `e2e-tests/pyproject.toml` declares `arkhai-core`.
- [x] 5.2 Unit, in `test_real_vm_lane.py`: creation states one settlement per ready
  mechanism; an Alkahest module and a payments module, in either order, adopt the same
  listing and create no second one; a listing lacking the adopting module's mechanism
  fails naming the listing and its options before any deal; a one-mechanism stack yields
  one option.
  Done against a fake storefront (contact exchange reported ready beside the deal
  mechanisms): every planned case, plus no creation for a ready mechanism without a
  settlement or an unready own mechanism, and the former adoption cases on the helper. Not
  covered at unit level: `listing_settlements()`'s payments branch.
- [x] 5.3 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_vm_real_provisioning` runs the helper but is in no lane; no pipeline
  marker covers it, and none is owed, since a real resource exists only on a target.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the helper's
  cases.
  `make test-e2e-unit` 607 passed; `make lock` rewrote `e2e-tests/uv.lock` only;
  `make check-packaging`, `make check-change` (12 checks) and `make test` passed.
  Extended: `e2e_vm_payment_purchase` runs `payments_settlement`.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the helper's
  cases (confirmed).

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
  Done: `roles/vm-management/files/host_diagnostics.sh`, run through Ansible's `script`
  module, sets `host_diagnostics_data`; `main.yml` includes it for `vm_action == "diagnose"`.
  The prerequisites skip starting libvirtd for `diagnose`, the units are read before
  guests are counted, and a failed call fails the job (`design.md`, "Implementation
  findings"). The README gains "6. Read Host Diagnostics". Library integration:
  `tests/test_host_diagnostics.py`, the script against faked `systemctl`, `virsh`, `uname`
  and `/proc`, and natively the shipped task file through `ansible-playbook`; it joins the
  native gate's `NATIVE` list. `make test-provisioning-iac`: VM 182 passed, 6 native
  skipped; `make test-provisioning-iac-native` passed (20 native VM tests).
- [x] 6.2 The action (D5). A host-scoped action (`diagnose`), registered in `codec.py`'s
  result-fact and fact-action maps and `bundle.py`'s actions, submitted by
  `host_operations_service.py` beside `check` and routed by the controller. A
  `management_unit` not matching systemd's unit-name syntax is refused at submission, no
  job queued; an unknown host is the route's error. The mock profile's default output
  (`mock_output.py`) renders a fact from the job's parameters. Unit: the unit-name
  validation (valid names, a path, a space, an empty name). Application integration
  (`test_hosts_api.py`, through the typed client): a submitted job succeeds in the mock
  profile with a fact the parse accepts; an invalid unit is refused with no job queued.
  Done. The route is `GET /api/v1/hosts/{host}/diagnostics?management_unit=…`
  (`provisioning_host_diagnostics`, admin only), bound in `controllers/hosts_controller.py`
  beside the capacity check (the router factory renamed `make_host_operations_router`).
  The unit is checked on the wire model (`HostDiagnosticsRequest`), so the route answers
  422 and the typed client refuses before sending. The result kind is `vm_diagnose`. The
  mock output is a guestless host with stable invocation IDs (UUIDv5 of host and unit).
  Round-1 triage fix (review 55 F1): the management unit is restricted to service units
  (`check_service_unit_name`). Unit: `test_host_operations_service.py`,
  `test_host_diagnostics.py` (the unit-name cases), the adapter's `test_vm_codec.py` and
  `test_vm_mock_output.py`. Application integration: `test_hosts_api.py::TestHostDiagnostics`,
  waiting on `wait_until_idle`, with a rejection-path test asserting status and stored jobs
  only, and an unknown host refused with 404. `make test-provisioning-adapter` 292 passed;
  `make test-provisioning` 708 unit and 584 integration passed after the fix.
- [x] 6.3 The client (D5's interface). `diagnose_host(host_id, management_unit=None)` on
  `VmOperatorClient` and `SyncVmOperatorClient` returns the `JobSubmitResponse`, and the
  client gains no polling. `HostDiagnostics.from_job_result(result)` in
  `vm_provisioning_operator` returns the typed facts or raises a named error naming the
  missing or malformed field, returning no partial result. Unit: a well-formed result
  parsed; each missing field and a wrong-typed field refused naming it. The endpoint
  coverage and client contract tests include the new route.
  Done: an invalid unit raises `pydantic.ValidationError` before sending;
  `from_job_result` raises `HostDiagnosticsError` whose `field` names the dotted path, with
  strict field types. `HostDiagnostics` exposes `libvirtd`, `relay_client`, `management`
  and `reported_units()`. Unit: every missing and wrong-typed field refused by name; the
  sync/async contract test and the endpoint coverage test pass.
- [x] 6.4 Versions and locks (`docs/development/RELEASING.md`, "Versioning policy";
  `AGENTS.md`, "Package and dependency discipline"). Bump the adapter's and the client's
  versions once each against `dev`, raise any exact pin that moves, run
  `make check-uv-version` and `make lock`, and commit every lock it rewrites. A package
  section 2 already bumped is bumped again only if this section needs a larger bump.
  Done: client 0.12.0, adapter 0.18.0 (its bound on the client `>=0.12.0`); the service's
  dev group raised, the service not bumped. `make check-uv-version` passed; `make lock`
  rewrote four locks.
- [x] 6.5 **Verification checkpoint.** Unit and application integration:
  `make test-provisioning`, `make test-provisioning-adapter`, `make test-provisioning-iac`.
  Run `make test`, `make check-packaging` (6.4 changes versions and locks) and
  `make check-comment-hygiene`.
  End-to-end: no pipeline marker runs the job; section 8's observation 2 module, in no
  lane, is its first system-level caller. None is owed in the pipeline.
  Owed by validation: `tests.yml`, jobs `test · test-provisioning`,
  `test · test-domains` and `test · test-provisioning-iac` — pass with the
  new action, client and playbook task.
  The suites, `make test`, `make check-packaging` and `make check-change` (12 checks)
  passed. Corrected: the pipeline's `e2e-vm` job runs `make test-provisioning-iac-native`,
  so it runs the task file and script against fakes, not the role's dispatch or a real
  host.
  Owed by validation: `tests.yml`, jobs `test · test-provisioning`,
  `test · test-domains` and `test · test-provisioning-iac` — pass with the
  new action, client and playbook task (confirmed).

Handoff from section 6: closeout's 9.9 gained `TESTING.md`'s native-test paragraph.

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
  Done; `e2e-tests` raises its client bound to `>=0.12.0`. Unit: the planned cases, the
  example's commented lines valid once uncommented, and each field refused on the other
  domain or access mode.
- [x] 7.2 The admission-log reader (D9). It reads the file's lines as the plugin's
  documented log contract (`tools/frp-grant-admission/README.md#the-log`) and, for one
  delivered lease, finds an `admit` line with `verified` true, `jti` equal to the
  reservation, `remote_port` equal to the lease record's `remote_port`, and `kid` equal to
  its `grant_key_id`, the record read through the relay's leases
  (`GET /api/v1/relays/{relay_id}/leases`). Unit: a matching line found; a line under the
  relay's newer active key but not the lease's recorded key refused; an earlier `admit`
  under a retired key ignored when the latest grant's line is present; a missing, unverified
  or mismatched line failing naming the lease.
  Done in `helpers/qualification.py` (`relay_lease_record`, `require_admitted`,
  `check_admission`). Beyond the plan: a direct target passes, the trailing copy is re-read
  within a bound (60s), and non-decision lines are skipped (`design.md`, "Implementation
  findings"). Unit (`test_qualification_helper.py`): the planned cases and those.
- [x] 7.3 Per-observation outcome (D8). Each qualification stage declares the observations
  that require it; at module end a hook logs each observation's outcome by D8's rule —
  made when every requiring stage passed, failed when one failed, unproven when none failed
  and one skipped, naming the skip's prerequisite — writing no file. Unit: observation 2
  recorded unproven naming `management_unit` when its diagnostics stage skipped and every
  other stage passed; observations 4 and 5 resolved independently in one module; a failure
  outranking a skip.
  Done in `helpers/qualification.py`, through the roles conftest's
  `pytest_runtest_makereport` (logging after the last item's teardown report) and
  `pytest_sessionfinish` (a stopped run). Stages are read from the module's classes and
  any failed phase fails a stage (`design.md`, "Implementation findings"). Unit: the planned
  cases, each phase's outcome, and two subprocess pytest runs over a constructed module
  (`-k` deselection and `-x`).
- [x] 7.4 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: none; the fields and the reader are read by section 8's modules, in no
  lane. None is owed in the pipeline.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the target and
  helper cases.
  `make test-e2e-unit` 659 passed; `make check-packaging` and `make check-change` (12
  checks) passed. `make test` was deferred to section 8's checkpoint by the owner's
  direction for the round (one full run for the frozen implementation).
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the target and
  helper cases (confirmed).

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

- [x] 8.1 Observation 2 (D1, D3, D5, D9). Two CPU-only VM purchases through the shared
  purchase stages on the target's host, the listing through section 5's helper. A
  heartbeat over SSH on the first guest runs across the second guest's create and
  teardown and shows no gap over five seconds; host diagnostics (section 6) are read before,
  during and after, and the pass criterion is D5's (the management unit keeps one
  invocation ID, stays active and adds no restarts; libvirtd adds no restarts, has no
  failed result, and keeps one invocation ID across the reads taken while the first guest
  runs), a changed invocation or a grown restart count failing the module naming the unit;
  both leases end through `10a`/`10b` back-dating and stepped watchdog cycles. Without
  `management_unit` the diagnostics' management reads skip naming it.
  Done as `scenarios/vms/test_vm_qualification.py` over `RealVmPurchaseDriver`
  (`scenarios/vms/real_purchase_driver.py`), the purchase parts shared with the lane driver
  as `VmPurchaseParts`. The second purchase runs the shared definitions through `run_stage`
  and completes its own teardown without `11b` (`design.md`, "Implementation findings").
  09i checks the payer's drop against both debits (D4). Diagnostics are read five times,
  12a and 12b applying D5's criterion (`host_generations.py`). Both guests' shapes, an
  unrelated key, admission, and (round-2 triage, review 61 F1) no GPU are checked per
  guest. The real resource and `listing_settlements` moved to `composed_listing.py`.
- [x] 8.2 Observations 4 and 5 (D1, D6, D10, D16's ending). The normal cycle through the
  purchase stages and the buyer-teardown ending, then the successor and refusal cycle in
  the same module, using the first cycle's consumed UID: the reclaim meets the planted
  foreign descendant, is queued for retry with its error recorded and a next retry time,
  its log names the descendant, the lease stays `releasing`, and after fixture-only repair
  the same job completes. The cycle reuses the cleanup-qualification fixtures
  (`working_data_qualification.py`, `working_data_probe.py`). No GPU is checked.
  Done as `scenarios/bare_metal/test_bare_metal_qualification.py` over
  `RealBareMetalPurchaseDriver` (`scenarios/bare_metal/real_purchase_driver.py`), run once
  per `cleanup_cycle` (`normal`, then `refusal`), each with its own state, key, profile and
  compensation stage (12). 11a1, the refusal cycle only, logs the job's record as the
  operator notification D5 names. Without `cleanup_qualification` the working-data stages
  and the refusal cycle skip naming it; the refusal cycle also skips without a verified
  normal cycle. The real listing's terms are the deployment's (`design.md`,
  "Implementation findings").
- [x] 8.3 Observation 6 (D5's consumed-UID read). It reapplies both hosts' canonical
  registrations and runs a publication cycle; existing listings are adopted with
  identities, states and pauses intact, no duplicate host, pool, resource, allocator or
  listing appears, unexpired relay quarantine is retained, and the consumed-UID history,
  read through the working-data operator route's `policy` operation before and after, is
  unchanged. It needs both hosts and reports a blocked skip naming the missing one.
  Done as `scenarios/vms/test_real_provisioning_reapply.py`, with a new
  `bare_metal_storefront_loops_held`. It first steps a publication cycle on each
  storefront so its "before" read is settled, compares a `RegistrationSnapshot` per host
  (`registration_faults`: host rows, the site's declarations bound to it — the
  "allocator" — the listings on its resource, and its relay's quarantined and active
  ports), and drains the VM storefront's capacity events itself (68 T1), since an
  idempotent reapply adds none. The evidence for holding no bare-metal timer (70 O1, D3):
  - no stage steps or asserts either bare-metal timer; its only advances are held
    storefront cycles;
  - neither timer writes host rows, pools or declarations, and the service's state guards
    (a release writes `released_at` only on an unreleased lease; a released reservation
    returns before its effect; allocation never takes a quarantined port) keep either from
    restoring what a faulty reapply removed; the consumed-UID history only grows;
  - relay-port reconciliation is ungated on both sites and could re-release an
    un-released lease, so each unexpired quarantined port is compared by its whole record,
    release time included (68 T2), its zone-less times read as UTC.
  Scope and limits: an idle stack after the other modules' cleanup; no claim that a live
  tenancy survives; an empty before-state proves nothing about preservation; a bare-metal
  lease an earlier module left releasing may cause a false failure, never a false pass.
- [x] 8.4 Common to the three (D1, D8, D9, D10). Each module is in no lane, reports a
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
  Done. Each module sets up its payments target, target(s) and executions before any
  hold; observation 6 holds both storefronts' loops and the VM site's timers (8.3). Every
  stage requires its module's or its cycle's observations (`OBSERVATIONS`,
  `CYCLE_OBSERVATIONS`), 11a1 narrowing to the refusal cycle. `Purchase03` fails naming the
  payer when the run records no approval. `PurchaseCompensation` reports what it cannot
  read or end as `UnreleasedDelivery` and skips the refund once the module began ending
  the purchase (`ending_begun`); each real driver supplies `purchase_status` and
  `end_purchase` through the real lane's recovery with the recorded job identifiers. The
  delta gained the compensation clause and scenario, and D8 the stage-requirement rule and
  compensation rationale. Unit: `test_payment_compensation.py`,
  `test_qualification_modules.py`, `test_buyer_purchase_run.py`. Not unit-tested: the
  modules' cleanup wiring, which only a target run exercises.
- [x] 8.5 Wiring checks. Unit: each module registered under its marker in no lane
  (absent from every `E2E_*_MODULE`); the observation 2 and observations 4 and 5 modules
  as rows of the purchase source check, extending the purchase stages without replacing a
  body; a module with no target configured reporting a blocked skip before any stage
  (with injected settings). `e2e-tests/README.md` lists the three markers and how an
  operator runs them through `test-module`.
  Done: `test_qualification_modules.py` (markers, `OBSERVATIONS`, cycles, the README's
  lines, `target_host`'s skips with injected settings), the purchase and stage-state source
  checks, and `test_scenario_cleanup_order.py`'s `--setup-plan` over the three modules.
  Differed: the no-target skip is two checks, `target_host` with injected settings and the
  setup order, since the payments target's absence cannot be injected in a unit run. Pure
  checks for D5's criterion, the listing's status and `registration_faults`. The README
  gains "Real-provisioning qualification".
- [x] 8.6 **Verification checkpoint.** Unit: `make test-e2e-unit`. Run `make test` and
  `make check-comment-hygiene`.
  End-to-end: `e2e_vm_qualification`, `e2e_bare_metal_qualification` and
  `e2e_real_provisioning_reapply` are in no lane; the deployment's operator runs them on
  the post-merge candidate (D7), and their sanitized findings are triaged as the owner's
  notes on that round. In the pipeline they collect and skip, which the unit wiring checks
  prove. The lanes' `e2e_vm_payment_purchase` and `e2e_bare_metal_payment_deal` exercise
  the shared stages these modules extend.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the wiring
  checks.
  `make test-e2e-unit` 727 passed; `make check-change` (12 checks) and
  `make check-packaging` passed. `make test` stopped at `test-apicredits` on a full root
  filesystem (`test-deployment-packaging` likewise), neither covering code this round
  changes; the round-2 fix run below passed `test-apicredits`. Corrected: the pipeline
  deselects the three modules by marker rather than collecting and skipping them.
  Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the wiring
  checks (confirmed).

Post-merge deployment run (owner's notes, sanitized): an independent operator
deployment ran the three modules on the merged revision, over relay access only, against
CPU-only hosts, with both storefronts settling TEST payments through a hosted payments
service over TLS and a pinned dispute authority that does not answer. Observation 2 made
(47 passed); observations 4 and 5 made (67 passed, the normal cycle's refusal-only stage
skipped by design); observation 6 made (7 passed); four purchases, each payer check
exact. Three causes found before the passing runs, none in the scenarios: the runner
lacked a `market` carrying `market bare-metal` (named with `MARKET_CLI_BIN`); the
cleanup qualification's operator route was one only the provisioning service could
reach; and a storefront started before its registry served held no recommended dispute
authority and refused the payments listing until restarted, recorded as an unowned gap
in `docs/development/ROADMAP.md`. The runbook's qualification section states all
three. Observations 1 and 3 were not run.

Round-2 triage fixes (review 61, records 67 and 70, and 68 T1 and T2; dispositions
delegated under the owner's best-judgment direction): 61 F1, each VM guest probed for no
GPU (`helpers/ssh_access.py`'s PCI probe); 70 O1, the holds reconciled in 8.3, 8.4 and D3
with no code change; 68 T1, observation 6 drains capacity events itself; 68 T2, quarantine
compared by the whole lease record. `make test-e2e-unit` 745 passed;
`make test-provisioning-iac`, `make check-packaging` and `make check-change` passed.
`make test` passed through `test-e2e-unit`, `test-apicredits` included, and stopped at
`test-release-tooling` on the host's mixed Git installation refusing
`git maintenance run --detach`; the suites after it passed alone.

Merge repair (validation 84; owner's direction, workflow log seq 154): `dev` moved image
publication into `scripts/publish_artifacts.py`, failing
`test_provisioning_build_produces_the_tag_consumed_by_push_images` on `dev` too.
`scripts/tests/test_image_publication_contract.py` now runs the publisher's own argument
parsing on `push-images`' invocation and asserts the tag and push commands start from the
provisioning build's image. `make test-release-tooling` passed (2680). Validations 88 and
91 passed full CI after it.

Second merge repair (`dev` held every compute lane module's timers, #356): the merge kept
both sides of `ARCHITECTURE.md`'s testing strategy and the test-compatibility
specification, kept this change's `test_bare_metal_payment_deal.py` (its stages already
step delivery under held convergence) and `dev`'s `test_image_publication_contract.py`, and
added `alice_loops_held` to `test_vm_payment_purchase.py`, the one lane module the new
lane-holds check found without it. `make test-e2e-unit` 782 passed and
`make check-comment-hygiene` passed on the merge.

Dispute coverage as a run setting (pre-closeout triage 78, revisited on the owner's
delegated direction, workflow log seq 164; outside the plan; `design.md`, "Implementation
findings"): `helpers/payments.py`'s `dispute_window_seconds` reads
`PAYMENTS.DISPUTE_WINDOW_SECONDS`, replacing the 15-day constants in
`vms/composed_listing.py`, `bare_metal/purchase_driver.py` and `test_vm_payment_deal.py`;
`e2e-tests/README.md` documents it. Unit: `make test-e2e-unit` 767 passed, 22 new cases in
`tests/unit/test_dispute_coverage.py`. `make check-comment-hygiene`, `make check-packaging`,
`make check-repository` and `scripts/change-workflow check index` passed. Validation 91
passed at `2f64eec1` (pipeline run 42341265288, `tests.yml` run 42341268726, all 18 jobs),
at the default coverage only.

## 9. Closeout

The closeout task's eleven parts, in order (`openspec/README.md#plan-closeout-requirements`).
Closeout changes documentation only; a part needing a code edit returns the change to
implementation. Replanned against the reviewed design: first numbered 8, now covering D23
and the `settlement-servicing` delta.

Worked in order at closeout, after the owner accepted the operator's outcomes (workflow log
seq 180).

- [x] 9.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read the
  comments sections 1–8 added against `AGENTS.md`'s "Python comments and docstrings". A
  finding returns the change to implementation.
  `make check-comment-hygiene` passed. A search of the added lines (`git diff a725e377
  HEAD`, code and configuration) for review, triage, migration, former-location, section
  and decision references found only "Observation N" docstrings and comments, which name
  the runbook's observations, a permanent document's terms. Review 92 read the comments
  too and found none to fix.
- [x] 9.2 **Import placement — confirm.** Every import sections 1–8 added is at module
  level, or local for a stated reason. One that should move returns the change to
  implementation.
  No added line in the diff from `a725e377` is an indented `import` or `from … import`, so
  every added import is at module level.
- [x] 9.3 **Documentation compliance.** Check D1–D10, D12 and D15–D23 against
  `openspec/README.md`'s placement rules: normative behaviour in the deltas, rationale in
  `openspec/specs/test-compatibility/architecture.md` and `TESTING.md`, nothing durable
  left only in `design.md`. D18, D20 and D22 have no permanent destination, as the proposal
  records. D23's normative rule is the `settlement-servicing` delta's.
  Each decision has the destination the proposal names, as the promotion record lists;
  the package documentation sections 5–8 wrote (the VM IaC README's diagnose action, the
  target example, `e2e-tests/README.md`'s qualification and purchase sections) matches
  the code. Two placements beyond 9.9's list: D23's current state and its two gaps went to
  `ROADMAP.md` Goal 4 (the kit-extraction goal) rather than Goal 1, and D7's candidate
  definition and outcome sorting to `VALIDATION_RUNBOOK.md` §29's preamble. Found stale and
  corrected while promoting: `TESTING.md`'s bare-metal lane entry said the payment
  purchase re-drives "through `settle_agreement`"; it repeats the canonical lifecycle
  `commit`. The implementation findings `design.md` now holds are change history, not
  durable rules beyond what the promoted documents state.
- [x] 9.4 **Narrative compression.** Compress section notes to final behaviour, material
  evidence, deferred work and destinations, moving any rationale into `design.md` first.
  Section 3's stop notes compress to the stop, its cause, and D23 as the answer.
  Sections 1–8 notes and handoffs compressed (this file from 141 KB to 67 KB); every
  planned task statement and `Owed by validation:` line kept as written. Alternatives,
  debugging findings and triage dispositions worth keeping moved first to `design.md`,
  "Implementation findings". `make check-tasks` passed.
- [x] 9.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 1 (D12):
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
  Observations 2, 4, 5 and 6 were each made (9.8), so the qualification row closes for
  them, and their result is absorbed into Goal 1's current state with its limits (CPU
  targets, TEST payments; no GPU offer, physical host, serving dispute authority, hosted
  storefront or real-money purchase; payment maturity not inferred). Observations 1 and 3
  stay owed, so the row is restated as theirs alone, unowned, rather than naming this
  change. The five new gaps are rows: GPU purchase, pushed notification and the debit
  listing ("Outside this repository") in Goal 1; the buyer settle status route and the
  kit-owned evidence store in Goal 4, whose current state now names the kit's settle-wait
  resolution. The real modules' first-run row stays unowned, reworded to name them the
  Alkahest modules and to drop "evidenced only by accepted live observations", which the
  qualification run made untrue.
- [x] 9.6 **Campaign index currency.** In `openspec/changes/README.md`, set this change's
  row to `in closeout` with notes matching the outcome, and update its campaign's
  dependency lines (`qualify-arkhai-real-provisioning` and `add-mvp-payments-lane-double`,
  both archived) to what is true. Run `make check-change-index`. Name the update in the
  promotion record.
  Row `in closeout`, its Notes the outcome and destinations; both dependency lines now say
  what each delivered and that this change is in closeout. No other row changed.
  `scripts/change-workflow check index` passed; it runs again after the archive (9.11).
- [x] 9.7 **Packaging.** Run `make check-packaging` and resolve every failure, then
  `make check-architecture-change CHANGE=qualify-real-provisioning-by-scenario`; the change
  owns no architecture exception row.
  `scripts/change-workflow run pre-archive` passed at `acd3a590`: `make check-packaging`
  (locks, environments, Python selection, layout, layers, scope, dependencies, kinds all
  OK) and `make check-architecture-change` ("owns no architecture row"). The change
  touched no `.agents/`, `.claude/` or `.codex/` path.
- [x] 9.8 **End-to-end pipeline.** Confirm the pipeline passes on the closeout candidate
  and record the run, its result, and the scenarios exercising this change:
  `e2e_bare_metal_payment_deal`, `e2e_bare_metal_mock_deal` (bare-metal lane);
  `e2e_vm_payment_purchase`, `e2e_deal`, `e2e_vm_payment_deal` (VM lane; the last for the
  settle wait's resolution of a payments deal by its negotiation). Record the operator's
  run of `e2e_vm_qualification`, `e2e_bare_metal_qualification` and
  `e2e_real_provisioning_reapply` on the post-merge candidate (D7): each observation made,
  or failed or unproven with a named cause outside this change, as triaged from the
  owner's notes. An observation failed or unproven by the scenario itself returns the
  change to implementation (D7).
  - **Pipeline.** Validation 91 passed at `2f64eec1`, the commit pre-closeout review 92
    read: `e2e.yml` run 42341265288, e2e-vm, e2e-bare-metal and e2e-apicredits all
    success, its runner image rebuilt from that commit. The orchestrating session's audit
    of the run's log (workflow log seq 174): VM 180 passed and 2 skipped, bare metal 95
    passed, API credits 4 passed, 19 modules; the native VM Ansible gate passed. The two
    skips are `e2e_vm_payment_deal`'s operator-end case and refund stages, blocked
    without `MEDIATION.SERVICE_URL` as the specification allows, not counted as passed.
    So `e2e_bare_metal_payment_deal`, `e2e_bare_metal_mock_deal`,
    `e2e_vm_payment_purchase` and `e2e_deal` passed, and `e2e_vm_payment_deal`'s commit,
    delivery, replay and servicing stages, its settle wait on the negotiation included.
    The lanes ran only the default 15-day dispute coverage.
  - **CI owed by validation.** `tests.yml` run 42341268726 at `2f64eec1`, all 18 jobs
    success: `test · test-e2e-unit` 767 passed (sections 1–8's source, purchase and helper
    tests); `test · test-kits` and `test · test-domains` (section 2); `test ·
    test-provisioning` and the compute-provisioning jobs (section 6). No job failed, so
    `dev`'s baseline run 42299053370 at `a725e377` compared nothing.
  - **Candidate.** Closeout changes no code, and the only commit after `2f64eec1` is
    `acd3a590`, which edits only the change index, so these runs describe the code the
    closeout commit carries; no waiver was needed.
  - **The operator's run** (`reviews/94-operator-qualification.md`, the operator's
    sanitized summary; accepted by the owner, workflow log seq 180). The three modules ran
    from runner source `2f64eec1` against a stack built from `e4011f4b`, whose difference
    from `2f64eec1` is harness, test and documentation only (no application code, chart,
    lock or dependency), with `dev` at `a725e377` merged in. Purchases used the shipped
    buyer CLI and Arkhai TEST payments; no Alkahest module, live charge or financial
    clock manipulation was used. Outcomes, each per D8:
    - observation 2 **made** — `e2e_vm_qualification`, 47 passed, none skipped: two
      CPU-only relayed guests, the first session's heartbeat surviving the second's create
      and removal (longest gaps 1.107 s and 2.000 s against the 5 s bound), management and
      libvirtd generations unchanged, both leases ended by expiry;
    - observations 4 and 5 **made** — `e2e_bare_metal_qualification`, 67 passed and one
      intended skip, the refusal-only stage parametrized for the normal cycle, which
      observation 4 does not require: the normal cycle's working data and activity
      removed with sentinels unchanged and capacity restored; the successor's fresh UID
      and key, its reclaim refusing the planted descendant with the job queued for retry
      and capacity held, then completing on its first automatic retry after fixture-only
      repair;
    - observation 6 **made** — `e2e_real_provisioning_reapply`, 7 passed, none skipped:
      both hosts' registrations, resources, pools, allocators, listings and relay state
      adopted, with a nonempty consumed-UID history and the unexpired quarantine records
      unchanged.
    An earlier bare-metal attempt failed in the operator's profile setup before any
    purchase, job or lease, and passed after the operator corrected its own configuration
    with no application change: a topology cause, retained by the operator as failed.
    Limits the outcomes keep: controlled CPU targets, not a GPU offer or a physical host;
    VM expiry stepped, not waited out; reapply on an idle stack; teardown does not prove
    payment maturity; no hosted public storefront, serving dispute authority or
    real-money purchase. No observation failed or was unproven, so nothing returns the
    change to implementation.
- [x] 9.9 **Promotion.** Write, and record in the promotion record:
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
  Written as listed; the promotion record below names each destination. The runbook's
  §25 gained "Run the qualification scenarios on a candidate" with the deployment's
  inputs, the `helm test` payments check, and the three commands; §29's preamble gained
  the scenarios as the first method, the per-observation outcome and its sorting by cause
  (D7, D8), and the candidate's definition of source (D7). The settlement-servicing
  paragraph was split in two, the second correcting the removed hook's name to bare
  metal's delivery status. Beyond the list: `ROADMAP.md` Goal 4 (9.5). None of the
  capabilities is organized by an `index.md`, so no index is written.
- [x] 9.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=qualify-real-provisioning-by-scenario`, resolve every
  match, then `openspec validate qualify-real-provisioning-by-scenario --strict`.
  `scripts/change-workflow run pre-commit --base dev` passed: index, tasks and skills
  checks, `validate --strict` ("is valid"), and `make check-repository`'s eight checks,
  documentation citations included. Its first run found one unresolvable citation, the
  target example's path in the promotion record read without its `.example` suffix,
  reworded as the rest of this file cites it.
- [x] 9.11 **Archival.** `openspec archive qualify-real-provisioning-by-scenario -y`,
  merging the test-compatibility, physical-provisioning and settlement-servicing deltas;
  the change's row then links to its archive directory.
  No permanent `spec.md` held any of the deltas' requirements before the archive, so they
  merged without `--skip-specs`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 — external-topology scenarios minimally extend locally verifiable ones; topology is the deployment's | `openspec/specs/test-compatibility/spec.md#requirement-an-external-topology-scenario-extends-a-locally-verifiable-scenario`; `docs/development/TESTING.md#locally-verifiable-and-external-topology-scenarios`; `docs/development/ARCHITECTURE.md#testing-strategy`; `openspec/specs/test-compatibility/architecture.md#ordinary-arkhai-purchase-evidence` (the scenarios beside the retained operator method) |
| D2 — one listing offers every composed deal mechanism; adoption requires the module's own | `openspec/specs/test-compatibility/spec.md#requirement-a-real-resources-listing-offers-every-composed-deal-mechanism`; `docs/development/TESTING.md#the-real-provisioning-lane` |
| D3 — VM leases end by back-dating and a stepped watchdog cycle, bare metal by the buyer's teardown; holds | `openspec/specs/test-compatibility/spec.md#requirement-a-compute-buyer-purchase-settled-through-arkhai-payments-runs-in-each-compute-lane` and `#requirement-real-provisioning-qualification-scenarios-make-the-owed-observations`; `docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes` (observation 2); `docs/development/TESTING.md#the-real-provisioning-lane` (observation 6's holds) |
| D4 — per-transaction checks and the balance sum check under a dedicated-account precondition | `openspec/specs/test-compatibility/spec.md#requirement-a-compute-buyer-purchase-settled-through-arkhai-payments-runs-in-each-compute-lane`; `openspec/specs/test-compatibility/architecture.md#ordinary-arkhai-purchase-evidence`; `docs/development/ROADMAP.md#goal-1--consolidate-physical-resource-authority-in-the-provisioning-service` (the debit-listing row) |
| D5 — the host diagnostics VM operator job, its pass criterion, observation 5's notification | `openspec/specs/physical-provisioning/spec.md#requirement-a-vm-hosts-diagnostics-are-read-through-an-operator-job`; `domains/vms/provisioning/iac/README.md` ("6. Read Host Diagnostics"); `docs/development/TESTING.md#the-real-provisioning-lane` and `#ansible-syntax-and-native-checks`; `docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes` (observations 2 and 5); `docs/development/ROADMAP.md` Goal 1 (the pushed-notification row) |
| D6 — observation 4 checks no GPU | `docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes` (observation 4); `docs/development/ROADMAP.md` Goal 1 (the paid GPU purchase row) |
| D7 — acceptance by cause, the frozen candidate, who runs the scenarios | `docs/development/VALIDATION_RUNBOOK.md#run-the-qualification-scenarios-on-a-candidate` and `#observations-the-qualification-owes` |
| D8 — per-observation outcomes, free-form sanitized evidence, compensation | `openspec/specs/test-compatibility/spec.md#requirement-real-provisioning-qualification-scenarios-make-the-owed-observations`; `docs/development/TESTING.md#locally-verifiable-and-external-topology-scenarios` and `#the-real-provisioning-lane`; `docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes` |
| D9 — grant admission read from the plugin's log at a target-named path, by the lease's recorded key | `openspec/specs/test-compatibility/spec.md#requirement-the-real-provisioning-target-names-diagnostics-and-admission-inputs` and `#requirement-real-provisioning-qualification-scenarios-make-the-owed-observations`; `docs/development/TESTING.md#the-real-provisioning-lane`; the target example (`config-real-provisioning-target.yml.example`, under `e2e-tests/config/`) |
| D10 — the dispute authority is pinned and need not answer | `openspec/specs/test-compatibility/architecture.md#ordinary-arkhai-purchase-evidence`; `openspec/specs/test-compatibility/spec.md` (the delivery-end filing scenario) |
| D12 — roadmap ownership | `docs/development/ROADMAP.md` Goal 1 (current state; the observations 1 and 3 row; the GPU purchase, pushed-notification and debit-listing rows; the real modules' row) and Goal 4 (current state; the buyer settle status route and kit-owned evidence store rows) |
| D15 — post-settlement stages shared across both sets and keyed on the settlement reference, except the ending | `openspec/specs/test-compatibility/spec.md#requirement-the-canonical-compute-deals-shared-stages-are-defined-once`; `docs/development/TESTING.md#the-canonical-compute-deal` |
| D16 — the bare-metal payment purchase on the shared stages, the buyer's teardown before the refund | `openspec/specs/test-compatibility/spec.md#requirement-a-configured-bare-metal-payment-purchase-is-qualified-end-to-end`; `docs/development/TESTING.md#4-system-integration-tests-end-to-end` (the bare-metal lane) |
| D17 — the VM lane purchase with its own resource and host, ending by expiry | `openspec/specs/test-compatibility/spec.md#requirement-a-compute-buyer-purchase-settled-through-arkhai-payments-runs-in-each-compute-lane`; `docs/development/TESTING.md#the-canonical-compute-deal` |
| D18 — in-cluster payments need no chart or kit work | No permanent destination: the storefront charts' CA option and the kit's transport rule are already specified (`openspec/specs/deployment-state/spec.md`) |
| D19 — the external run's payments target and the storefront payments check first | `docs/development/VALIDATION_RUNBOOK.md#run-the-qualification-scenarios-on-a-candidate`; `docs/development/TESTING.md#the-real-provisioning-lane` |
| D20 — the local payments target is delivered | No permanent destination: a dependency delivered, in the change's history |
| D21 — stepping rather than waiting is the existing rule | `docs/development/TESTING.md#locally-verifiable-and-external-topology-scenarios` (citing "Tests wait on events, never on durations") |
| D22 — implementation cadence | No permanent destination: the change's history |
| D23 — the settle wait's resolution and terminality are the settlement-runtime kit's | `openspec/specs/settlement-servicing/spec.md#requirement-the-settle-wait-resolves-a-settlement-by-its-reference-or-its-negotiation`; `openspec/specs/settlement-servicing/architecture.md#servicing-lifecycle`; `docs/development/ROADMAP.md#goal-4--make-a-domain-a-composition-of-kit` |
| Principles 1–5 (scenario kinds, minimal extension, topology, externally supplied and free-form evidence) | `docs/development/TESTING.md#locally-verifiable-and-external-topology-scenarios`; rule 2 also `docs/development/ARCHITECTURE.md#testing-strategy` |
| Kit-unification principle D23 applies | Not promoted (`design.md`, Open Questions) |
| Roadmap currency (closeout part 5) | `docs/development/ROADMAP.md` Goals 1 and 4, as D12 above |
| Campaign index currency (closeout part 6) | `openspec/changes/README.md`, "Lesser goal — Reach hosts and VMs that have no inbound route": this change's row and its two dependency lines |
