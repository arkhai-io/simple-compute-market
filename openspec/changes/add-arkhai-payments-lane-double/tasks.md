# Tasks — in-lane payment and mediation doubles

Design-stage implementation plan. No runtime implementation is claimed here. Preserve
completed items when this plan is executed. This change owns both executable doubles;
production adapters and their contract/fixture prerequisites remain in
`agreed-evidence-and-early-termination`.

## Dependency gates and first use

- Foundation sections 1–2 supply lifecycle interfaces; 8.1 supplies the payments
  revision/models/vectors; 9.1 supplies the shared snapshot fixture/frame seam; 12.1
  supplies the mediation published or explicitly draft schema/models and record
  fixture seam. Confirm these per boundary before building its corresponding mode.
  Missing publication/vectors permits pinned proposed-only work, not published claims.
- Foundation 11.1/12.2 adapter integration consumes these doubles after they exist;
  it is not a prerequisite to constructing them. Coordinate ownership edits in D7
  before implementation so a second mediation double is not assigned elsewhere.
- `spot-deals-through-arkhai-payments` owns production rate arithmetic/adapters and
  compute scenarios. `converge-ongoing-compute-leases` consumes the controls for end
  service/rate servicing. `activate-per-period-compute-servicing` owns later hosted
  capability readiness and live qualification. No horizon feature gates any of them.
- First use is the existing bare-metal and credits payment deals, through their lane
  targets, mock provisioning, seeded development payer and seller accounts and pinned
  fixture authority identities. No live credential or physical hardware is required.
  Later compute scenarios consume the same setup rather than creating another double.

New paths below are planned deliverables, not citations to existing implementation.
Within the new tooling root `tools/authority-lane-doubles`, filenames are relative to
that root. Test work adapts existing kept suites first. New acceptance tests require
maintainer approval of the stated property and system; this plan is not that approval.
Until granted, use temporary deterministic diagnostics and report the missing coverage
rather than expanding the suite implicitly.

## 1. Package, contract provenance and signed frames

- [ ] 1.1 Confirm the foundation gates and request D7's ownership edits in its design
      and tasks. Record the exact published/draft schema and vector hashes for each
      service. Refuse published readiness for any required unpublished surface; pin
      proposed candidates and a difference manifest without reintroducing dropped
      primitives. Files: new tooling contract manifests/candidate data under
      `src/authority_lane_doubles/contracts/`; consume, do not fork, kit SOURCE files.
- [ ] 1.2 Add the tooling `pyproject.toml`, `uv.lock`, `Makefile`, `Dockerfile` and
      `src/authority_lane_doubles/` package with separate payments and mediation
      entry points. Declare every imported kit distribution. Reuse kit fixture APIs;
      coordinate absent frame APIs upstream rather than duplicating framing. Build
      from `.dist` and the committed lock via the existing packaging helpers.
- [ ] 1.3 Add deterministic lane-only identities, accounts, initial balances and
      authority advertisement fixtures to the tool. Label all credential material
      public development-only, never for a public network. Keep production defaults
      empty. Expose health/status with contract metadata outside signed wire frames.

Verification: static schema validation and existing kit vector targets
`make -C kit/arkhai-payments check-vectors` and the foundation's mediation vector
suite when available; shared receipt/snapshot signing reproduces the pinned vectors.
Library integration uses real HTTP clients to read both services' initial state.
Packaging: new tool build/reinit/typecheck targets, `make check-packaging`.
Missing producer vectors are recorded as published-qualification gates, not passing
conformance evidence.

## 2. Payments HTTP double

- [ ] 2.1 Implement approval, exact Agreement attachments, receipts, snapshots,
      event reads and per-account authorization/idempotency in new tooling
      `src/authority_lane_doubles/payments.py`, reusing kit models and signers.
      Implement only the chosen contract in each mode, including explicit refusals
      for unsupported operations. Never emit live-mode records.
- [ ] 2.2 Add the target revision's per-part start, stop with notice and pending-stop
      maturity, absolute end, funding exhaustion and funded-through observations.
      Use the pinned rate-period arithmetic from start, including mixed once/rate
      mandates where supported; do not conflate transaction approval with start.
      Keep no payee stop on on-demand mandates and no horizon/vouch route.
- [ ] 2.3 Add held-money partial reverse before/after stop, afterStop payout timing,
      independent extend refs and lift, caps and contract refusal codes. Preserve
      idempotent results across lost responses. Share one state engine between HTTP
      and controls; do not grow a second rate simulator in FakePaymentsClient.

