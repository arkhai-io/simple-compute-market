# Tasks — in-lane payment and mediation doubles

Design-stage implementation plan. No runtime implementation is claimed here. Preserve
completed items when this plan is executed. This change owns both executable doubles;
production adapters and their contract/fixture prerequisites remain in
`agreed-evidence-and-early-termination`.

## Dependency gates and first use

- Foundation sections 1–2 supply lifecycle interfaces; 8.1 supplies payments
  schemas/models/vectors; 9.1 supplies the shared snapshot fixture/frame seam;
  12.1 supplies the published/draft mediation schema, models and
  record-signing fixtures before construction. Gate buyer_end on the shared
  acknowledgement signing/verification primitive owned by 13.1 and consumed by 7.5,
  with the 2.4 response model. Confirm each prerequisite before its HTTP surface.
- Foundation 7.4/11.1/12.2/14.2 and spot kit tests use in-process contract fakes
  generated from the same kit vectors; they do not depend on this tool (D-H).
  The tool's tests and lane/system-integration runs consume its HTTP services.
  Land foundation prerequisites first, then this change, then lane consumers;
  foundation's remaining rounds can finish independently with contract fakes.
  Missing producer vectors permits pinned proposed-only work, not published claims.
- `spot-deals-through-arkhai-payments` owns production rate arithmetic/adapters and
  compute scenarios. `converge-ongoing-compute-leases` consumes the controls for end
  service/rate servicing. `activate-per-period-compute-servicing` owns later hosted
  capability readiness and live qualification. Only their stated contract/deployment gates apply.
- First use is the existing bare-metal and credits payment deals, through their lane
  targets, mock provisioning, seeded development payer and seller accounts and pinned
  fixture authority identities. No live credential or physical hardware is required.
  Later compute scenarios consume the same setup rather than creating another double.

New paths below are planned deliverables, not citations to existing implementation.
Within the new tooling root `tools/authority-lane-doubles`, filenames are relative to
that root. Test work adapts existing kept suites first. The owner authorizes the
new double's own timer/hold, mechanical-classifier, effect-resume and control-isolation
coverage below (02 F10); it is required for implementation, not a deferred approval.
No unrelated consumer acceptance suite is authorized by this design triage.

## 1. Package, contract provenance and signed frames

- [ ] 1.1 Confirm D7's remaining foundation coordination edits and prerequisite
      extracts (02 F3/F11), rather than requesting already-applied ownership edits.
      Record the exact published/draft schema and vector hashes for each
      service. Refuse published readiness for any required unpublished surface; pin
      proposed candidates and a difference manifest without reintroducing dropped
      primitives. Files: new tooling contract selectors/manifests under
      `src/authority_lane_doubles/contracts/` selectors and difference manifests;
      schemas/candidate bytes/vectors stay solely in the owning kit with publication
      status and hashes in SOURCE. Consume those exact bytes (02 F5).
- [ ] 1.2 Add the tooling `pyproject.toml`, `uv.lock`, `Makefile`, `Dockerfile` and
      `src/authority_lane_doubles/` package with separate payments and mediation
      entry points. Declare every imported kit distribution. Reuse kit fixture APIs;
      coordinate absent frame APIs upstream rather than duplicating framing. Build
      from `.dist` and the committed lock via the existing packaging helpers.
- [ ] 1.3 Add deterministic lane-only identities, accounts, initial balances and
      authority advertisement fixtures to the tool. Label all credential material
      public development-only, never for a public network. Keep production defaults
      empty. Expose health/status with contract metadata outside signed wire frames;
      before explicit mode/seed selection report not-ready. Compare required consumer
      SOURCE hashes in published readiness and fail setup by name on mismatch.

Verification: static schema validation and existing kit vector targets
`make -C kit/arkhai-payments check-vectors` and the foundation's mediation vector
suite when available; shared receipt/snapshot signing reproduces the pinned vectors.
The tool's library-integration suite uses real HTTP clients with injected transports
to read both services' initial state; kit suites keep their vector-generated fakes.
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
      mandates where supported. Apply each stopper's partialPeriod in the authority,
      one notice from notice_seconds, boundary-aligned exhaustion and absolute ends
      carrying their own partialPeriod without term rounding. The dispute authority
      entry uses chosen and its event supplies treatment. Earn periods at period end
      or part stop; anchor {for} payouts to that earning instant, not period start. Until expressible, fail closed on unsupported values and use
      charged for both spot parties. Setup ends at activation with its window,
      returning all only when undelivered under self-penalty (D-A/D-B/D-D).
      Do not conflate transaction approval with start.
      Keep no payee stop on on-demand mandates.
