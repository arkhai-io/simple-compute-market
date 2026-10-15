## 1. Provisioning-phase `fulfillment_id` fix

- [x] 1.1 Inventory all VM e2e scenario files for legacy (`allocation_id`/`provisioning_job_id`/`vm_remove_job_id`/`SyncProvisioningClient`) vs. current (`capacity_reservation_id`/`fulfillment_id`/`schedule_resource`/`begin_fulfillment`/`ComputeProvisioningClient`) vocabulary.
- [x] 1.2 Confirm `provisioning_job_id` is genuinely, permanently empty on the durable path (not just stale naming) by reading `SettleStatusResponse`'s own docstring and the Section 9 promotion record that produced it.
- [x] 1.3 Confirm `run_fulfillment_convergence_cycle`, `get_fulfillment_status`, and `drain` already exist on the relevant clients before designing around them.
- [x] 1.4 Rewrite `test_full_deal.py` stage 08b: capture `fulfillment_id`, confirm `dispatching` via `get_fulfillment_status`, drop the resource-id assertion (moved to 09c).
- [x] 1.5 Rewrite `test_full_deal.py` stage 09a: `resume_rule` → `drain` → `run_fulfillment_convergence_cycle` → assert `active`.
- [x] 1.6 Rewrite `test_full_deal.py` stage 09c: require `fulfillment_id` instead of `provisioning_job_id`; source `reserved_resource_id` from the admin `DealLease` view; fix the `create_job_id` cross-check (assert presence, not equality against a value we no longer capture).
- [x] 1.7 Mirror 1.4-1.6 in `test_full_deal_buyer_cli.py`.
- [x] 1.8 Apply the equivalent fix to `test_non_erc20_settlement.py`'s single settlement-flow function.
- [x] 1.9 Update `DealState` (`conftest.py`): remove the stale `provisioning_job_id` field; repurpose `fulfillment_id` (already existed, previously teardown-only) as the identity captured at settlement; repurpose `reserved_resource_id` as admin-introspection-sourced at 09c.
- [x] 1.10 Update stale module- and function-level docstrings referencing the old `provisioning_job_id` flow.
- [x] 1.11 `py_compile` all four touched files; grep for orphaned references (`prov_job_id`, `.get_job(`) across all three scenario files.
- [x] 1.12 Run the actual e2e scenarios against live docker-compose services to confirm runtime correctness. Not run in the implementing session (no live services there; verified by static analysis and compile-checking only). Done at closeout: E2E run 38741626285 (2026-10-15, `dev` at `a82a5b2`), VM lane 134 passed, nothing failed or skipped, 118 deselected: `test_full_deal.py` 31 of 31, `test_full_deal_buyer_cli.py` 27 of 27, `test_non_erc20_settlement.py` 2 of 2 (`native-token`, `erc1155`). See 5.8.

## 2. Teardown-phase rewrite

**Finding (2026-07-29): already implemented.** Stages 10a–11b of both
full-deal scenarios already run the teardown sequence `pools-7` proposed;
what kept them from running was stage 08b's `provisioning_job_id` assertion
upstream, which Section 1 fixed. Full trace in `design.md`, "Section 2".

- [x] 2.1 Re-verify `pools-7-storefront-fulfillment-cutover`'s Section 10 static analysis against current code. Result: current code already matches the proposed sequence; no rewrite needed.
- [x] 2.2 Confirm `test_full_deal.py` stages 10a-11b match the proposed sequence.
- [x] 2.3 Confirm `test_full_deal_buyer_cli.py`'s equivalent stages match (word-for-word identical to 2.2).
- [x] 2.4 Trace why `pools-7` believed this was still deferred: stage 08b failed outright on `provisioning_job_id`, so no later stage ran. Evidence: run 37298149909 (2026-10-05, from `bare-metal-mock-provisioned-deal`) passed stages 08a–11b of both full-deal scenarios, and run 38741626285 (2026-10-15) passed them again with `test_non_erc20_settlement.py`, which the earlier lane did not run. The lease is read and back-dated through the family and site clients (see `design.md`).
- [x] 2.5 Update `pools-7-storefront-fulfillment-cutover` task 10.14 to reflect this is resolved, not deferred. Done 2026-10-15: that task carries a dated resolution note naming run 38741626285.
- [x] 2.6 Run stages 10a-11b against live services to confirm they now execute and pass. Done: run 38741626285 passed 10a, 10b, 11a, and 11b in both `test_full_deal.py` and `test_full_deal_buyer_cli.py` (see 5.8), as run 37298149909 had on 2026-10-05.

