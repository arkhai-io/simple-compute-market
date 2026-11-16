# Design: drive-the-storefront-clock-in-lanes

## Context

One of Goal 8's three MVP changes: this one and `serve-running-rate-deals` in
parallel, then `switch-on-hosted-per-period-vm`. Its aim is fully deterministic
end-to-end verification of rate deals: a lane proves a deal's time-defined
transitions — funds running out, a notice taking effect, a term ending, a hold
paying out — by moving time, never by waiting on wall time, pausing a watchdog and
back-dating a record. The funds-exhausted rows of `serve-running-rate-deals` are its
first users.

The change keeps its name, though its scope is no longer the storefronts' clock
alone: lane time spans every party in a lane (D1, D9).

What exists:

- Only the lane doubles have a movable clock: wall time plus an offset, moved by
  `POST /test/clock/advance` and reset by `POST /test/clock/reset`
  (`tools/lane-double-controls/src/lane_double_controls/clock.py`, `routes.py`), and
  the harness advances both and resets them at each module's end
  (`e2e-tests/tests/e2e/roles/helpers/lane_doubles.py`, `lane_double_clock`).
- Every other party reads wall time directly: about 221 reads across 99 production
  files in core, kit, domains and provisioning, buyer included, and 58 SQL time
  defaults across 15 files (`server_default=func.now()`, `onupdate=func.now()`,
  `DEFAULT CURRENT_TIMESTAMP`), such as `kit/site/src/market_site/db.py` and
  `migrations.py`.
- Moving one party's time alone does not drive a deal. With only the doubles
  advanced, a stop at an advanced instant is in every other party's future: the
  storefront journals a truncation to it
  (`kit/deal-servicing/src/market_deal_servicing/journal.py`, `schedule_physical`)
  and the site ends the lease only when its own wall clock reaches it
  (`kit/site/src/market_site/ledger.py`, `list_lease_due`;
  `provisioning/compute/src/compute_provisioning/lease_lifecycle.py`). With the
  storefront advanced too, it journals a termination the provisioning service stamps
  at its own wall time (`lease_lifecycle.py`, `terminate_lease`), which the compute
  classifier does not recognise as commanded because it precedes the commanded
  instant (`domains/compute/src/arkhai_compute/end_classification.py`,
  `classify_site_end`); being earlier, the site's unclassified end becomes the
  deal's selected end.
- Every hop of the marketplace's v2 signing checks the signer's timestamp against
  the verifier's now within a skew, 300 s almost everywhere
  (`kit/identity/src/market_identity/verification.py`), in both directions: buyer
  and administrator to storefront (`core/storefront/src/core_storefront/auth.py`,
  `kit/deal-servicing/src/market_deal_servicing/routes.py`, `ingress.py`),
  storefront to registry (`core/registry/src/core_registry/api/publisher_auth.py`),
  storefront and harness to provisioning and the site
  (`provisioning/compute/service/src/compute_provisioning_service/middleware/auth.py`,
  `kit/site/src/market_site/auth.py`), and every typed client's response check. The
  doubles authenticate by bearer token, which carries no timestamp. Freshness also
  bounds replay state, which `redesign-authenticated-requests` prunes past the skew
  horizon. The design is coherent; what it requires is that the two parties on a
  signed hop agree on time within the skew.
- No party can tell it runs in production: no storefront, registry, provisioning or
  buyer configuration has an environment setting. The provisioning service mounts its
  mock controllers at `/test/*` only under its `mock` profile
  (`compute_provisioning_service/main.py`).
- Each service already has an operator surface where its pause controls sit: the
  storefronts' `/api/v1/admin/pause` and `/api/v1/admin/lifecycle/pause`,
  provisioning's `/api/v1/system/lease-watchdog/pause` and
  `/api/v1/system/fulfillment-convergence/pause`, the registry's `/api/v1/system/…`.

## Decisions

### D1 — One lane time, shared by every party

In a lane, every party perceives one time, which the test sets: both compute
storefronts, the API-credits storefront, the provisioning service and the site it
hosts, the API-credits service and the site ledger it hosts, the sample app's
metering middleware, every registry, both doubles, the chain, the buyer and the
harness's own signing clients. Each party moves its whole perception of time, not
a clock for one purpose.

Authentication is kept as it is. Timestamp freshness is coherent: a timestamp is a
claim checked within a tolerance, never an order between two parties. Moving one
party's time breaks every signed hop between it and a party that did not move once
the gap passes the skew; when every party on a hop moves by the same amount, every
hop stays within it. So the boundary of lane time is every party that signs,
verifies or decides by time in the lane.

