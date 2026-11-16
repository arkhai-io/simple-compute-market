## Why

An end-to-end scenario may wait only on an effect its own request caused or for
an instant the Agreement fixes, and a behaviour defined by time elapsing is
driven by moving time through a control
([`deal-scenarios.md`, "The discipline every scenario follows"](../../../docs/guidance/repository/deal-scenarios.md#the-discipline-every-scenario-follows)).
Only the lane doubles have a movable clock (`tools/lane-double-controls`). Every
other party — the storefronts, the site, the registry, the buyer — reads wall time,
so after a double's clock moves, no step of theirs may follow: a stop the double
records at an advanced instant is in their future, and the site would end the lease
only when its own wall clock reached it. Pausing watchdogs and back-dating records,
the approach so far, is not a viable way to verify Goal 8's rate deals.

Moving any one party's time alone does not help either: every hop of the
marketplace's signing checks the other side's timestamp within a skew, so a party
moved alone breaks every signed exchange with a party that did not move. Fully
deterministic verification of rate deals needs one time, shared by every party in a
lane and set by the test.

This change is one of Goal 8's three MVP changes: it runs beside
`serve-running-rate-deals`, whose funds-exhausted rows in both lanes need it, and
`switch-on-hosted-per-period-vm` follows them. It takes the whole of the roadmap's
"perceived clock" gap: the storefronts', the site's and the buyer's shares.

## What Changes

- **One time source per process.** A standalone component, `injected-time`, gives
  each process one source of the time of the world, wall time by default or injected
  time frozen at an instant the test sets. Every production read of wall time — about
  221 across core, kit, domains, provisioning and the buyer — goes through it; a
  duration of a process's own activity is measured on the monotonic clock. A
  repository check forbids direct wall-time reads.
- **Database times where logic reads them.** Every database time production logic
  reads is supplied by the application from the source; audit-only columns keep their
  SQL defaults.
- **A setting in every party.** `time.source = "wall" | "injected"`, `"wall"` by
  default, in each storefront, the provisioning service, the registry, the API-credits
  service, the sample app, the doubles and the buyer. Injected time is announced at
  startup and on status with its current instant, warned beside payments
  `livemode = true`, and never set by committed configuration outside the lanes.
  Nothing refuses it: the production image carries the control unused.
- **A setting route on each operator surface.** `POST /api/v1/admin/time` on the
  storefronts and `POST /api/v1/system/time` on provisioning and the registry, mounted
  only under injected time, forward-only, behind administrator authentication and
  exempt from request freshness alone; each typed client gains `set_time`.
- **The buyer and the harness.** The buyer's source reads a lane-time file the
  harness writes; the harness's signing clients read its own process source.
- **The doubles and the chain.** The doubles take injected time behind
  `POST /test/time`; the lane fixture sets the chain's block time with every set.
- **One lane-time fixture.** It sets every party to one instant, in order, confirms
  each status, and never resets: lane time only moves forward.
- **Run modes.** The three Compose lanes run injected time; external-topology runs and
  the local Helm release run on wall time, reaching only Agreement-fixed instants.
- **The rule restated.** `system-tests.md`, `deal-scenarios.md` and `TESTING.md`
  state that a stage reaches an instant by setting lane time, with back-dating
  admitted below it, and the policy for an external component whose time a test does
  not control.

## Capabilities

### New Capabilities

- `injected-time`: the standalone time component — the process source, its frozen injected form, the forward-only set, the lane-time file, the setting route service — and the obligations of every process that reads time.

### Modified Capabilities

- `market-composition`: the storefronts' time setting, setting route, status section and livemode warning.
- `physical-provisioning`: the provisioning service's time setting, setting route and status section.
- `site-capacity`: the site's hold and lease decisions at the process source.
- `registry-discovery`: the registry's time setting, setting route and status section.
- `buyer-orchestration`: the buyer's time setting and lane-time file.
- `marketplace-identity`: the setting operation's freshness exemption; signing at the process source.
- `test-compatibility`: lane time across every party, the fixture, the doubles' injected time, the chain, run modes and the lanes.
- `deployment-state`: injected time absent from committed configuration outside the lanes; the local Helm release on wall time.

## Non-Goals

- Changing a live instance's time for diagnosis or recovery; time is changed only on an instance configured for injected time.
- New previews or dry runs at a chosen instant.
- Injected time in the hosted payments service and dispute authority, which is their own repository's change.
- Injected time in the real-provisioning lane, its relay plugin, or any external-topology run, which run on wall time.
- Rewriting today's back-dating and pause-based workarounds in existing scenarios, recorded as deferred work in the change index.
- Supplying audit-only database times from the application, or rebuilding tables to drop their SQL defaults.
- Writing the funds-exhausted scenarios themselves, which are `serve-running-rate-deals`'.
- Any time source but wall time in a production deployment.

## Impact

- Code: every production module that reads wall time, in every service, kit and the buyer; a new standalone component under `tools/`.
- Configuration: one new setting in each party, defaulting to wall time; lane configuration sets it.
- Operator API: a setting route on each service's operator surface, present only under injected time; a time section on each status.
- Authentication: one operation exempt from request freshness, present only under injected time.
- Database: application-supplied times for the columns production logic reads; no migration.
- Tests: the lane-time fixture replaces `lane_double_clock`; the doubles' clock controls change; every lane module runs on lane time.
- Packaging: the component is a published, dependency-free distribution every package depends on.
- No wire change to any production contract.

## Dependencies and Related Changes

- No dependency. Runs in parallel with `serve-running-rate-deals`, whose funds-exhausted rows depend on it; its other rows do not.
- Takes `converge-ongoing-compute-leases`' task 4.1a, the bare-metal storefront clock, and answers its open question on the site's clock.
- Answers `serve-running-rate-deals`' open question on the spot notice's wait: a stage sets lane time to the notice's effect.
- Takes Goal 8's unowned perceived-clock row in `docs/development/ROADMAP.md`, the site's and the buyer's shares included.
- `redesign-authenticated-requests` prunes replay state against request freshness; this change's exemption covers one operation present only under injected time, whose forward-only meaning makes a replay harmless.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `market-composition`, `physical-provisioning`, `site-capacity`, `registry-discovery`, `buyer-orchestration`, `marketplace-identity`, `test-compatibility`, `deployment-state`
- [x] New subsystem specification: `injected-time`
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `ARCHITECTURE.md` — lane time across every party and why authentication needs it; `test-compatibility`'s spec and companion.
- D2: `injected-time`'s spec and the modified services' specs — the setting, its default, its announcement and warning; `DEPLOYMENT_AND_CONFIG.md` — the setting; `docs/guidance/engineering/configuration.md` — a test control the production image must carry is off by default and omitted from production configuration, not refused.
- D3: `injected-time`'s spec and companion — one source per process, installed by its root; `ARCHITECTURE.md`.
- D4: `test-compatibility`'s spec — lane time only moves forward, never reset.
- D5: `market-composition`, `physical-provisioning` and `registry-discovery` specs — the setting routes and status sections; the operator handbook.
- D6: `injected-time`'s spec and companion; `tools/README.md`; `published-packages.md` — the component's place.
- D7: `test-compatibility`'s spec; `TESTING.md` — the lane-time fixture.
- D8: `docs/guidance/engineering/system-tests.md`, `docs/guidance/repository/deal-scenarios.md` and `TESTING.md` — reaching an instant by setting lane time, back-dating below it.
- D9: `ROADMAP.md` and the change index — the perceived-clock row owned and closed, convergence's task 4.1a and its open question answered.
- D10: no permanent destination — the implementation cadence governs this change's rounds only.
- D11: `injected-time`'s spec — frozen injected time, its representation and starting point.
- D12: `injected-time`'s companion and the operator handbook — no live change of an instance's time.
- D13: `injected-time`'s spec — database times production logic reads come from the source.
- D14: `marketplace-identity`'s spec — the setting operation's freshness exemption.
- D15: `test-compatibility`'s spec; `TESTING.md` — the chain set with lane time.
- D16: `test-compatibility`'s spec; `TESTING.md` — run modes; `docs/guidance/engineering/system-tests.md` — the ladder for an external component whose time a test does not control.
- D17: `deployment-state`'s spec; `DEPLOYMENT_AND_CONFIG.md` — the local Helm release on wall time.
- D18: `test-compatibility`'s spec and companion; `tools/lane-double-controls/README.md` — the doubles' injected time.
- D19: `buyer-orchestration`'s spec; `TESTING.md` — the buyer's lane-time file and the harness's source.
- D20: `docs/guidance/engineering/implementation.md` — one time source per process, elapsed work on the monotonic clock; `injected-time`'s spec — the check.
- D21: `test-compatibility`'s spec; `TESTING.md` — every Compose lane on injected time.