- [ ] 2.3 Add held-money partial reverse before/after stop, afterStop payout timing,
      independent extend refs and lift, caps and contract refusal codes. Preserve
      idempotent results across lost responses. Share one state engine between HTTP
      and controls; kit contract fakes follow shared vectors, not an independent
      hand-maintained rate simulator.

Verification: keep existing kit `test_client.py`, `test_receipt_fixture.py` and
`test_receipts.py` on kit-owned contract fakes/vectors. In the new tool's
`tests/test_payments.py`, drive real clients through HTTP transports and prove
start/stop authorization, partialPeriod outcomes, notice firing without a storefront,
setup maturity, overlapping case holds, reversal before/after stop and response-loss
replay. Required unit state-machine coverage uses an injected clock for timer/hold
transitions and idempotent retries; required library integration covers signed HTTP
records from the same state engine (02 F10). No hosted ledger qualification is claimed.

## 3. Mediation HTTP double

- [ ] 3.1 Add new tooling `src/authority_lane_doubles/mediation.py`: authenticated
      file/append/read/watch, registry-approval scope fixture, per-agreement signed
      sequence/cursors across cases, closed-case refusal and per-write idempotency.
      Use the foundation's mediation models and record-signing fixture. Known,
      authorized agreements with no cases read as a signed empty record at cursor
      zero; unknown agreements/readers receive named refusals.
- [ ] 3.2 Implement authority-owned filing extensions over payment HTTP: per-part
      held/not-held/pending/error results, stable case/part keys, and payout-race
      handling. Add `src/authority_lane_doubles/authority_payments_client.py` using
      kit-generated models for authority HTTP calls (02 F14), not an invented
      production-party client. Read the committed Agreement and derive effects in
      the authority tool, never in the marketplace dispute adapter.
- [ ] 3.3 Implement the two mechanical classes only: sufficient seller self-penalty
      and buyer_end with a verified, deal-bound storefront acknowledgement. Realize
      past ends as stop-now plus reverse. Queue everything else for triage with a
      local notification outbox; accept a lane operator ruling through the same
      application path. Refuse unsupported bond effects until the contract has them.
- [ ] 3.4 Apply effects as the dispute authority with stable IDs/case refs, record
      applied state, resume partial outcomes and lift only this case's refs. Keep
      a delivery end distinct from a discount. Make case discovery/record watch work
      after a party outage without imposing order across authority records.

Verification: foundation 12.2 uses its kit contract fake. The tool's required
`tests/test_mediation.py` library integration drives real clients for two cases,
mixed held/not-held, lost filing response, closed-before-append, empty record and
repeated evidence. Required `tests/test_mechanical_rulings.py` unit coverage proves
self-penalty sufficiency and acknowledgement signature/deal/time binding; HTTP
integration files seller exceptional_end, acknowledged buyer_end and absent/invalid
ack triage. Required `tests/test_effect_recovery.py` interrupts effect application
and proves resume without duplicates or another case's lift (02 F10).
These are interface simulation results, not live mediation acceptance.

## 4. Lane-only controls and deterministic time

- [ ] 4.1 Add new tooling `src/authority_lane_doubles/controls.py`: explicit lane
      enablement, scoped run reset, wall-time due-work barriers, exhaustion, snapshot
      replay/sequence/provenance faults, per-operation refusals and delayed/dropped
      responses including after commit, independent authority outage, key overlap,
      triage and effect pause/resume. Separate record corruption from normal valid
      signing so scenarios can identify the injected fault.
- [ ] 4.2 Keep controls on lane-private networks with no host port, unavailable
      outside the lane profile. Make faults run/transaction/case scoped. Rotation
      controls must not change client trust or patch a committed record key.
