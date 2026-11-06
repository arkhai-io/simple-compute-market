## Why

The end-to-end pipeline (`.github/workflows/e2e.yml`) takes about twelve minutes,
and the VM lane alone sets that figure: the bare-metal and API-credit lanes finish in
under four. E2E run 42283244737 spent the VM lane's 717 seconds as follows:

| Phase | Time |
|---|---|
| Runner setup, wheels, dev-env and test images, service images | 2m21s |
| `compose up --wait` and the payments check | 35s |
| VM scenarios, 153 in series | 3m15s |
| VM IaC native Ansible gate | 5m21s |
| Logs, upload, teardown | 16s |

Two causes are not inherent to what the pipeline proves.

**The native Ansible gate sits on the VM lane's critical path without needing its
stack.** `make test-provisioning-iac-native` runs in the built provisioning image
with `--network none` and never reaches the compose stack, yet it runs after the
scenarios, in their job. Of its 321 seconds, 273 are the compute family's 19 native
tests, run in series by `unittest`: each `test_admission_installer` case drives a
real `ansible-playbook` that builds real virtual environments, taking 25–45 seconds.
They work in their own temporary directories and touch no shared path.

**Some scenarios wait on timers and durations, against `TESTING.md`.** Its
"Tests wait on events, never on durations" and "Pause the loop, then advance it
explicitly" sections, and the end-to-end stage discipline, allow a scenario to wait
only on a request it made. Five places in the pipeline's lanes do otherwise:

- `test_buy_oneshot_buyer_cli` and `test_listing_shapes` hold the storefront's loops
  but not provisioning's fulfillment convergence or lease watchdog. Their
  `market buy` reaches `ready` only when convergence's 30-second timer next fires:
  in the run above, every such buy completed on a timer tick, about 40 seconds of
  waiting in all. This is the trap `TESTING.md` records as "A loop with no pause is
  not paused".
- The bare-metal introduction scenario polls the `introduction-retention` dry run
  until the retention window has passed in real time, where the guidance asks a
  deadline the scenario is defined by "as a deadline of now".
- The bare-metal payment scenario, having advanced provisioning to `active`, polls
  the storefront's fulfillment status for up to 30 seconds.
- The VM introduction stages poll Mailpit for seller-side delivery, which runs off
  the request path.
- The API-credit buyer scenario polls through the sample app's 3-second verify
  cache after a top-up.

Each wait costs little today, but each new scenario that copies one adds its
own, and a timer-bound scenario's duration is set by the timer rather than by
the work it does.

## What Changes

- **The native Ansible gate becomes a lane of its own.** A new `e2e.yml` job builds
  the wheels and the provisioning image and runs `make test-provisioning-iac-native`;
  the VM lane no longer runs it. The gate keeps its stance: a skipped test or an empty
  run fails it.
- **The compute family's native tests run concurrently** within the gate, so the new
  lane does not become the pipeline's longest; the VM IaC's native tests may follow
  the same runner.
- **Every buy scenario holds what it depends on.** `test_buy_oneshot_buyer_cli` and
  `test_listing_shapes` take the fulfillment-convergence and lease-watchdog holds, run
  `market buy` in the background, and step convergence with `advance-cycle` once the
  job is submitted, as `test_full_deal_buyer_cli` already does.
- **The `introduction-retention` dry run and step accept an as-of time** on the
  storefront admin API, so the bare-metal introduction scenario asks whether an
  introduction is past its window at a time it names, rather than waiting for the
  window to pass. This is an end-to-end test control on an admin route; production
  callers omit it and the sweep reads the clock as today.
- **The remaining waits are replaced by a step or a seam.** The bare-metal payment
  scenario's storefront status poll, the VM introduction's Mailpit poll, and the
  API-credit scenario's verify-cache poll each get the step or seam the design finds
  for it.
- **A source check keeps holds complete.** `e2e-tests/tests/unit/test_scenario_holds.py`
  is extended so a scenario module that drives a fulfillment to delivery must hold
  fulfillment convergence and the lease watchdog.
- State: **proposed; design not started.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: "Scenarios hold shared services for the whole module" gains
  the rule that a module driving a fulfillment holds convergence and the lease
  watchdog, enforced from source; "Each domain runs in its own lane" or a sibling
  requirement records that the native Ansible gate runs as its own pipeline job.
- `contact-exchange-settlement`: the retention sweep's preview and step accept an
  as-of time.
- Others as design finds them: the API-credit and introduction-delivery
  specifications if their seams change behaviour.

Until design writes these deltas, `.openspec.yaml` sets `skip_specs`; design clears it.

## Non-Goals

- Do not cache image layers across runs, build images once for every lane, or shard a
  lane's scenarios across several stacks. Those are the next step for scaling the
  scenario count; several stacks on one host is `isolate-end-to-end-lane-stacks`.
- Do not run a lane's scenarios in parallel within one stack: the holds are global to
  a service, and stages within a module are ordered.
- Do not add a source check rejecting `sleep` in scenario code.
- Do not change the real-host helpers (`real_provisioning`, `ssh_access`,
  `bare_metal_access`, the real compute deal driver, working-data qualification),
  which poll real hardware outside any pipeline lane.
- Do not change the refund retry in payment-compensation cleanup, which runs only
  after a scenario has failed and already takes an injected clock and sleep.
- Do not change the provisioning service's convergence interval.

## Open questions

- **The API-credit verify cache.** Whether the lane's sample app runs with no cache,
  a top-up invalidates the cache, or another seam lets the scenario observe the
  top-up; and where the cache's own behaviour is proven if the lane bypasses it.
- **The bare-metal payment status poll.** Which storefront path makes an `active`
  fulfillment visible: if it reads through to provisioning, the poll is a single
  assertion; if a loop carries it, the scenario steps that loop.
- **The VM introduction's Mailpit poll.** What dispatches seller-side delivery, and
  which step or completion signal the scenario waits on instead.
- **The as-of control's shape.** Its name, its validation (whether a time before the
  storefront's clock is refused), and whether it applies to the dry run and the step
  alike.
- **Concurrency in the native gate.** One process per test or per module, the worker
  count on a hosted runner, and how a failure's output stays attributable.

## Dependencies and Related Changes

- `isolate-end-to-end-lane-stacks` makes several lane stacks able to share a host,
  which the deferred sharding step would build on. Neither waits for the other.
- `extract-e2e-project` (deferred) would move the harness this change edits.

## Impact

`.github/workflows/e2e.yml` (a gate job; the VM job's gate step removed); the root
`Makefile` if the gate lane needs a build target of its own;
`provisioning/compute/iac/scripts/native_ansible_gate.sh` and possibly
`domains/vms/provisioning/iac/scripts/native_ansible_gate.sh`, with the VM IaC
structure test that reads the latter; `scripts/fetch-e2e-logs.py` if the new job
uploads logs; the scenario modules named above and their helpers; the storefront
admin route and kit runner for `introduction-retention`, and its client; the
API-credit sample app or middleware configuration; `TESTING.md`'s native-gate and
lane sections and its hold rules; and the source check in
`e2e-tests/tests/unit/test_scenario_holds.py`. Runtime behaviour changes only where
an admin route gains the as-of control.
