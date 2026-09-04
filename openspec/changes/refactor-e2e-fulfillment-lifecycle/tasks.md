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
- [ ] 1.12 Run the actual e2e scenarios against live docker-compose services to confirm runtime correctness -- **not done in this session** (no live services available in this environment). Verified by static analysis and compile-checking only.

## 2. Teardown-phase rewrite

**Finding (2026-07-29): already implemented, not needed as new work.**
`test_full_deal.py` and `test_full_deal_buyer_cli.py` stages 10a-11b already
use `fulfillment_id`, `check_leases()`, `run_fulfillment_convergence_cycle()`,
`drain()`, and the exact `teardown_dispatch_pending` → `tearing_down` →
`torn_down` → `released` state sequence `pools-7`'s design review proposed --
word-for-word identical between both files. `pools-7-storefront-fulfillment-cutover`
task 10.14's "deferred" status was stale documentation, not a reflection of
current code.

**The real gap was upstream, not here.** Every teardown stage's
`require_state(deal_state, ..., "reserved_resource_id")` precondition would
silently *skip* (not fail) those stages on every run, because
`reserved_resource_id` was never populated before Section 1's fix -- it was
sourced from a buyer-facing event/response that has been opaque (always
`None`) since before this change existed. This is consistent with `pools-7`'s
own complaint that "no E2E run exists for this PR head" -- these stages were
never silently broken so much as never actually executed at all.

- [x] 2.1 Re-verify `pools-7-storefront-fulfillment-cutover`'s Section 10 static analysis against current code. Result: current code already matches the proposed sequence; no rewrite needed.
- [x] 2.2 Confirm `test_full_deal.py` stages 10a-11b match the proposed sequence.
- [x] 2.3 Confirm `test_full_deal_buyer_cli.py`'s equivalent stages match (word-for-word identical to 2.2).
- [x] 2.4 Trace why `pools-7` believed this was still deferred: `reserved_resource_id`'s `require_state` precondition was unsatisfiable before Section 1's fix, so these stages silently skipped rather than ran and failed -- explaining why nobody observed them passing.
- [ ] 2.5 Update `pools-7-storefront-fulfillment-cutover` task 10.14 to reflect this is resolved, not deferred (pending an actual passing run -- see 1.12/2.6).
- [ ] 2.6 Run stages 10a-11b against live services (blocked on the same live-service constraint as task 1.12) to confirm they now execute and pass, not just that they're syntactically present and internally consistent.

## 3. Inter-service test split

- [x] 3.1 Resolve the three open implementation questions in `design.md`: e2e half is already covered by `test_full_deal.py`'s existing (Section-1-hardened) real reserve/commit/schedule/begin flow across two real services, so no new scenario file is needed; fast half uses `httpx.MockTransport` (both `RemoteCapacityClient` and `ComputeProvisioningClient` already declare a `transport` test seam for exactly this); retirement of the old tier happens atomically with confirming the mock-transport replacement passes (not staged -- the e2e-side coverage already existed and needed no gating).
- [x] 3.2 e2e-side coverage: none added, confirmed already sufficient (see 3.1).
- [x] 3.3 Added `core/storefront/tests/integration/test_capacity_and_fulfillment_client_opacity.py`: mock-transport test proving `RemoteCapacityClient`/`ComputeProvisioningClient` never send a placement field across reserve/commit/schedule/begin. Zero cross-package imports. Verified it fails when a placement field is deliberately reintroduced (sanity-checked by temporarily setting `resource_id="pinned-host"` on the commit call and confirming the test catches it), then confirmed it passes again with the fix reverted.
- [x] 3.4 Added `tests/integration` to `core/storefront`'s pytest `testpaths` (previously only `tests/unit` was discovered).
- [x] 3.5 Removed `domains/vms/storefront/tests/cross_service/` (both the test file and its now-dead PYTHONPATH-trick `conftest.py`) and the `test-vm-capacity-boundary` make target, including its `.PHONY` entry and its dependency in the aggregate `test` target.

## 4. Light review pass

- [x] 4.1 Read `test_multi_registry.py` fully; no fulfillment-lifecycle vocabulary (legacy or current) anywhere in the file, and it doesn't import `DealState` -- confirmed independent of everything Sections 1-3 touched. No changes needed.
- [x] 4.2 Read `test_buy_oneshot_buyer_cli.py` fully; no legacy vocabulary. It does import `DealState` and assigns `deal_state.reserved_resource_id` directly (`= BUY_RESOURCE_ID`), which remains a valid field after Sections 1-3's changes -- direct assignment, not dependent on how the *other* scenario files populate it. No changes needed.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 5.1 **Comment hygiene.** Run `make check-comment-hygiene`, then direct-read the comments and docstrings this change touches for the fuzzier provenance-narration rule the target cannot catch mechanically.
- [ ] 5.2 **Import placement.** Review every import this change adds or touches and move it to module level where safe; retain a local import only against an observed circular import or a documented lazy-load reason, verified against the real suite.
- [ ] 5.3 **Documentation compliance.** Re-check this change's accepted decisions against `openspec/README.md`'s placement rules. It carries no delta specs, so confirm every material decision has a permanent destination or an explicit temporary, superseded, or rejected classification.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations, moving durable rationale into `design.md` first.
- [ ] 5.5 **Roadmap currency.** This change sits under the lesser goal “End-to-end harness determinism”, which has no roadmap goal behind it, so it most likely owes `docs/development/ROADMAP.md` nothing. Confirm that and record the no-impact disposition explicitly rather than omitting the step.
- [ ] 5.6 **Campaign index currency.** Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md` to match its state at completion, or record the disposition here if its status and campaign placement are both unchanged.
- [ ] 5.7 **Promotion.** Complete the design-promotion record, mapping every accepted decision to its exact permanent heading, and verify no production source references `openspec/changes/refactor-e2e-fulfillment-lifecycle`.

## Design-promotion record

See `design.md`'s "Section 1 ... Design promotion record" table. Sections 2-4
have no promotion record yet -- nothing implemented.