Rejected:

- Moving only the site's lease clock with both doubles, leaving the storefronts on
  wall time. It drives an authority-ended deal, since the storefront schedules an end
  the authority dated in its future, but leaves the storefront's own judgements, the
  buyer's watchdog and the registry on wall time, short of determinism.
- Moving the storefronts' and the doubles' clocks with the compute classifier and end
  selection changed to accept a termination the site stamps earlier: production
  classification bent to suit a test clock.
- Services and the harness only, with the buyer on wall time: the buyer's watchdog
  decides by elapsed time and stays undrivable.
- Widening the skew in lanes: a security parameter in configuration, where production
  could set it wrong, widening the replay horizon with it.
- Authentication reading real time while everything else reads lane time: a
  purpose-specific clock, and evidence dated inconsistently, since response envelopes
  are retained at their signed timestamp.
- Reworking authentication away from timestamps: a protocol change at every
  authority, contradicting `redesign-authenticated-requests`, for a design that is not
  broken.
- Process-wide faked time through an `LD_PRELOAD` library: it needs the library in
  the release images, a variable outside the configuration system, and stays
  invisible to every test below the lane.

### D2 — Injected time is off by default and announced, never refused

Each party takes one setting, `time.source = "wall" | "injected"`, `"wall"` by
default, in its own configuration format: the storefronts' `[Time] source`,
provisioning's `time.source`, the registry's `TIME_SOURCE`, the buyer's
`[time] source`. The production image necessarily carries the control; production
configuration simply never sets `"injected"`, and nothing refuses it, since no party
can recognise production. With `"injected"`, a process logs it at startup and reports
it, with its current instant, on its status surface; a party with an Arkhai payments
section whose `livemode` is `true` also logs a warning. A static check holds that no
committed configuration outside the lanes sets `"injected"`: the chart defaults, the
local Helm release's values (D17), the production examples such as
`helm/charts/bare-metal-storefront/examples/production-values.yaml`, and the shipped
presets.

A typed configuration model refuses an unknown key, so an older image given a lane
configuration with this setting fails naming it rather than reading wall time.

Rejected: a refusal coupled to `livemode`, which protects only the parties with
payments configured while suggesting all are protected; a profile-gated setting,
since the storefronts are not on the profile loader; a new deployment-wide
`deployment = "test" | "production"` setting, a concept nothing else uses and one more
value an operator can set wrong.

### D3 — One explicit time source per process

Each process reads the time of the world from one time source, installed by its
composition root from `time.source`, and from nothing else. Every production read —
the 221 direct reads among them — goes through it. Where an injected clock parameter
already exists (`EndService`, `DealWatch`, `RateParts`, the compute delivery path),
its default becomes the process source, so unit-level seams keep working. A duration
of the process's own activity is measured on the monotonic clock (D20).

The buyer, a frozen `market` binary the harness starts per stage, has no API: its
source reads a lane-time file its configuration names, on every read (D19).

Rejected:

- `time-machine`, which patches Python's time functions process-wide at the C level
  and would convert no read. It moves every third-party read too, including the ones
  that measure elapsed work: under frozen time (D11) a library's deadline written
  against `time.time()` never expires. It patches the interpreter's standard library
  at runtime in production, and is invisible at the call site. The existing library
  does not meet the requirement, which is what `implementation.md`'s "Prefer an
  existing library" admits.
- libfaketime steered by a file a route rewrites: as in D1.
- A clock passed through every constructor from each root: the same reads converted,
  with many more signatures changed, for nothing a test needs beyond injected
  defaults.
- A fixed offset in the buyer's configuration per invocation: a `buy` running across
  an advance would not see it. The buyer asking a service for the time: in production
  that would make a seller the buyer's clock.

### D4 — Lane time moves only forward and is never reset

Lane time only moves forward. Each module continues from the instant the previous one
left, and no fixture returns a party to wall time: the doubles' per-module reset
existed only because they ran ahead of every other party. A stage may set any forward
instant, including one derived from the wall time plus an offset; what is
deterministic is the order of events, not pre-chosen instants. A backward set is
refused, naming the party and both instants.

Rejected: keeping a reset per module, which moves journals backwards and reopens
replay windows once replay state is pruned against the clock.

### D5 — The time controls sit on each service's operator surface