## 3. Inter-service test split

- [x] 3.1 Resolve the three open implementation questions in `design.md`: e2e half is already covered by `test_full_deal.py`'s existing (Section-1-hardened) real reserve/commit/schedule/begin flow across two real services, so no new scenario file is needed; fast half uses `httpx.MockTransport` (both `RemoteCapacityClient` and `ComputeProvisioningClient` already declare a `transport` test seam for exactly this); retirement of the old tier happens atomically with confirming the mock-transport replacement passes (not staged -- the e2e-side coverage already existed and needed no gating).
- [x] 3.2 e2e-side coverage: none added, confirmed already sufficient (see 3.1).
- [x] 3.3 Added `core/storefront/tests/integration/test_capacity_and_fulfillment_client_opacity.py`: mock-transport test proving `RemoteCapacityClient`/`ComputeProvisioningClient` never send a placement field across reserve/commit/schedule/begin. Zero cross-package imports. Verified it fails when a placement field is deliberately reintroduced (sanity-checked by temporarily setting `resource_id="pinned-host"` on the commit call and confirming the test catches it), then confirmed it passes again with the fix reverted. Correction (closeout, 2026-10-15): that file no longer exists; the storefront-side `RemoteCapacityClient` was retired by later changes, and the proof now lives as two unit tests beside the clients it covers, `kit/site-client/tests/unit/test_opacity.py` and `provisioning/compute/client/tests/unit/test_fulfillment_client_opacity.py`. See `design.md`, "Closeout".
- [x] 3.4 Added `tests/integration` to `core/storefront`'s pytest `testpaths` (previously only `tests/unit` was discovered). Still in place, now holding other integration tests.
- [x] 3.5 Removed `domains/vms/storefront/tests/cross_service/` (both the test file and its now-dead PYTHONPATH-trick `conftest.py`) and the `test-vm-capacity-boundary` make target, including its `.PHONY` entry and its dependency in the aggregate `test` target.

## 4. Light review pass

