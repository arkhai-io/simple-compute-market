# Tasks — in-lane payment and mediation doubles

Design-stage implementation plan. No runtime implementation is claimed here. Preserve
completed items when this plan is executed. This change owns both executable doubles;
production adapters and their contract/fixture prerequisites remain in
`agreed-evidence-and-early-termination`.

## Dependency gates and first use

- Foundation sections 1–2 supply lifecycle interfaces; 8.1 supplies payments
  schemas/models/vectors, unpublished candidate, installed resource metadata/API
  and the one clock-injected payments fixture engine; 9.1 supplies snapshot framing;
  12.1 supplies mediation contracts, installed resources, mapping/netting vectors,
  models and record-signing fixtures. Confirm each prerequisite before its surface.
  No mediation acknowledgement-verifier gate remains: buyer_end goes to triage;
  only qualifying payee exceptional_end self-penalties are mechanical.
  Foundation 2.4 supplies the buyer-usable acknowledgement model/verifier, 13.1 the
  storefront signer, and 7.5 consumes it. Bare-metal porting waits for 7.4, 13.x/15.x.
- Foundation 7.4/11.1/12.2/14.2 and spot kit tests use in-process contract fakes
  exercising the same kit vectors (payments uses the shared engine directly); they do not depend on this tool (D-H).
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
new double's own timer/hold, triage/operator-ruling, effect-resume and control-isolation
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
      status and hashes in SOURCE. Consume the kit-installed resource/model API
      from built wheels without sibling checkouts, not checkout-relative schema
      paths (03 F2 / 04 F11). Keep one canonical resource source. Select the same
      candidate as consumer publication/acceptance/derivation through the explicit
      lane-only proposed declaration; refuse missing prerequisites by name.
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
      installed metadata hashes in both published and proposed readiness; fail
      setup by name on mismatch. Report each authority's current wall-clock instant.

Verification: static schema validation and existing kit vector targets
`make -C kit/arkhai-payments check-vectors` and the foundation's mediation vector
suite when available; shared receipt/snapshot signing reproduces the pinned vectors.
The tool's library-integration suite uses real HTTP clients with injected transports
to read both services' initial state; kit suites keep their in-process fakes.
Packaging: new tool build/reinit/typecheck targets, `make check-packaging`.
Missing producer vectors are recorded as published-qualification gates, not passing
conformance evidence.

## 2. Payments HTTP double

- [ ] 2.1 Implement approval, exact Agreement attachments, receipts, snapshots,
      event reads and per-account authorization/idempotency in new tooling
      `src/authority_lane_doubles/payments.py`, reusing kit models and signers.
      Wrap the foundation 8.1 kit fixture engine, not another ledger. Implement only
      the chosen contract, including explicit refusals for unsupported operations.
      Normal responses never emit live-mode records; only the labelled 4.1
      record-corruption fault may do so.
- [ ] 2.2 Add the target revision's per-part start, stop with notice and pending-stop
      maturity, absolute end, funding exhaustion and funded-through observations.
      Use pinned rate arithmetic from start, including mixed once/rate mandates
      where supported. For contracts expressing them, implement stopper partialPeriod,
      chosen dispute stops with explicit event treatment, end.partialPeriod without
      rounding, period-end/stop earning and {for} holds from earning. Otherwise
      follow the selected publication's actual semantics; refuse unsupported inputs,
      never guess charged behavior or implement consumer acceptance policy here.
      Setup maturity uses only the selected contract's immutable activation anchor.
      Require explicit authorizing stop entries: seller entries exist only for
      entitlements, such as spot notice. Use mediation's PT0S/chosen entry for the
      mechanical self-penalty, not seller payment-adapter operations. Add no seller
      restitution entry, implicit favourable-stop rule, waiver, early release or
      several-entries-per-account dependency. End_delivery grants the storefront no
      buyer billing authority; buyer half journals/retries its own stop under the
      same key during outage and billing runs until it lands. On-demand non-preemption
      is enforced by buyer remedy over held money/bond, not the mandate. Never
      conflate approval with rate start or observe compute activation inside the authority.
- [ ] 2.3 Add held-money partial reverse before/after stop, afterStop payout timing,
      independent extend refs and lift, caps and contract refusal codes. Preserve
      idempotent results across lost responses. Share one state engine between HTTP
      and controls and the kit's in-process fake: import the shared kit engine,
      exercise the same vectors and do not maintain another rate simulator.

Verification: keep existing kit `test_client.py`, `test_receipt_fixture.py` and
`test_receipts.py` on kit-owned contract fakes/vectors. In the new tool's
`tests/test_payments.py`, drive real clients through HTTP transports and prove
entry-based start/stop authorization (including refusal without an entry), mediation
self-penalty effects through its own entry, buyer-owned stop/retry and unchanged notice, partialPeriod outcomes, notice firing without a storefront,
setup maturity, overlapping case holds, reversal before/after stop and response-loss
replay. Required unit state-machine coverage uses an injected clock for timer/hold
transitions and idempotent retries; required library integration covers signed HTTP
records from the same state engine (02 F10). Verify built-wheel resource access
without sibling source trees and fake/HTTP engine parity (03 F2 / 04 F3). No hosted ledger qualification is claimed.

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
      production-party client. Take the exact Agreement from the case, verify its
      hash against the committed mandate, and derive dispute effects in the tool;
      do not require an attachment or trust marketplace-computed remedies (E-F).
