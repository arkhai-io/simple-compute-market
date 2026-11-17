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
  (`tools/lane-double-controls`, its modules `lane_double_controls.clock` and
  `lane_double_controls.routes`), and
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
- The storefronts and provisioning have an operator surface where their pause
  controls sit, behind signed administrator requests: the storefronts'
  `/api/v1/admin/pause` and `/api/v1/admin/lifecycle/pause`, provisioning's
  `/api/v1/system/lease-watchdog/pause` and
  `/api/v1/system/fulfillment-convergence/pause`. Their signed status is
  `GET /api/v1/system/status`, the storefronts' read as `admin_system_status`
  through the canonical client's `get_system_status`. The registry's administrator
  surface is `/admin/api-keys`, behind the shared bearer key `REGISTRY_ADMIN_API_KEY`
  (`core/registry/src/core_registry/api/api_key_auth.py`, `require_admin_api_key`);
  its signed `/api/v1/system/*` routes admit only the marketplace roles, and it has no
  status route. The API-credits service has no status route; its signed routes, held
  by `kit/site`'s `SiteAuthMiddleware`, admit an `admin` role on every contract. The
  sample app, an unpublished test-only project, has no operator surface at all.

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
provisioning's and the API-credits service's `time.source`, the registry's
`TIME_SOURCE`, the sample app's `APICREDITS_SAMPLE_APP_TIME_SOURCE`, the buyer's
`[time] source`. A value other than `"wall"` or `"injected"` refuses startup, naming
the setting and the value (17 F4). The production image necessarily carries the control; production
configuration simply never sets `"injected"`, and nothing refuses it, since no party
can recognise production. With `"injected"`, a process logs it at startup and reports
it, with its current instant, on its status surface; a party with an Arkhai payments
section whose `livemode` is `true` also logs a warning. A static check holds that no
committed configuration outside the lanes sets `"injected"`: the chart defaults, the
local Helm release's values (D17), the production examples such as
`helm/charts/bare-metal-storefront/examples/production-values.yaml`, and the shipped
presets.

An older image ignores the setting and runs on wall time: the registry's settings
ignore unknown keys and provisioning's Dynaconf accepts any. The session fixture
refuses it, naming the party, since its status lacks the time section, reports wall
time, or does not report the instant set (D7, D16; 17 F5).

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

| Service | Setting route | Status | Administrator authentication |
|---|---|---|---|
| VM, bare-metal and API-credits storefronts | `POST /api/v1/admin/time` | `GET /api/v1/system/status` | signed |
| Provisioning service | `POST /api/v1/system/time` | `GET /api/v1/system/status` | signed |
| API-credits service | `POST /api/v1/system/time` | `GET /api/v1/system/status`, new | signed, `admin` role |
| Registry | `POST /admin/time` | `GET /admin/status`, new | bearer `REGISTRY_ADMIN_API_KEY` |

A request carries `{"now": <Unix seconds>}` (D11). The answer is
`{"source": "injected", "now": <Unix seconds>}`; an instant earlier than the
service's current one is refused `409 time_moves_forward`, and a body other than a
valid `{"now": …}` is refused `422 invalid_time`; neither changes anything. Each
status carries `{"time": {"source": "injected", "now": …}}` or
`{"time": {"source": "wall"}}`. The route is mounted only on an instance configured
for injected time (D12), behind the service's administrator authentication.

The storefronts' time section goes on their existing signed status, read through
the canonical client's `get_system_status`; no new storefront status route (A1). The
API-credits service gains two signed route contracts, the setting route admitting only
`admin` and the status admitting `admin`, beside its existing contracts, since its
middleware refuses a route without one (17 F2). The registry's control sits on its
existing administrator surface beside `/admin/api-keys`, behind the shared bearer
key, answering unsigned as those routes do; a bearer request carries no timestamp, so
it needs no freshness exemption (17 F1). A signed administrator role on the registry
is an unowned gap in the change index, for the change that adds its first production
administrator function.