- [x] 4.1 Read `test_multi_registry.py` fully; no fulfillment-lifecycle vocabulary (legacy or current) anywhere in the file, and it doesn't import `DealState` -- confirmed independent of everything Sections 1-3 touched. No changes needed.
- [x] 4.2 Read `test_buy_oneshot_buyer_cli.py` fully; no legacy vocabulary. It does import `DealState` and assigns `deal_state.reserved_resource_id` directly (`= BUY_RESOURCE_ID`), which remains a valid field after Sections 1-3's changes -- direct assignment, not dependent on how the *other* scenario files populate it. No changes needed.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [x] 5.1 **Comment hygiene — confirm.** `make check-comment-hygiene`: OK on both scans. Read directly: the 08b/09a/09c comments and docstrings in `test_full_deal_buyer_cli.py` and `test_non_erc20_settlement.py`, the shared stages in `helpers/compute_deal_stages.py`, and the module docstrings of the two opacity tests. None names the review or migration that introduced it. One imprecision, not a hygiene violation: two comments point at `test_full_deal.py`'s stage 09a for rationale that now lives in the shared stage's docstring, reached from there by inheritance. Recorded in `design.md`, "Found at closeout", for a later code edit.
- [x] 5.2 **Import placement — confirm.** The stages this change rewrote add no local import; the two local imports in `test_full_deal_buyer_cli.py` sit in stages 03a and 04a, which this change did not touch, and `conftest.py`'s fixture-local imports predate it. One in a file this change wrote: `test_fulfillment_client_opacity.py` imports `json` inside its request loop although the module imports it at top level — redundant, with no circular-import or lazy-load reason. Deleting the line is a code edit closeout does not make; recorded in `design.md`, "Found at closeout".
- [x] 5.3 **Documentation compliance.** Every accepted decision is classified in `design.md`'s closeout design-promotion record: permanent ones already stated by `ARCHITECTURE.md#identifiers`, `TESTING.md`, the fulfillment, site-capacity, and test-compatibility specs, and the stages' own docstrings; change history stays here. Checked against the code: the shared stages, the two opacity tests, and `core/storefront/pyproject.toml` match what the record cites. No production source references `openspec/changes/refactor-e2e-fulfillment-lifecycle` (`grep` over `.py`, `.toml`, `.yml`, `.yaml`, `Makefile`: none).
- [x] 5.4 **Narrative compression.** Section 2's preamble and 2.4's evidence compressed to the finding, the runs, and the pointer into `design.md`, which already held the full trace; 3.3 and 3.4 gained one-line corrections for where the code lives now, with the detail in `design.md`, "Where the implementation lives now". No completed task was deleted or rewritten.
- [x] 5.5 **Roadmap currency.** No goal affected: `ROADMAP.md` describes no harness assertion, and the lesser goal this change sits under has no roadmap goal behind it. No edit; disposition recorded in `design.md`, "Closeout dispositions".
- [x] 5.6 **Campaign index currency.** Row set to `in closeout` with the run as its note; the lesser goal has no dependency graph. `add-deterministic-regression-contract`'s `Depends on` entry is left for archive cleanup. `make check-change-index`: OK.
- [x] 5.7 **Packaging.** `make check-packaging`: OK, every check (lock-derived installs, current locks, Python version selection, one package per distribution, layers, scope, dependencies, kinds). `make check-architecture-change CHANGE=refactor-e2e-fulfillment-lifecycle`: owns no architecture row. `make check-agent-skills` not owed: the change touches no `.agents/`, `.claude/`, or `.codex/` file.
- [x] 5.8 **End-to-end pipeline.** E2E run 38741626285, dispatched with `make run-e2e` on `dev` at `a82a5b2` on 2026-10-15: success on `e2e-vm`, `e2e-bare-metal`, and `e2e-apicredits`. VM lane: 134 passed, 118 deselected, nothing failed or skipped. Scenarios exercising this change: `test_full_deal.py` (31 stages) and `test_full_deal_buyer_cli.py` (27 stages), including 08b, 09a, 09c, 10a, 10b, 11a, and 11b in each; `test_non_erc20_settlement.py`, both cases. The run names the commit this closeout starts from, which carries the change's code unchanged. Artifacts could not be downloaded from the closeout environment; the job log was read through the GitHub API instead (`design.md`, "End-to-end evidence").
- [x] 5.9 **Promotion.** No spec deltas and no permanent document owed: each destination already states the decision or is an in-code docstring. The design-promotion record in `design.md`, "Closeout", maps every accepted decision to its exact heading or file, and the proposal's "Permanent documentation impact" records the same disposition with the knowledge promoted.
- [x] 5.10 **Documentation citations.** `make check-doc-citations CHANGE=refactor-e2e-fulfillment-lifecycle` after promotion: OK, every cited path resolves and none is a tombstone. `openspec validate --strict` not run on the change: it has no spec deltas, which the validator rejects.
- [x] 5.11 **Archival.** `openspec archive refactor-e2e-fulfillment-lifecycle -y --skip-specs` (1.14.0), after every other part; the index row points at the archived directory; `openspec validate --specs --strict` and `make check-change-index` pass.

## Design-promotion record

The complete record is `design.md`'s "Closeout" section, "Design-promotion
record": every accepted decision from Sections 1–3, its classification, and
its exact permanent heading or file, plus the roadmap and index dispositions.
Section 4 made no decision.