| Service | Setting route | Status |
|---|---|---|
| VM, bare-metal and API-credits storefronts | `POST /api/v1/admin/time` | `/api/v1/admin/status` |
| Provisioning service | `POST /api/v1/system/time` | its system status |
| Registry | `POST /api/v1/system/time` | its system status |
| API-credits service and the sample app | on their existing operator surface, beside their status | their status |

A request carries `{"now": <Unix seconds>}`. The answer is
`{"source": "injected", "now": <Unix seconds>}`; an instant earlier than the
service's current one is refused `409 time_moves_forward`. Each status carries
`{"time": {"source": "injected", "now": …}}` or `{"time": {"source": "wall"}}`. The
route is mounted only on an instance configured for injected time (D12), behind the
service's administrator authentication, exempt from request freshness alone (D14).

The storefronts bind one kit-owned, framework-free route service in `kit/storefront`
at the same path, as they bind the trading pause; the route service's generic part —
the forward-only set and the status section — comes from the time component (D6).
Each typed client — the storefront client, the provisioning client, the registry
client — gains a `set_time` method and the status time section.

Rejected: a new `/test` base path. The doubles keep theirs (D18), since they are
test-only tools.

### D6 — The time source is a standalone component

The source is generic infrastructure, so it is a standalone component
([`implementation.md`, "Generic infrastructure is a standalone component"](../../../docs/guidance/engineering/implementation.md#generic-infrastructure-is-a-standalone-component)):
under `tools/`, the standard library only, naming no market concept, published, its
boundary held by a structure test of its own, as `tools/frp-grant-admission` is. It
holds:

- the process source: wall, or injected and frozen (D11);
- its installation from a configured source;
- the forward-only set, refusing an earlier instant;
- the lane-time file's reader and writer, so the harness and the buyer share one
  definition of the file (D19);
- a framework-free route service for the setting route and the status section.

Every package and the doubles depend on it; each service's HTTP binding stays its own.
`make check-architecture` gains the allowance for depending on it. It is a new
capability, `injected-time`, with its own specification.

Rejected: a `kit/time` foundation kit with the standard library only, as
`kit/identity` is, which suits the architecture check but breaks the
standalone-component rule.

### D7 — One lane-time fixture sets every party

One fixture replaces `lane_double_clock`. The run's profile names its mode (D16) and
every party; a lane provides its own configuration, so a missing party fails the
setup rather than skipping. At the session's start the fixture sets every party to
the wall time at that moment. `lane_time.set(T)` moves the harness's own source
first, then each storefront, provisioning service, registry and the API-credits
lane's services, then both doubles, then the chain (D15), then the buyer's file; it
then reads every party's status and fails naming any that does not report T.

### D8 — The scenario rule restated

`docs/guidance/repository/deal-scenarios.md`, `docs/development/TESTING.md`, and
the engineering rule in `system-tests.md` state the discipline under lane time:

- In an injected run, a stage reaches an instant by setting lane time, never by
  waiting, and waits only for its own request's effect.
- A wall-time run (D16) keeps today's waits for instants the Agreement fixes.
- Back-dating a record and stepping the loop that acts on it remains admitted, below
  setting time: weaker, and discouraged once a party's time can be set.

New rows use lane time. Today's back-dating — the VM lease-end technique — and the
pause-based workarounds stay until rewritten, which is deferred work recorded in the
change index.

### D9 — The change's name, its capabilities and the roadmap

The change keeps its name: the branch, the worktree and two other changes refer to
it, and its documents state its scope.

Modified capabilities: `market-composition` (the storefronts' setting, route,
status and warning), `physical-provisioning` (provisioning's), `site-capacity` (the
site's expiry decisions at the process source), `registry-discovery` (the
registry's), `buyer-orchestration` (the buyer's source and file),
`marketplace-identity` (the freshness exemption; signing clients read the process
source), `test-compatibility` (lane time, the fixture, the doubles, the run modes,
the lanes) and `deployment-state` (the static check, the local release on wall time).
New: `injected-time`. The stores that convert their database times
(`kit/fulfillment`, `kit/resource-pools` among them) are held by `injected-time`'s
requirement on read times (D13), not by deltas of their own capabilities.
`vm-storefront-fulfillment` is not touched.

On the roadmap, the unowned "perceived clock for the site and the buyer half" row
becomes this change's. `converge-ongoing-compute-leases`' task 4.1a (the bare-metal
storefront's clock) and its open question on the site's clock are answered here, as
is `serve-running-rate-deals`' open question on the spot notice's wait: a stage sets
lane time to the notice's effect.

### D10 — Implementation cadence

Two rounds, then closeout.

- **Round 1, the conversion**, four sessions; its review sees every read moved and
  the check holding:
  1. the time component, its specification, the check and the engineering guidance;
  2. the storefront side: `core_storefront`, the storefront and servicing kits, the
     VM, bare-metal and API-credits storefronts;
  3. the service side: provisioning, `kit/site`, the registry, the API-credits
     service and the metering middleware;
  4. the buyer side and the signing clients.
  The check is switched on at the end of the round.
- **Round 2, the controls and the lanes**, two sessions:
  1. the setting routes, status sections, settings and the livemode warning in every
     service; the freshness exemption; the static configuration check;
  2. the doubles, the fixture, the buyer's file, the chain, the run modes, the three
     lanes, the hold-passed scenario, and the rule restated.

### D11 — Injected time is frozen at an absolute instant

An injected source returns exactly the instant last set, until it is set again:
time moves only when the test moves it. Every party agrees exactly, because an
advance sets each one to the same instant rather than adding a delta to clocks read
at slightly different moments, and nothing elapses unseen: an approval window, a
delivery deadline or an Agreement's start arrives only when a stage sets time to it.

The representation is Unix seconds, `{"now": 1794821400}`, in the lane-time file, the
setting route's request and answer, and the status section. A process configured for
injected time starts frozen at the wall instant it started and reports that on its
status, until the session fixture sets it (D7). The lane starts from the wall time at
the session's start, which keeps payments receipt-key pins, checked at the snapshot's
instant, and certificates, checked on real time, valid; a fixed epoch would break
both.

Rejected: a source running from the set instant at real rate, which lets parties
drift by however far apart their settings landed and lets a wall-time wait slip
through; an offset, which says nothing about which instant a party is at.

### D12 — An instance's time is never changed live

The time source is configuration. The setting route exists only on an instance
configured for injected time, so a wall-time instance has none, and switching source
means reconfiguring and restarting. A service's time is a claim it signs and
exchanges: freezing or advancing a live service would date its records and evidence
falsely, break every signed hop with counterparties on real time, and stop none of
the authorities' deadlines. Pausing loops and the explicit operator actions — ending a
deal, terminating or force-releasing a lease, stepping a loop — serve diagnosis and
recovery. An incident is reproduced on a copy: the database restored into a local or
lane stack configured for injected time.

Rejected: a runtime switch on any instance, with or without a refusal beside
`livemode`.

### D13 — Database times are supplied where production logic reads them

Every database time production logic reads — a column a query orders, filters or
expires by, or a decision compares — is supplied by the application from the process
source: ORM defaults become Python `default=` and `onupdate=` callables, and raw SQL
passes the time. An audit-only `created_at` or `updated_at` that nothing reads keeps
its SQL default. Each store's integration test under injected time asserts the
columns it reads. Which columns are read is a judgement made per column in
implementation, not a check.

Rejected: supplying every database time and flagging SQL time functions in a check.
Many tables carry a `created_at` that is hard to supply from the application and
affects no test, and determinism needs only the times something decides by.
Rebuilding tables to drop their DDL defaults: migration steps in seven chains and an
upgrade for every operator, for a failure the integration tests catch.

### D14 — The time-setting operation is exempt from request freshness

An advance of more than the skew crosses every signed hop: a harness that moves
itself last signs at T and cannot verify a response stamped at T′; one that moves
itself first signs at T′, which a service still at T refuses. So the setting
operation alone skips the request timestamp's freshness check. Its signature, the
administrator principal, the operation, method and resource, and the request-id
reservation are verified as for every request; an earlier instant is refused. Under
D11 a replay is either an exact retry, which the reservation answers, or names an
instant already reached, which is refused; and the route exists only under injected
time (D12). The harness moves its own source first, signs each setting call at T′, and
verifies each response normally.

Rejected: signing at T and verifying at T′ with a per-call clock in the harness's
clients, a purpose-specific clock hidden in test code; advancing in steps within the
skew, which takes thousands of rounds for a dispute window; a bearer control token on
the admin surface, a second kind of administrator authentication.

### D15 — The chain follows lane time

Under frozen lane time, Anvil, which stamps blocks with wall time, drifts ahead over
the whole run, and an escrow's expiration is compared both on chain and off it
(`kit/alkahest/src/market_alkahest/escrow_verification.py`). At the session's start
and at every set, the fixture sets Anvil's next block timestamp to the lane instant
and mines a block; between sets the chain runs at real rate, ahead of lane time by
the real time since the last set, which escrow windows far exceed. Implementation
checks whether Anvil can be frozen too (`anvil_setBlockTimestampInterval`) and adopts
it if so.

Rejected: leaving the chain on wall time, which fails as runs lengthen.

### D16 — One time source per run

A run is injected or wall time throughout; the session fixture reads every party's
status and fails naming a mix, since a frozen party drifts behind every real one and
signed hops and grants then fail. The three Compose lanes run injected (D21).
External-topology runs — the real-provisioning lane, whose relay plugin checks grant
expiry on its own clock (`tools/frp-grant-admission`), and every run against hosted
authorities — run on wall time. In wall mode the lane-time helper reaches only an
instant the Agreement fixes, by waiting for it; a module needing any other instant is
a blocked skip naming the wall-time target. The shared stages call one helper either
way, so they stay shared.

For an external component whose time a test does not control, the policy is a
ladder:

- if the scenario does not exercise the component's time-dependent behaviour, keep
  its times out of the way: expiries and windows set far enough ahead that no run
  reaches them;
- if it does, control its time: through its own control, a provider's test clock
  among them (the hosted payments service and dispute authority are to gain injected
  time in their own repository); else through a double that stands in for it with a
  time set with the others';
- a proxy that rewrites the times in a backend's responses changes only what the
  backend reports, never when it acts, and cannot rewrite signed values, so it serves
  only times the scenario does not exercise;
- below those, back-dating a record and stepping the loop that acts on it;
- otherwise the run uses wall time, blocking what it cannot reach.

Rejected: giving the relay plugin a time control so the real-provisioning lane runs
injected, which leaves hosted runs on wall time anyway and puts a test control in a
security component; injected runs only, which would cut the external-topology runs
off from the shared stages.

### D17 — The local Helm release stays on wall time

`helm/local-values.yaml` serves interactive use and pre-review validation
(`scripts/validate_slice.py`). A release frozen under injected time would sit still
for an interactive user. The scenarios validation runs against it — `contracts`,
`e2e_alkahest_escrow_codecs`, `e2e_alkahest_trusted_oracle` — set no time, so they run
in wall mode. A validation-only overlay setting `"injected"` comes when a
time-driven scenario joins that list.

### D18 — The doubles take injected time

The doubles' `PerceivedClock` and offset give way to the shared source, one name for
the concept. `POST /test/clock/advance` and `POST /test/clock/reset` become
`POST /test/time {"now"}` with the same answer and refusal as D5's, behind their
existing control bearer token and `/test` path; their status reports
`{"source", "now"}`. `tools/lane-double-controls`' models and client change with them,
and the hold-passed scenario sets instants instead of advancing.

### D19 — The harness and the buyer

The harness installs an injected source in its own process; its signing clients read
the process source, with no clock per client. The buyer takes `[time] source =
"injected"` with `file = "<path>"`; the file holds `{"now": <Unix seconds>}`, which the
harness writes through the component's writer, atomically (a temporary file, then a
rename). A buyer configured for injected time whose file cannot be read refuses to
start, naming the file.

### D20 — The check and the guidance

A repository check forbids direct wall-time reads in production source and in the
doubles: `time.time`, `time.time_ns`, `datetime.now`, `datetime.utcnow`,
`date.today`, `datetime.today`, and argument-free `time.gmtime()` and
`time.localtime()`. A duration of the process's own activity — a timeout, a poll
budget, a backoff, a rate-limiter window, a loop interval — reads `time.monotonic()`,
which the check permits: under frozen lane time a duration measured on lane time is
always zero, and a monotonic clock neither stops when time is held nor jumps when it
is set. Every read is classified once: a value stored, signed, sent to another party,
or compared with an instant another party knows is lane time; a value only subtracted
from another reading in the same process is elapsed work. SQL time defaults are
outside the check (D13).

Engineering guidance in `implementation.md` states: a process reads the time of the
world from one time source and nothing else; a duration of its own activity is
measured on the monotonic clock, which neither stops when time is held nor jumps
when it is set.

### D21 — Every Compose lane runs injected time

All three Compose lanes run the doubles, and under D11 the doubles are frozen, so
every party in each lane runs injected time, the API-credits lane's storefront,
credits service and sample app's middleware included. The local Helm release stays on
wall time (D17).

Rejected: the API-credits lane on wall time, with its doubles on wall time: two modes
among the locally verifiable lanes for no saving, since the check converts that code
anyway.

## Open Questions

None. Previews at a chosen instant are a non-goal (`proposal.md`).
