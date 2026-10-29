# Tasks — compute lease activation at the site

Design-stage plan; no implementation is claimed. Decisions are in `design.md`. The
deadline, the pool tag, the expiry claim and the lapse cause are
`renewable-compute-lease-deadlines`' tasks, not these.

## 1. Schema and migration

- [ ] 1.1 Add nullable `renew_by_utc` and `renewal_phase` to
  `kit/site/src/market_site/db.py`. Add a service-owned ordered migration in
  `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`
  leaving existing rows null; coordinate its order with
  `capacity-reservation-lifecycle-hardening`'s migrations on the same table. Existing
  active leases must not become awaiting activation during upgrade. Verify in the
  compute service's existing migration integration suite; a new test there needs
  maintainer approval.

Verification point: `make -C provisioning/compute/service test-integration`.

## 2. The activation transition

- [ ] 2.1 Extend `kit/site/src/market_site/ledger.py` with activation from `leased`, in
  phase `awaiting_activation` or null, to `active`, setting the due instant to the
  current agreed end without a caller-supplied time; `active` retries return the lease
  unchanged; `releasing`, terminal, failed-release and operator-owned states refuse
  without a write; a truncation before activation or between a lost acknowledgement
  and its retry is adopted, never extended. Admission accounting is untouched.
- [ ] 2.2 Extend `kit/site/tests/integration/test_ledger.py` — the public ledger API
  over a real embedded database — for: activation from each admissible phase, retry
  after truncation, the lost-acknowledgement retry, refusal from each non-admissible
  state, no resurrection after release, a legacy null-phase lease activated, and
  full-window admission before and after activation. Deterministic two-session
  controls, not sleeps.

Verification point: `make -C kit/site test`.

## 3. Typed activation and inspection

- [ ] 3.1 Extend the typed authority in `kit/site/src/market_site/authority.py`, the
  models in `http_models.py`, `router.py` and the client in
  `kit/site-client/src/market_site_client/client.py` with activation by reservation
  identity and lease inspection carrying `renewal_phase`, `renew_by_utc` and the active
  instant. Existing service authentication and exact response verification; request
  bodies carry no billing kind, funded-through time or deadline value.
- [ ] 3.2 Extend `provisioning/compute/contracts/src/compute_provisioning_contracts/contracts.py`,
  `provisioning/compute/client/src/compute_provisioning_client/client.py` and the
  compute service's lease controller and composition with the same, typed and
  offering-mode neutral, exposing null compatibility and the active instant.
- [ ] 3.3 Run `make -C kit/site-client test`, the compute contracts and client `make test`
  targets and `make -C provisioning/compute/service test-integration`; verify the
  contract delta's three scenarios, including refusal of a response signed by a
  principal other than the configured site authority. Record commands, results and
  any unrun checks.

Verification point: the kit and compute package suites above; `make test`.

## 4. Closeout

Documentation-only, after code review; any required code correction returns to
implementation. Follow `openspec/README.md#plan-closeout-requirements` in this order.

- [ ] 4.1 **Comment hygiene:** run `make check-comment-hygiene`; a required edit
  returns to implementation.
- [ ] 4.2 **Import placement:** confirm touched imports are module-level unless a
  verified cycle keeps one local.
- [ ] 4.3 **Documentation compliance:** classify D1–D2 against documentation
  ownership; promote nothing about deadlines.
- [ ] 4.4 **Narrative compression:** retain final behaviour, evidence and destinations.
- [ ] 4.5 **Roadmap currency:** update Goal 8's gap row for this change in
  `docs/development/ROADMAP.md`.
- [ ] 4.6 **Campaign index currency:** update this change's row and the dependency
  graph in `openspec/changes/README.md`; run `make check-change-index`; record the
  update in the promotion record.
- [ ] 4.7 **Packaging:** run `make check-packaging` and
  `make check-architecture-change CHANGE=activate-compute-leases-at-the-site`;
  resolve all failures.
- [ ] 4.8 **End-to-end pipeline:** record the run and that the existing VM, bare-metal
  and API-credit complete-deal scenarios under
  `e2e-tests/tests/e2e/roles/scenarios/` keep passing with null-phase leases; the
  activating-caller traces are `unify-compute-delivery-path`'s and are recorded here
  as not this change's.
- [ ] 4.9 **Promotion:** write D1 to `openspec/specs/site-capacity/architecture.md`
  and the capacity-reservation section of `docs/development/ARCHITECTURE.md`; archive
  synchronizes the two delta-covered `spec.md` files; complete the promotion record.
- [ ] 4.10 **Documentation citations:** run
  `make check-doc-citations CHANGE=activate-compute-leases-at-the-site`, then
  `openspec validate activate-compute-leases-at-the-site --strict`.
- [ ] 4.11 **Archival:** `openspec archive activate-compute-leases-at-the-site -y`,
  then link the campaign row to the archive.

## Design promotion record

No promotion yet.

| Accepted decision | Permanent location after implementation |
|---|---|
| D1 phase, transition, retry and refusal | `openspec/specs/site-capacity/spec.md`, `openspec/specs/site-capacity/architecture.md`; capacity reservation in `docs/development/ARCHITECTURE.md` |
| D2 typed activation and inspection | `openspec/specs/compute-provisioning-contract/spec.md` |
| Campaign status | Goal 8 in `docs/development/ROADMAP.md`; campaign row in `openspec/changes/README.md` |
