## Why

`docs/development/TESTING.md` requires every loop an end-to-end scenario advances to
offer a pause, and an explicit single step that works while the loops are held. Only
one of the three storefronts can do that today, and it does it with a domain-local
copy:

- **VM** holds its timer loops through `domains/vms/storefront/src/market_storefront/lifecycle.py`,
  420 lines of module-global registry, gate, acknowledgement, bounded quiescence, and
  loop-state reporting, with pause, resume, run-cycle, and dry-run routes in its admin
  controller.
- **Bare metal** starts two loops nothing can hold — the negotiation watchdog and the
  settlement-servicing worker — and steps only publication, which has no timer.
- **API credits** starts three loops nothing can hold — the negotiation watchdog, the
  settlement-servicing worker, and the quota capacity-event poller — and has no
  lifecycle controls at all.

Two active changes now need bare-metal controls before they can be proven.
`contact-payload-retention` adds a retention sweep loop whose end-to-end scenario
steps it, and `bare-metal-mock-provisioned-deal` decided that its deal scenario holds
every bare-metal loop and steps each transition. Building a second domain-local copy
for bare metal would put a duplicate in place for `kit-owned-storefront-shell` to
remove later, against the rule that an extracted concern leaves no domain-local
implementation. That shell change owns extracting the timer-loop lifecycle among a
much larger scope — the route set, executable assembly, and health — and is in its
design phase. The loop lifecycle is separable from the rest of that scope, so it is
carved out here and delivered first.

Doing so exposes a defect in the shared loop runners. The kit negotiation watchdog
and the settlement-runtime servicing worker both read their pause predicate, then
sleep their full interval, then do their work without reading it again. A pause
requested during the sleep is reported honestly as `pausing`, but the loop still runs
one complete cycle once it wakes, and with bare metal's 60-second watchdog interval
the pause cannot quiesce inside the 5-second bound the pause route waits.

VM's lifecycle module also cites a `storefront-publication` requirement for its
loop-state semantics that does not exist in that specification. The semantics are
real and load-bearing; they have no normative home.

## What Changes

- Add one instance-scoped loop controller to `kit/storefront`: registration of each
  timer-driven loop by name together with the step that runs its cycle and an
  optional read-only preview; one pause and one resume holding every registered loop
  at a cycle boundary; bounded quiescence; per-loop reported state established by the
  loop itself; gated names declared without a task handle for fan-out loops; and
  summaries of which loops are starting and which have ended. The semantics are VM's,
  adopted unchanged.
- Add a framework-free lifecycle route service to `kit/storefront` — pause, resume,
  run-cycle, and dry-run by registered loop name — which each storefront binds into
  its own router behind its own administrator authentication. Wire paths, response
  shapes, and the canonical `StorefrontClient` methods are unchanged.
- Reorder the shared loop runners — the kit negotiation watchdog and the
  settlement-runtime servicing worker — to read the gate on entry and immediately
  before their work, and to wait between cycles through an injected wait that
  returns as soon as a pause is requested.
- Compose all three storefronts onto the controller in this change:
  - **VM** binds its `lifecycle` module to one controller instance, preserving every
    public name its call sites import, and serves its routes through the route
    service;
  - **bare metal** registers its negotiation watchdog and settlement-servicing worker,
    serves pause, resume, and a step for each beside its existing publication step;
  - **API credits** registers its negotiation watchdog, settlement-servicing worker,
    and per-site capacity-event pollers, and serves the same routes, authenticated
    under the operation names the canonical client signs.
- Move VM's aggregate capacity-event poller loop into `kit/capacity-publication` beside
  `poll_events`, so VM and API credits share one implementation.
- Give the negotiation watchdog a step in every storefront. VM holds it today but
  offers no step for it.
- State the controller's contract normatively in `market-composition`, including the
  loop-state semantics VM's module cites without a home.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: storefront timer loops are registered with, held by, and
  stepped through one kit-owned controller per storefront process; a loop's reported
  state is established by the loop.

## Non-Goals

- Do not change the trading pause (`/api/v1/admin/pause`). Holding loops and refusing
  new negotiations remain separate controls.
- Do not persist the loop pause across a restart. VM's is process-local, and a
  restarted storefront resumes its loops; see `design.md`.
- Do not change any loop's timing, configuration, or the work its cycle performs.
- Do not extract the storefront route set, executable assembly, or health service.
  Those remain `kit-owned-storefront-shell`'s.
- Do not add loops. A change that adds one registers it with the controller.

## Impact

- `kit/storefront`: the controller and the route service.
- `kit/storefront` and `kit/settlement-runtime`: the negotiation watchdog and
  servicing worker loop runners.
- `domains/vms/storefront`: `lifecycle.py`, the loop-pause flag in `server.py`, the
  lifecycle routes in the admin controller, and the lifecycle test suites whose
  private-state assertions move to kit.
- `domains/bare_metal/storefront`: startup in `server.py` and the lifecycle routes in
  `api.py`.
- `kit/capacity-publication`: the aggregate capacity-event poller loop.
- `domains/apicredits/storefront`: `startup.py`, the capacity-event poller, new
  lifecycle routes, and their administrator authentication.
- `docs/development/TESTING.md`: the loop table.

## Dependencies and Related Changes

- **No blocking dependency.** `kit/storefront` exists and every storefront already
  composes it.
- **Carved from `kit-owned-storefront-shell`**, which keeps the route set, executable
  assembly, and health, and composes this controller when it extracts the shell.
- **Implements `bare-metal-mock-provisioned-deal`'s decision** that the bare-metal
  pause holds every loop and every transition is stepped. That change keeps the
  scenario that relies on it.
- **Prerequisite of `contact-payload-retention`**, whose retention sweep registers
  with the controller and whose end-to-end scenario steps it.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the kit storefront's place in the kit
      layers gains the loop controller beside the shell seams it already owns.
- [x] Existing subsystem specification — `openspec/specs/market-composition/spec.md`.
- [x] `docs/development/TESTING.md` — the loop table names the controller and gains
      bare-metal and API-credit rows.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- One kit-owned loop controller per storefront process; every timer loop registers
  with it, paired with its step — `openspec/specs/market-composition/spec.md`.
- A loop's reported state is established by the loop, and a loop waits, gates, then
  works — `openspec/specs/market-composition/spec.md`.
- The pause-and-step convention is composed rather than reimplemented —
  `docs/development/TESTING.md`'s loop table and `docs/development/ARCHITECTURE.md`.