Verification: extend existing `kit/arkhai-payments/tests/test_client.py` setup to use
HTTP where it meaningfully covers transport; keep existing `test_receipt_fixture.py`
and `test_receipts.py` framing assertions. Deterministic library-integration drive:
start/stop authorization, notice firing with no storefront, two overlapping case
holds, partial reversal before/after stop and response-loss replay. Candidate new
coverage for approval: the payment double's timer/hold state machine preserves the
selected contract across clock advance and idempotent retries. No full hosted ledger
qualification is claimed.

## 3. Mediation HTTP double

- [ ] 3.1 Add new tooling `src/authority_lane_doubles/mediation.py`: authenticated
      file/append/read/watch, registry-approval scope fixture, per-agreement signed
      sequence/cursors across cases, closed-case refusal and per-write idempotency.
      Use the foundation's mediation models and record-signing fixture.
- [ ] 3.2 Implement authority-owned filing extensions over payment HTTP: per-part
      held/not-held/pending/error results, stable case/part keys, and payout-race
      handling. Read the committed Agreement and derive effects in the authority
      tool, never in the marketplace dispute adapter.
- [ ] 3.3 Implement the two mechanical classes only: sufficient seller self-penalty
      and buyer_end with a verified, deal-bound storefront acknowledgement. Realize
      past ends as stop-now plus reverse. Queue everything else for triage with a
      local notification outbox; accept a lane operator ruling through the same
      application path. Refuse unsupported bond effects until the contract has them.
- [ ] 3.4 Apply effects as the dispute authority with stable IDs/case refs, record
      applied state, resume partial outcomes and lift only this case's refs. Keep
      a delivery end distinct from a discount. Make case discovery/record watch work
      after a party outage without imposing order across authority records.

Verification: foundation section 12.2's mediation client library-integration suite
consumes this double, including two cases, mixed held/not-held results, lost filing
response, closed-before-append and repeated claimant evidence. Deterministic HTTP
first-use drive files seller exceptional_end, acknowledged buyer_end, unacknowledged
buyer triage, an invalid-acknowledgement triage and interrupted effect application;
read signed records through the real client. Candidate new coverage for approval:
mediation's mechanical classifier verifies the acknowledgement binding and rejects
weaker self-penalties; its effect journal resumes without duplicate payment effects.
These are interface simulation results, not live mediation acceptance.

## 4. Lane-only controls and deterministic time

- [ ] 4.1 Add new tooling `src/authority_lane_doubles/controls.py`: explicit lane
      enablement, scoped run reset, injected clocks/barriers, exhaustion, snapshot
      replay/sequence/provenance faults, per-operation refusals and delayed/dropped
      responses including after commit, independent authority outage, key overlap,
      triage and effect pause/resume. Separate record corruption from normal valid
      signing so scenarios can identify the injected fault.
- [ ] 4.2 Keep controls on lane-private networks with no host port, unavailable
      outside the lane profile. Make faults run/transaction/case scoped. Rotation
      controls must not change client trust or patch a committed record key.

Verification: use real HTTP calls and temporary diagnostics to advance notice/hold
races without sleeps and replay an operation after lost acknowledgement. Adapt the
existing lane Compose checks in `scripts/tests/test_lane_compose.py` to assert the
new overlay's isolation with their kept topology assertions. Candidate new coverage
for approval: isolated controls cannot mutate another run and clock barriers expose
all due authority transitions for the scenario's selected instant.

## 5. Wire lanes and prepare repeatable first use

- [ ] 5.1 Add the shared planned root overlay `compose.authority-doubles-lane.yml`.
      Update `Makefile`'s lane image/environment targets and `e2e-tests/Makefile`'s
      three Compose file sets, log and down targets so one image supplies separately
      addressed services per lane and cleanup removes their state. Do not add these
      services to default or hosted stacks.
- [ ] 5.2 Add lane payment/dispute profiles under `e2e-tests/config` and role fixtures
      through existing configuration generation. Wire service identities, fixture
      credentials, seeded accounts and authority advertisements, including accepted
      Dispute/DisputeCredential identity entries where lifecycle is composed. Preserve
      API-credit compatibility without claiming it now services disputes.