- [ ] 3.3 Restore exceptional_end to dispute adapter intents and mediation request
      vocabulary/published mapping through the foundation producer gate. Accept a
      journaled seller-half dispute filing only, never seller direct stop/reverse.
      Never future-date; pre-start failures journal immediately and file at Agreement
      start. Mechanically rule only a payee-filed request at least as strong as the
      standard self-penalty: through mediation's PT0S/chosen entry stop rate parts now
      returned (always returned on-demand), reverse earnings since at, reverse unserved
      once share by time, setup all before activation and none after, full bond once
      supported. Unsupported bond effects refuse, not fabricated completion. Queue
      buyer_end and all other nonqualifying claims for visible triage/outbox regardless
      of acknowledgements. Realize buyer_end as payer stop submitted at at with notice
      and committed partialPeriod, leaving once parts untouched. Present stop plus
      net held-money adjustment realizes a past remedy without backdating. All stop
      rulings, mechanical or operator, state partialPeriod explicitly.
- [ ] 3.4 Apply effects as the dispute authority with stable IDs/case refs, record
      applied state, resume partial outcomes and lift only this case's refs. Keep
      a delivery end distinct from a discount. Make case discovery/record watch work
      after a party outage without imposing order across authority records.
- [ ] 3.5 Implement revision-bound case references and agreement-wide remedy netting
      from the pinned foundation mapping/vectors (03 F1 / 04 F9). Serialize remedy
      application per agreement, resolve uncertain prior effects, net confirmed
      authority reversals and awards across revised exceptional_end and operator
      cases, and apply only the additional remedy.
      Preserve prior provenance across open/closed cases, partial application and
      append/close races. Unsupported netting remains explicit repair/triage.

Verification: foundation 12.2 uses its kit contract fake. The tool's required
`tests/test_mediation.py` library integration drives real clients for two cases,
mixed held/not-held, lost filing response, closed-before-append, empty record and
repeated evidence. Required `tests/test_triage_rulings.py` coverage proves only
qualifying payee exceptional_end is mechanical, weaker/non-payee requests do not get
that rule, buyer_end remains triaged regardless of acknowledgement, and all stop
rulings state partialPeriod. Cover on-demand returned, setup before/after activation,
pre-start/future-time filing boundaries, no seller direct effects, preserved buyer
notice and optional signed end_delivery evidence.
HTTP integration files cases with the exact Agreement and no attachment, verifies
hash mismatch refusal, and applies operator rulings through the authority path. Required `tests/test_effect_recovery.py` interrupts effect application
and proves resume without duplicates or another case's lift (02 F10), plus a
40-then-total-60 revised remedy applies only 20, including uncertain/partial prior
effects, closed prior cases and races (03 F1 / 04 F9).
These are interface simulation results, not live mediation acceptance.

## 4. Lane-only controls and deterministic time

- [ ] 4.1 Add new tooling `src/authority_lane_doubles/controls.py`: explicit lane
      enablement, scoped run reset, wall-time due-work barriers, exhaustion, snapshot
      replay/sequence/provenance faults, per-operation refusals and delayed/dropped
      responses including after commit, independent authority outage, key overlap,
      triage and effect pause/resume, payer funding/top-up and a labelled signed
      livemode:true fault. Rotation retains old receipt bytes inside a current-key
      signed snapshot with the selected contract's re-anchoring attestation; missing
      vectors keep the scenario proposed-only (04 F9). Separate corruption from valid
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
      Process due work on reads/writes and an internal wall-time scheduler without
      barriers; barriers only force/report progress. Expose each authority's current
      instant in status and barriers for skew checks (04 F10).

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
      trust through SSL_CERT_FILE only in lane participants, using a bundle of the
      lane CA plus default public roots, not a replacement lane-CA-only trust store. No host control port.
- [ ] 5.2 Add lane payment/dispute profiles under `e2e-tests/config` and role fixtures
      through existing configuration generation. Wire service identities, fixture
      credentials, seeded accounts and authority advertisements, including accepted
      Dispute entries in every hosted role, including API-credit publication and
      selection, and DisputeCredential bindings where lifecycle filing is composed.
      Admit draft mediation only under an explicit lane profile/proposed declaration;
      an Agreement naming it makes the run proposed even without a case (04 F7).
      Preserve API-credit compatibility without claiming it now services disputes. Use
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
      evidence-class definition; reject consumer hash mismatch in either mode.
      Replace the helper's lane-double readiness skip with a named setup failure;
      blocked/unrun is only for the explicitly selected external-target case (04 F1).
      Declare the typed tooling-control-client distribution in e2e-tests/pyproject.toml
      and refresh its lock so installed lane consumers can import it (04 F13).
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
- [ ] 5.5 Port the existing
      `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_payment_deal.py`
      and helper to foundation's post-approval commit, buyer-half re-drive, seller
      reverse and end_delivery flow (04 F2). Retain original-run identity and all
      bounded cleanup/race assertions. Remove retired payment-level dispute_authority
      serialization in favor of role Dispute entries. Foundation 7.4, 13.x/15.x gate
      this port; this change is its sole scenario owner. API credits keeps its
      separately owned settle path.

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
- System integration (after 5.5's port): `make -C e2e-tests test-e2e-bare-metal` and
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