The storefronts bind one kit-owned, framework-free route service in `kit/storefront`
at the same path, as they bind the trading pause; the route service's generic part —
the forward-only set, the value's validation and the status section — comes from the
time component (D6). Each typed client — the storefront client, the provisioning
client, the API-credits service's client, the registry client — gains a `set_time`
method and the status time section; the registry client's send the administrator
key.

Rejected: a new `/test` base path for the services. The doubles and the sample app
keep or take one (D18), since they are test-only tools. A signed administrator role
on the registry for this control (17 F1): new identity surface — a trust set, its
configuration, rotation — for a control present only under injected time.

### D6 — The time source is a standalone component

The source is generic infrastructure, so it is a standalone component
([`implementation.md`, "Generic infrastructure is a standalone component"](../../../docs/guidance/engineering/implementation.md#generic-infrastructure-is-a-standalone-component)):
under `tools/`, the standard library only, naming no market concept, published, its
boundary held by a structure test of its own, as `tools/frp-grant-admission` is. It
holds:

- the process source: wall, or injected and frozen (D11);
- its installation from a configured source;
- the time value's validation (D11) and the forward-only set, refusing an earlier
  instant;
- the lane-time file's reader and writer, so the harness and the buyer share one
  definition of the file (D19);
- a framework-free route service for the setting route and the status section.

Every package and the doubles depend on it; each service's HTTP binding stays its own.
`make check-architecture` gains the allowance for depending on it (corrected in
implementation: the check skips `tools/`, so the allowance is each package's own
`allowed-dependencies` entry, with no `ARCHITECTURE.toml` row; "Implementation
record", §1). It is a new
capability, `injected-time`, with its own specification.

Rejected: a `kit/time` foundation kit with the standard library only, as
`kit/identity` is, which suits the architecture check but breaks the
standalone-component rule.

### D7 — One lane-time fixture sets every party

One fixture replaces `lane_double_clock`. The run's profile names its mode (D16) and
every party; a lane provides its own configuration, so a missing party fails the
setup rather than skipping. At the session's start the fixture sets every party to
the wall time at that moment, or to the latest instant a party already holds when
that is later — a chain a second ahead, or a stack an earlier run left ahead — so
the start never sets a party back (D4; 45 session-start). It reads the parties it
reaches with no signed timestamp first — the registries' bearer administrator
route, the controls, the chain and the buyer's file, which every set moves — and
moves the harness's source to the latest instant they hold before reading any
signed status, so a stack left ahead past the signing skew answers it; a service
still past the skew from that instant counts as holding none, so the set moves
one restarted behind forward, and one left ahead by a run stopped partway through
a set refuses it and fails the start by name (72 F1;
rejected: exempting the administrator status read from freshness, which widens
the identity exception, and requiring a fresh stack for each session). The local Helm release's
validation names its storefront, provisioning service and registry too, on wall
time, through the e2e-tests chart's `config` passed through whole as its pods'
`e2e-tests` profile, so it reads each one's status (D16, D17; 45 F1). `lane_time.set(T)` moves the harness's own source
first, then each storefront, provisioning service, registry and the API-credits
service, then both doubles and, in the API-credits lane, the sample app (D18), then
the chain (D15), then the buyer's file; it then reads every party's status and fails
naming any that does not report T — an older image without a time section among them
(D2).

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
`api-credits` (the API-credits service's setting, route and status; 17 F2),
`marketplace-identity` (the freshness exemption; signing clients read the process
source), `test-compatibility` (lane time, the fixture, the doubles and the sample
app's control, the run modes, the lanes) and `deployment-state` (the static check,
the local release on wall time).
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
  2. the doubles and the sample app's control, the fixture, the buyer's file, the
     chain, the run modes, the three lanes, the hold-passed scenario, and the rule
     restated.

### D11 — Injected time is frozen at an absolute instant

An injected source returns exactly the instant last set, until it is set again:
time moves only when the test moves it. Every party agrees exactly, because an
advance sets each one to the same instant rather than adding a delta to clocks read
at slightly different moments, and nothing elapses unseen: an approval window, a
delivery deadline or an Agreement's start arrives only when a stage sets time to it.

The representation is Unix seconds, `{"now": 1794821400}`, in the lane-time file, the
setting route's request and answer, and the status section. `now` is a JSON integer
from 0 to 253402300799, the last second of year 9999 and the largest instant a UTC
`datetime` holds; a boolean, a float, a string, a value out of range, a missing `now`
or any other member is invalid, read by one rule in the time component wherever the
value is parsed (17 F4). Integer seconds match the signing protocol's integer
timestamps, which would truncate a finer instant on every signed hop, and make the
fixture's comparison exact. A process configured for
injected time starts frozen at the wall instant it started and reports that on its
status, until the session fixture sets it (D7). The lane starts from the wall time at
the session's start, which keeps payments receipt-key pins, checked at the snapshot's
instant, and certificates, checked on real time, valid; a fixed epoch would break
both.

Rejected: a source running from the set instant at real rate, which lets parties
drift by however far apart their settings landed and lets a wall-time wait slip
through; an offset, which says nothing about which instant a party is at; fractional
seconds (17 F4), truncated on every signed hop and needing a conversion rule each
reader must share, for sub-second control no scenario needs.

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
operation alone skips the request timestamp's freshness check, on the services whose
administrator requests are signed: the storefronts, provisioning and the API-credits
service. The registry's bearer-authenticated control carries no timestamp and needs
no exemption (D5; 17 F1). Its signature, the
administrator principal, the operation, method and resource, and the request-id
reservation are verified as for every request; an earlier instant is refused. Under
D11 a replay is either an exact retry, which the reservation answers, or names an
instant already reached, which is refused; and the route exists only under injected
time (D12). The harness moves its own source first, signs each setting call at T′, and
verifies each response normally.

Rejected: signing at T and verifying at T′ with a per-call clock in the harness's
clients, a purpose-specific clock hidden in test code; advancing in steps within the
skew, which takes thousands of rounds for a dispute window; a bearer control token on
a signed admin surface, a second kind of administrator authentication there. The
registry's bearer key is no second kind: it is the registry's only administrator
authentication (17 F1).

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

The sample app is in the doubles' category, not the services': unpublished, installed
only by the lanes (`published-packages.md`). It takes the same control (17 F2):
`POST /test/time {"now"}` and a status reporting `{"source", "now"}`, behind a
control bearer token from its own environment, excluded from the metering gate,
mounted only under injected time, through `lane-double-controls`' models and
client. The metering middleware, which is published, gains no control: it reads the
process source its host installs, which the sample app installs from
`APICREDITS_SAMPLE_APP_TIME_SOURCE` and a seller's application leaves on wall time.

### D19 — The harness and the buyer

The harness installs an injected source in its own process; its signing clients read
the process source, with no clock per client. The buyer takes `[time] source =
"injected"` with `file = "<path>"`; the file holds `{"now": <Unix seconds>}`, which the
harness writes through the component's writer, atomically (a temporary file, then a
rename). The file is read by the time component's rule (D11). A buyer configured for
injected time whose file cannot be read or holds an invalid value refuses to start,
naming the file; a later read that fails fails the command, naming the file, and never
falls back to wall time; `"injected"` without `file` refuses startup (17 F4).

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
credits service and sample app included: the sample app's middleware signs every
request to the credits service, so it shares lane time through the app's control
(D18). The local Helm release stays on
wall time (D17).

Rejected: the API-credits lane on wall time, with its doubles on wall time: two modes
among the locally verifiable lanes for no saving, since the check converts that code
anyway.

## Open Questions

None. Previews at a chosen instant are a non-goal (`proposal.md`).

## Implementation record

Findings and alternatives from implementation that the decisions above do not hold,
moved here from `tasks.md`'s notes.

- §1 (1.7): `make check-architecture` skips `tools/`, so `arkhai-injected-time` is no
  project in its model: depending on it forms no internal edge, and naming it in a
  kind allowlist would fail the check's configuration rule. D6's allowance is instead
  each package's own `allowed-dependencies` entry; no `ARCHITECTURE.toml` row.
- §1 (1.8): the source returns whole seconds, wall time included, so a converted
  `time.time()` or `datetime.now()` read loses its fraction; that matters only where
  something ordered or compared sub-second instants, judged per read.
- §3 (3.1): without `injected_time = "arkhai-injected-time"` under
  `[tool.arkhai.architecture.import-roots]`, `make check-architecture` reads the
  import as a distribution `injected-time` the package's allowlist does not name.
- §3 (3.1), §5 (5.1): whole seconds broke tests that compared a source read with a
  sub-second wall read, expected two stamps to differ without time moving, or failed
  only past half a wall second or when two rows fell in one second; such tests drive
  an injected source. Until section 7 converted the signing clients, a signed test
  injected an instant 120 s behind wall: inside the 300 s skew, yet told apart from a
  wall read.
- §3 (3.2), §5 (5.2): injected time holds one instant across many writes, so a query
  ordering by a store-written timestamp ties; ties break by an insertion key (`rowid`,
  `id`) where the table has one, and none was added where PostgreSQL, which has no
  `rowid`, may serve.
- §3 (3.4): stored leases on lane time — the fulfillment claim and poll interval,
  settlement servicing's retry, the storefronts' convergence leases — do not lapse
  while injected time is held; a lane stage sets time past them or steps the loop.
- §5 (5.1): a retired relay key's validity counted leases allocated strictly before
  its retirement, which sub-second stamps ordered. Within one whole second before
  cannot be told from after, so a same-second lease counts (`<=`): the bound may be
  later than needed, never earlier than a grant in use (the MODIFIED delta, 33
  relay-key).
- §5 (5.3): a service suite installs its internal dependencies as wheels from
  `.dist`; after editing a kit, `make dist` (or `make lock`) runs first or the suite
  tests the old code.
- §8 (8.2): the storefronts authenticate in module functions no composition builds,
  so they read the installed source per request; the provisioning and site
  middlewares are built by a composition and take the operation in their
  constructor. Since section 10 both exempt it only while the installed source is
  settable, since the provisioning app and route table are built once at import and
  shared by its tests.
- §9, §11: a composed app reads the installed source when it is built, and composing
  a service installs its configured source; a test installs its own source before
  building the app (after composing, where composition installs one) and restores it
  after. A test's stand-in at a real time route's path is shadowed by the real route
  under injected time.
- §12 (12.1): rejected for the static check, rendering with Helm and Compose: a
  render drops keys a chart does not template (the registry chart renders a fixed
  list) and gates the test on both tools; parsing the files refuses more and needs
  neither.
- §12 (12.2), §16 (16.1): the storefront files a lane shares with the full local
  stack (`storefront.alice.toml`, `storefront.dev.toml`) could not carry injected
  time without putting the full stack on it; the lanes took files and profiles of
  their own (`storefront.alice.lane.toml`, the registries' and provisioning's lane
  profiles).
- §15 (15.4, 45 F1): the local release's lane-time section was first merged into the
  shared `helm` profile; contract validation's pod, which layers `helm` alone, would
  then start the lane-time fixture without credentials and fail, so the section took
  its own `e2e-tests` profile, on the owner's choice.
- §15 (15.4, 60 F1): the credential-key refusal uses character classes since a JSON
  Schema pattern has no portable case flag. Declined: a key spelled with the Kelvin
  sign, which Python lowercases to `k`, passes the ASCII pattern; only a crafted key
  reaches it.
- §16 (16.3): D15's check answered — the lane's Anvil admits
  `anvil_setBlockTimestampInterval(0)`, adopted, so the chain is frozen between sets.
  Found when the first VM run's stage 08b failed: between sets the chain stamped wall
  time and ran ahead, and once the hold-passed module had moved lane time days ahead
  a later set fell below the latest block, which `evm_setNextBlockTimestamp` refuses.