- [ ] 5.3 Adapt `e2e-tests/tests/e2e/roles/helpers/payments.py` and existing payment
      scenario setup/reporting for target kind, contract hashes and evidence class;
      add authority readiness checks only where required by the selected scenario.
      Use a missing-setting failure for lane-owned credentials, not a blocked skip.
      Preserve explicit external-target selection without fallback to a double.
- [ ] 5.4 Run the existing bare-metal and credits payment deal surfaces from clean
      committed setup; verify they run rather than skip against the default lane
      target and clean up after both success and an injected failure. Prepare the
      VM lane's same authority setup for the rate changes without claiming their
      future compute scenarios already exist. Capture reproducible commands and
      contract/evidence metadata; stop every owned service after trying it.

Verification levels/targets:
- Unit: `e2e-tests/tests/unit/test_payments_helper.py` and
  `test_payment_compensation.py` for retained setup/cleanup assertions;
  `scripts/tests/test_lane_compose.py` for retained lane topology.
- Library/application integration: actual HTTP clients to both doubles; foundation
  sections 11/12 adapter suites after dependency gates land; no production authority
  internals or new API-credit dispute behavior.
- Smoke: Compose health/readiness and a signed read at each required authority before
  mutating a scenario. A down target reports environment setup, not product evidence.
- System integration: `make -C e2e-tests test-e2e-bare-metal` and
  `make -C e2e-tests test-e2e-apicredits`, preserving existing payment markers and
  mock provisioning. Run `test-e2e-vm` for its changed wiring. Capture consumer
  revision, contract hashes, initial seed/actors, result and cleanup. Later rate
  scenarios belong to `spot-deals-through-arkhai-payments`, not this plan.

## 6. Closeout

Closeout is documentation-only and runs after code review. A code defect returns to
implementation rather than being hidden in closeout edits. Follow
`openspec/README.md#plan-closeout-requirements` in order:

- [ ] 6.1 Confirm comment hygiene with `make check-comment-hygiene`; stop and return
      to implementation for any comment/docstring defect.
- [ ] 6.2 Confirm import placement against this change's diff and focused suites;
      module-level unless a genuine tested cycle or deliberate lazy-load reason
      remains. A needed code edit returns to implementation.
- [ ] 6.3 Check documentation compliance: doubles/evidence belong to test-compatibility,
      external authority contracts to their owning kits and foundation documents;
      no test-control behavior is promoted as a production guarantee.
- [ ] 6.4 Compress completed task notes to final behavior, validation, residual gates
      and promotion destinations; keep material alternatives in design.
- [ ] 6.5 Update Goal 8's current state and gap mapping in
      `docs/development/ROADMAP.md`: lane payment and mediation qualification is
      available; hosted activation remains separately gated. Record the promotion.
- [ ] 6.6 Update this change's row and campaign dependencies in
      `openspec/changes/README.md`; check one owner per double and acyclic prerequisite
      versus consumer gates. Record the promotion and run `make check-change-index`.
- [ ] 6.7 Run `make check-packaging` and
      `make check-architecture-change CHANGE=add-arkhai-payments-lane-double`;
      resolve failures and retain no architecture exception owned by this change.
      Run `make check-agent-skills` if agent instructions were touched.
- [ ] 6.8 Confirm end-to-end pipeline evidence for existing payment deals and changed
      VM wiring, with scenario results and contract classes. Name unavailable
      prerequisites as blockers with their owner and mark gated assertions unrun;
      proposed qualification is not live evidence.
- [ ] 6.9 Promote D1–D7 to `openspec/specs/test-compatibility/architecture.md`,
      `docs/development/TESTING.md` and `e2e-tests/README.md` as the design-promotion
      record specifies; archive synchronizes the normative test-compatibility delta.
      Keep the capability index current. Record no repository-wide architecture
      change because production layers/authorities are unchanged.
- [ ] 6.10 Run `make check-doc-citations CHANGE=add-arkhai-payments-lane-double`,
      resolve every new citation, then `openspec validate add-arkhai-payments-lane-double
      --strict` as the last check before archive. Run the combined `make check-change
      CHANGE=add-arkhai-payments-lane-double` gate too.
- [ ] 6.11 Archive with `openspec archive add-arkhai-payments-lane-double -y` only
      after the above, update the archived index link, and let closeout review read
      the archived change and resulting permanent documents.

## Design promotion record

See design.md's decision-by-destination table. All entries await implementation and
post-code-review promotion; this design reconciliation promotes no current behavior.
