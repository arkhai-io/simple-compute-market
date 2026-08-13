## Context

See `proposal.md` for the "Why" and section breakdown. This document records
the design reasoning behind Section 1's implementation and the open questions
for Sections 2-4.

## Section 1: provisioning-phase `fulfillment_id` fix (implemented, 2026-07-29)

### Problem, confirmed by reading the actual code

`test_full_deal.py`'s stage 08b captured `status_resp.provisioning_job_id`
from the settle-status response and used it two ways: (a) as an argument to
`provisioning_client.get_job(prov_job_id)`, asserting a queued/running/succeeded
status, and (b) stored on `DealState` for stage 09a's
`provisioning_test_client.wait_for_job(deal_state.provisioning_job_id, ...)`.

`core_storefront.models.settle_models.SettleStatusResponse`'s own docstring
states `provisioning_job_id` is "the legacy ephemeral executor-job identity
and is always `None` for a fulfillment that went through the durable path
instead." Confirmed this is not merely stale vocabulary but an actually-empty
field for every fulfillment created through the current
`schedule_resource`/`begin_fulfillment` path -- meaning stage 08b's `assert
prov_job_id` and everything downstream of it would fail against current
`dev`, not just read oddly.

This is a different bug from `pools-7` task 10.14's already-documented
teardown-phase staleness (stages 10-11): it's upstream, in the *provisioning*
phase, and wasn't previously tracked anywhere -- POOLS-7's own static
analysis of this test file was scoped to teardown only.

### Resolution: `resume_rule` + `drain` + `run_fulfillment_convergence_cycle`

The legacy path's `wait_for_job(job_id)` needs a raw Ansible job id, which the
storefront no longer surfaces to the buyer-facing settle-status response (by
design -- `fulfillment_id` is the durable path's identity; the raw job id is
now internal `provider_metadata` on the `SettlementRecord`). Two considerations
shaped the fix:

1. **`resume_rule` never needed the job id in the first place.** It operates
   on a caller-chosen `rule_id` (`PROV_RULE_ID`, defined by the test itself),
   not the job's id. This call was already correct and needed no change.
2. **Waiting for the specific job's completion doesn't require its id either,
   given this scenario's shape.** `provisioning_test_client.drain(timeout=...)`
   ("long-poll until all jobs are terminal") already existed for teardown use.
   In a single-deal, single-outstanding-job e2e scenario, draining every
   outstanding job is equivalent to waiting for the one job under test --
   there is nothing else running concurrently to conflate it with. This
   avoids inventing a new "resolve job id from fulfillment id" test-only
   endpoint, which would have been the alternative (rejected: it would add
   provisioning-service surface area solely to route around a boundary the
   architecture is deliberately drawing).
3. **Job completion and fulfillment convergence are two separate facts, and
   only one of them is directly observed by draining.** Per
   `openspec/specs/fulfillment/spec.md`'s fulfillment convergence worker
   requirement, a `SettlementRecord` only advances from `dispatching` to
   `active` once the convergence watchdog observes the provider's terminal
   status -- job completion alone doesn't imply that transition happened.
   `provisioning_client.run_fulfillment_convergence_cycle()` (already exists,
   already used for teardown determinism per `pools-7` design.md's Section 10
   review) triggers exactly that convergence step deterministically, avoiding
   a sleep against the real background interval.

The resulting sequence (`resume_rule` → `drain` → `run_fulfillment_convergence_cycle`
→ `get_fulfillment_status` asserting `active`) requires zero new
`compute-provisioning-service`/`kit/fulfillment` code -- every method used
already existed as test or production client surface. This was verified by
grepping the sync client (`vm_provisioning_operator.client`) before designing
the fix, not assumed.

### A second, independent problem found in the same code path

Stage 08b also asserted `deal_state.reserved_resource_id ==
E2E_RESOURCE_ID`, sourced from `event.data.get("resource_id")` on the
`provision`/`job_submitted` stage event. This event still carries
`resource_id` (confirmed: `vm_fulfillment_service.py`'s `_record_fulfillment_id`
stage_event call was only stripped of `vm_host`, not `resource_id`, during
this session's earlier `vm_host`-stripping work) -- so this specific
assertion was not broken by anything in this session. But tracing where
`reserved_resource_id` was *supposed* to have come from before that (the
`_reserve_capacity_for_obligation` call's own reservation response) revealed
it's always `None` there -- `resource_id` has been stripped from the ordinary
buyer-facing `/reservations` response since before this change, and before
the `provisioning_job_id` issue was even found. Stage 08b's specific
`event.data.get("resource_id")`-sourced check happened to still work only
because it read a *different*, server-side-only telemetry channel (the stage
event), not the buyer-facing HTTP response -- an accident of two independent
paths, not a designed guarantee.

**Resolved:** moved resource-identity verification entirely to stage 09c,
which already had a robust source for it -- the admin-only `DealLease` view
(`get_capacity_reservation`, confirmed in this session's earlier audit to sit
behind the same admin-gated router as everything else on this API, and
therefore a legitimate, separate introspection channel from the ordinary
opaque-reservation guarantee, not a loophole in it). Stage 08b no longer
asserts on resource identity at all; it only confirms dispatch happened.

### Design promotion record

| Material decision | Permanent location |
|---|---|
| `fulfillment_id`, not `provisioning_job_id`, is captured at settlement and reused through teardown | No `openspec/specs` entry -- this is test-suite maintenance tracking already-shipped `SettleStatusResponse` behavior, not new production behavior |
| `drain()` substitutes for `wait_for_job(<id>)` in single-job e2e scenarios; job completion and fulfillment convergence are separately-driven facts | In-code docstrings on the affected test stages (`AGENTS.md`'s "non-obvious invariants" guidance) |
| Resource-identity verification belongs at stage 09c (admin introspection), never inferred from the buyer-facing path | In-code docstrings on stages 08b/09c |

## Section 2: teardown-phase rewrite (finding: already implemented, 2026-07-29)

### Expected vs. actual

Expected, per `proposal.md`'s original scoping: implement
`pools-7-storefront-fulfillment-cutover`'s already-designed five-stage
teardown sequence, since its task 10.14 states this work is deferred.

Actual, on inspection: `test_full_deal.py` stages 10a-11b already implement
that exact sequence. Verified line by line against `pools-7`'s design review:

| Proposed stage (pools-7 design.md) | Current code |
|---|---|
| Terminate lease | 10a: `admin_interrupt_deal` |
| Lease `releasing`, fulfillment `teardown_dispatch_pending`, capacity held | 10b: `check_leases()`, asserts both states, `resource_consumed` |
| One convergence step → `tearing_down`, capacity still held | 11a: `run_fulfillment_convergence_cycle()`, asserts `tearing_down` |
| Provider completes, converge to `torn_down` | 11b: `resume_rule` → `drain()` → `run_fulfillment_convergence_cycle()`, asserts `torn_down` |
| Lease cycle → `released`, capacity available, storefront observes | 11b (same stage): `check_leases()` asserts `released`, waits for the `capacity_released` stage event, asserts capacity freed |

`test_full_deal_buyer_cli.py`'s equivalent stages are word-for-word identical
to `test_full_deal.py`'s. Both already use `drain()` rather than a raw
job-id-based wait for the teardown-side Ansible job -- the same technique
Section 1 independently arrived at for the provisioning side, applied here
first (or concurrently) by whoever wrote this code.

### Why this wasn't previously visible as "done"

Every stage from 10a onward gates on `require_state(deal_state, ...,
"reserved_resource_id")`. `require_state` skips (doesn't fail) a test when a
precondition field is `None`. Before Section 1's fix, `reserved_resource_id`
was populated at the old stage 08b from `event.data.get("resource_id")` on a
stage event -- which itself worked, since that event still carries
`resource_id` -- but chained through `deal_state.reserved_resource_id ==
E2E_RESOURCE_ID`'s assertion, which depended on the same variable also being
compared against the (always-`None`, opacity-stripped) reservation response
value elsewhere. Tracing the actual failure mode precisely: the specific
break was that stage 08b required `provisioning_job_id` (`assert
prov_job_id`, unconditional, not a skip) to be truthy before
`reserved_resource_id` was ever reached -- and `provisioning_job_id` is
permanently `None` on the durable path. So stage 08b itself would **fail**
outright (not skip) on the durable path, and every stage after it
(including all of 09a-11b) would never run at all, teardown included.

This means `pools-7`'s "no E2E run exists for this PR head" observation and
this change's Section 1 finding are the same root cause, not two coincidental
gaps: fixing the stage 08b failure is what makes the already-written teardown
stages reachable for the first time, not just newly correct.

### Remaining work

Not a rewrite. Two things:

1. Correct `pools-7-storefront-fulfillment-cutover` task 10.14's status --
   it currently reads as deferred/not-done; the code says otherwise.
2. Get an actual passing run against live services (blocked on the same
   constraint noted in Section 1 -- this sandbox has no live
   docker-compose stack). Static/structural verification is complete; runtime
   confirmation is not.

### Section 2 design-promotion record

| Material decision | Permanent location |
|---|---|
| No rewrite needed; existing teardown-stage implementation already matches the proposed design | This document -- change history, not new production behavior |
| Stage 08b's `provisioning_job_id` failure was masking every downstream stage (09a-11b), not just the provisioning-phase assertions | Recorded here and cross-referenced from `pools-7-storefront-fulfillment-cutover` task 10.14's corrected status |

## Section 3: inter-service test split (implemented, 2026-07-29)

### Resolved

1. **E2E half: no new scenario file.** `test_full_deal.py` already exercises
   the real `reserve` → `commit` → `schedule_resource` → `begin_fulfillment`
   path against two genuinely running services, and Section 1 of this same
   change just hardened its assertions around exactly this boundary
   (dropping the broken buyer-facing resource-id check, moving verification
   to admin introspection at stage 09c). A second, dedicated scenario file
   proving the same thing would duplicate coverage without adding anything
   the existing flow doesn't already exercise.
2. **Fast half: `httpx.MockTransport`.** Confirmed by reading both client
   classes before deciding, not assumed: `RemoteCapacityClient`
   (`core_storefront.capacity_remote`) and `ComputeProvisioningClient`
   (`compute_provisioning.client`) both already declare a
   `transport: httpx.AsyncBaseTransport | None` constructor parameter,
   `RemoteCapacityClient`'s docstring literally labeling it "test seam
   (httpx.MockTransport / ASGI)". Driving both against one shared
   `MockTransport` handler, built from the same typed
   `compute_provisioning.contracts` models a real server validates against,
   needed no new test infrastructure.
3. **Retirement: atomic, not staged.** The staged-retirement concern
   (coverage gap if either replacement is incomplete) doesn't apply once (1)
   resolved to "no new e2e coverage needed" -- there's no new e2e piece to
   wait on. Removed `domains/vms/storefront/tests/cross_service/` and the
   `test-vm-capacity-boundary` make target in the same pass as adding the
   mock-transport test.

### Implementation notes

`core/storefront/tests/integration/` didn't exist before this change --
`core/storefront/pyproject.toml`'s `testpaths` only listed `tests/unit`.
Added `tests/integration` alongside it, matching the pattern already used by
`provisioning/compute/service` (unit + integration both discovered).

The new test's proof is request-side, not response-side: a
`_RecordingHandler` captures every `httpx.Request` the mock transport
answers, and the test asserts none of their JSON bodies carry a non-null
`resource_id` -- this is what actually matters (the client never *sends*
placement data), not merely that it tolerates opaque responses. Verified
this catches a real regression by temporarily reintroducing
`resource_id="pinned-host"` on the `commit()` call and confirming the
assertion fails with a clear message identifying which endpoint leaked it,
then reverting.

### Section 3 design-promotion record

| Material decision | Permanent location |
|---|---|
| `RemoteCapacityClient`/`ComputeProvisioningClient`'s existing `transport` test seam is the intended mechanism for boundary-opacity proofs, not a special execution environment | No `openspec/specs` entry -- this is test-suite architecture, not production behavior. Documented in the new test file's own module docstring for discoverability. |
| The genuine cross-service proof lives wherever it already existed (`test_full_deal.py`), not duplicated into a new scenario | Same as above |
| `core/storefront` gains an `integration` test tier, matching the pattern other packages already use | `core/storefront/pyproject.toml` (mechanical config change, no spec text needed) |

## Section 4: light review pass (not started)

No design questions anticipated -- confirm `test_multi_registry.py` and
`test_buy_oneshot_buyer_cli.py` don't reference stale fulfillment-lifecycle
vocabulary (Section 1's inventory found none, but that was a grep-based
inventory, not a full read).