- [ ] 4.3 Add tooling-owned versioned `control_contracts.py` models/route contract,
      typed `control_client.py` and isolated HTTP `harness.py` for this tool's suite.
      Explicit initialization supplies seed/modes; ordinary kit tests do not use
      the harness. Refuse unsupported versions, unknown references and omitted/empty
      mutation target sets without creating scope. Reset names only its owned run.
      Barrier results expose per-authority watermarks, pending work and blocked
      dependencies, never claim completion while effects are blocked (01 F2/02 F12).
      Use wall time and short windows in lanes; injectable time is test-only (02 F4).

Verification: required `tests/test_controls.py` unit/library-integration coverage
uses the typed client to prove scope/version refusals, deterministic initialization,
teardown, lost-response replay and truthful blocked barriers. Inject time only in
the isolated tool state-machine suite. Lane calls drain due work against wall time,
with bounded observable progress rather than sleeps or a fictitious lane clock.
Adapt existing `scripts/tests/test_lane_compose.py` assertions for private controls
and isolated stores. A barrier must not mutate another run (02 F10).

## 5. Wire lanes and prepare repeatable first use

- [ ] 5.1 Add the shared planned root overlay `compose.authority-doubles-lane.yml`.
      Update `Makefile`'s lane image/environment targets and `e2e-tests/Makefile`'s
      three Compose file sets, log and down targets so one image supplies separately
      addressed services per lane and cleanup removes their state. Do not add these
      services to default or hosted stacks. Provide HTTPS origins/certificates with
      Compose-service SANs and a lane-only public development CA; explicitly mount
      trust through SSL_CERT_FILE only in lane participants. No host control port.
- [ ] 5.2 Add lane payment/dispute profiles under `e2e-tests/config` and role fixtures
      through existing configuration generation. Wire service identities, fixture
      credentials, seeded accounts and authority advertisements, including accepted
      Dispute/DisputeCredential identity entries where lifecycle is composed. Preserve
      API-credit compatibility without claiming it now services disputes. Use
      fixture bearer credentials through api_key_env, development_auth=false and
      livemode=false; preserve existing non-loopback HTTPS and auth checks. Add a
      composition guard in role config loaders, payments `settlement_config.py` and
      planned mediation config, refusing lane settings/identities outside the explicit
      lane profile. This is a configuration guard, not relaxed client validation.
      Export the fixture SERVICE_IDENTITY for spot's test-only proposed declaration
      binding; never infer trust from a private status route (02 F2/F8).
- [ ] 5.3 Adapt `e2e-tests/tests/e2e/roles/helpers/payments.py` and existing payment
      scenario setup/reporting for target kind, contract hashes and evidence class;
      add authority readiness checks only where required by the selected scenario.
      Use a missing-setting failure for lane-owned credentials, not a blocked skip.
      Preserve explicit external-target selection without fallback to a double.
      Apply the foundation's target-naming/readiness rule and this change's single
      evidence-class definition; reject published-mode consumer hash mismatch.
      Pass explicit lane-CA SSL contexts to trust_env=false readiness probes, and
      supply service-name NO_PROXY for real clients that retain trust_env. Prove
      both readiness and signed requests succeed without disabling verification.
- [ ] 5.4 Run the existing bare-metal and credits payment deal surfaces from clean
      committed setup; verify they run rather than skip against the default lane
      target and clean up after both success and an injected failure. Prepare the
      VM lane's same authority setup for the rate changes, claiming only service
      health/readiness here, not a VM payment scenario (02 F15). First verify real
      config construction and a signed client request between containers over TLS
      with fixture bearer auth; prove production rejects the lane tuple (02 F2).
      Capture reproducible commands and
      contract/evidence metadata; stop every owned service after trying it.

Verification levels/targets:
- Unit: `e2e-tests/tests/unit/test_payments_helper.py` and
  `test_payment_compensation.py` for retained setup/cleanup assertions;
  `scripts/tests/test_lane_compose.py` for retained lane topology.
- Library/application integration: actual HTTP clients to both doubles in the
  tool-owned suites after prerequisite gates land; foundation/spot adapter
  suites use their own contract fakes. No production authority
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
      VM evidence in this change is health/readiness only;
      proposed qualification is not live evidence.
- [ ] 6.9 Promote D1–D7 to `openspec/specs/test-compatibility/architecture.md`,
      `docs/development/TESTING.md` and `e2e-tests/README.md` as the design-promotion
      record specifies; replace TESTING.md's blank-target pipeline description with
      lane-default behavior and retained explicit external-target gating. Archive
      synchronizes the normative test-compatibility delta.
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
