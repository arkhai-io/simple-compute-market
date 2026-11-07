## 1. Qualify the bare-metal payment deal (PR #275)

The numbering of sections 1 and 2 was added when the change was brought into the current workflow; the task text is as first written.

- [x] 1.1 Add the three-call bare-metal payment scenario and module-owned supply/cleanup.
- [x] 1.2 Register/include its marker without removing the canonical mock deal.
- [x] 1.3 Document current scenario contract in test-compatibility, testing map and E2E guide.
- [x] 1.4 Collect the exact three calls and run relevant scenario/CLI typing.
- [x] 1.5 Run the connected scenario against a ready configured payments target.

At `430213a40`, the configured payment scenario passed all three calls in 47.9 seconds with mock provisioning: receipt-gated access/result, original-run settlement and fulfillment replay, seller refund, separate reclaim and whole-host capacity return. The initial connected attempt exposed run completion treating opaque dictionary provision terms as a model; completion now uses the negotiation outcome's existing serializer. Command interfaces and settlement design are unchanged.

Exact collection, focused scenario typing, comment hygiene, scoped citations and packaging passed. CLI typing additionally required retaining already-validated seller pins in callbacks and asserting delivery's existing non-null sink boundary.

Correction (01 F4): 1.3 wrote the scenario contract into `openspec/specs/test-compatibility/spec.md` directly; it is reverted to `dev`'s text and carried by this change's delta, to be merged by the archive at closeout.

## 2. First closeout

- [x] 2.1 Comment hygiene: `make check-comment-hygiene`.
- [x] 2.2 Import placement: all added imports are module-level.
- [x] 2.3 Documentation compliance: decisions promoted to owning permanent documents.
- [x] 2.4 Narrative compression: retain final contract and check outcomes only.
- [x] 2.5 Roadmap currency: no directional-goal or production-behavior change.
- [x] 2.6 Campaign index currency: focused candidate qualification row added.
- [x] 2.7 Documentation citations: `make check-doc-citations CHANGE=qualify-bare-metal-payment-deal`.
- [x] 2.8 Packaging: `make check-packaging`.
- [x] 2.9 End-to-end pipeline evidence: configured three-call scenario passed (3 passed, 0 skipped); public CI without payments remains explicitly blocked.
- [x] 2.10 Promotion: design record names guide, testing map and permanent spec.

Correction (01 F1, 01 F4): this closeout predates the current workflow and does not stand. Its index row used a status outside the legend (2.6), the spec was promoted by hand before review (2.3, 2.10), and it had no archival, architecture-change, or strict-validation step. The change is closed out again by the closeout section planning appends.

## 3. Merge the development branch

- [x] 3.1 Merge `dev`, which carries #268–#272 as squash commits.

Landed in `ef8804b93`. Conflicts came from this branch carrying #268–#272's original commits; every file the branch's own commits do not touch takes `dev`'s version, and the eleven files they do touch carry exactly their own edits on `dev`'s. Comment hygiene and `make check-packaging` passed; the e2e unit suite (53) and bare-metal buyer suite (13) passed; the payment scenario collected its three calls against `dev`'s payments helper.

## 4. Pin the bare-metal buyer's completion of an agreed negotiation

Replanned against the reviewed design: the design triage's tasks 4.1–4.4 are split by layer into sections 4–6. Delivers D5's regression proof in the bare-metal buyer. Touches `domains/bare_metal/buyer/tests/`.

- [x] 4.1 Unit-test `market bare-metal buy` completing an agreed negotiation whose accepted provision terms are a dictionary, as the bare-metal buyer always receives them: drive the command through Typer's runner with its configuration, identity, registry, negotiation, and settlement collaborators replaced at module level (the command takes no injected collaborators), a real `RunLog` in a temporary directory, and assert the run's `run_ended` event carries the terms (D5; 01 F5).
- [x] 4.2 The same for `market bare-metal request-introduction`, whose agreed path also writes `run_ended` with the accepted terms (D5; 01 F5).

Verification: bare-metal buyer suite (unit; collaborators replaced at the command's module), each test failing if its command calls `.model_dump()` on the terms; `make test`. No dependency changes. End-to-end: no pipeline scenario drives either command to an agreement; `e2e_bare_metal_payment_deal` drives `buy` once configured with a payments target.

Done. `domains/bare_metal/buyer/tests/test_cli_completion.py` (unit; each command's collaborators replaced on `arkhai_bare_metal_buyer.cli`, the run log real): an agreed `buy` and an agreed `request-introduction` with dictionary accepted terms exit 0 and write `run_ended` carrying the terms. The module-level replacement departs from `TESTING.md`'s mocking convention; `design.md#evidence-boundaries` records why. Evidence: bare-metal buyer suite passed, 15; restoring `.model_dump()` in either command fails its test. End-to-end: no pipeline scenario drives either command to an agreement.

## 5. Compensate a failed payment deal and clean up independently

Delivers D6 and D7, implementing the `test-compatibility` delta's scenario "A stage fails after the payment is approved". Touches `e2e-tests/tests/e2e/roles/helpers/` (a new cleanup helper), `e2e-tests/tests/unit/`, and `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_payment_deal.py`.

- [x] 5.1 Add a cleanup helper to `e2e-tests/tests/e2e/roles/helpers/` that attempts each named step in order, recording a failure without stopping the later steps, then runs each always-run step the same way, and raises one error naming every step that failed (D7; 01 F3).
- [x] 5.2 Unit-test 5.1: a failing step does not stop later steps or the always-run steps; every failure is reported by name; a clean run raises nothing (D7).
- [x] 5.3 In the payment scenario, record the purchase's negotiation and transaction from the buy command's run events as soon as the command returns, before asserting its success, so a command that failed after approval still leaves them recorded (D6; 01 F2).
- [x] 5.4 Rebuild the supply fixture's cleanup on 5.1: when a transaction is recorded and the deal's teardown stage has not completed, refund it through the pinned seller, then tear the purchase's fulfillment down by its negotiation, waiting for capacity release; then disarm gates, drain, and remove the pool override, mock rules included; with the storefront's lifecycle loops, fulfillment convergence, and the lease watchdog resumed as always-run steps, by `docs/development/TESTING.md`'s finaliser rule (D6, D7; 01 F2, 01 F3).

Verification: e2e unit suite (`make -C e2e-tests test-unit`; unit) for 5.1; the payment scenario collects its three calls against the lane's settings; `make test`; comment hygiene. End-to-end: `e2e_bare_metal_payment_deal` exercises 5.3 and 5.4 only against a configured payments target; the pipeline configures none, so it skips there and is no evidence for this section, and its failure path is not exercised by any run.

Done, as revised by the two fix rounds below. `e2e-tests/tests/e2e/roles/helpers/cleanup.py`'s `run_cleanup` attempts every step, records each failure (a `pytest.fail` included), runs the always-run steps in a `finally`, and raises `CleanupFailed` naming every failed step (5.1; 5.2 in `e2e-tests/tests/unit/test_cleanup_helper.py`). The supply fixture cleans up through it (5.4): the purchase's compensation, each mock rule, draining, the pool override; then, always, the lease watchdog, fulfillment convergence, and the storefront's loops. Plan divergence (5.3): the purchase's identifiers are read from the buyer's run log when cleanup runs, not recorded when the command returns, since a timed-out command never returns (D6). Evidence: e2e unit suite passed; the mutations are in `design.md#evidence-boundaries`. End-to-end: `e2e_bare_metal_payment_deal` skips without a payments target, before its supply fixture, so no run exercises the cleanup.

## 6. Document the cleanup contract

Delivers D6 and D7's operator-facing description. Touches `docs/development/TESTING.md` and `e2e-tests/README.md`.

- [x] 6.1 State in `docs/development/TESTING.md`'s bare-metal lane entry and `e2e-tests/README.md`'s "Bare-metal payment deal" that a failed run refunds and tears down any deal it left outstanding, and that every cleanup step runs with the held loops resumed last (D6, D7; 01 F2, 01 F3).

Verification: `make check-doc-citations CHANGE=qualify-bare-metal-payment-deal`; `make check-change CHANGE=qualify-bare-metal-payment-deal`. End-to-end: none.

Done. `docs/development/TESTING.md`'s bare-metal lane entry and `e2e-tests/README.md`'s "Bare-metal payment deal" describe the cleanup as D6 and D7 state it, corrected with each later round (6.1). Evidence: `make check-doc-citations` and `make check-change` passed; the prose was read against the code by fresh-context checks. End-to-end: none.

**Round 1 fixes** (`reviews/03-implementation-external.triage.md`, against `9335dd9b5`; the fix commit validated in `reviews/06-validation.md`):

- 03 F1: the refund retries for 60 seconds on a 409, a 503, or an unreachable storefront, and a refund that still fails is reported as `UnresolvedPayment` with the negotiation and transaction.
- 03 F2: each mock rule is deleted by its own cleanup step, so a real failure is reported.
- 03 F3: the compensation decisions are in `e2e-tests/tests/e2e/roles/helpers/payment_compensation.py`, with the seller, clock, and sleep injected, unit-tested in `e2e-tests/tests/unit/test_payment_compensation.py`.
- 03 F4: `e2e-tests/pyproject.toml` declares `arkhai-core-buyer`; the e2e-tests lock is refreshed.

Evidence: e2e unit suite passed, 77; `make check-packaging` and `make check-change` passed; `make -k test` passed but for the two known environmental gaps.

**Pre-closeout fixes** (`reviews/07-pre-closeout-external.triage.md`, against `eafef0625`; the fix commit validated in `reviews/08-validation.md`):

- 07 F1: the release step reads the fulfillment after the refund, and that read alone decides (D6).
- 07 F2 (decision A): the unverified-payment 409 detail stays a documented stand-in for a structured reason, pinned by two service-integration tests in `domains/bare_metal/storefront/tests/integration/test_payment_settlement_client.py`; the reason code is unowned work in `openspec/changes/README.md`.
- 07 F3: a host whose fulfillment cleanup cannot read or tear down is reported as a failed step, not promised released, in the delta, D6, `TESTING.md`, and the README.

Evidence: e2e unit suite passed, 80; the bare-metal storefront's payment settlement tests passed, 15; `make check-change` passed; `make -k test` passed but for the two known environmental gaps.

## 7. Closeout

The closeout task of `openspec/README.md#plan-closeout-requirements`, in its order. It edits documentation only; a part needing code returns the change to implementation.

- [x] 7.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read every comment and docstring in the change's diff from `dev` for any that narrate the review or migration that introduced them. Do not edit code here. Done: `make check-comment-hygiene` passed; the comments and docstrings in the change's diff from `dev` (`git diff 95b262391 HEAD`) state invariants and reasons, and none names a change, task, review, or history.
- [x] 7.2 **Import placement — confirm.** Check the imports the change added for any still local without a recorded reason. Done: the change adds no function-local import.
- [x] 7.3 **Documentation compliance.** Re-check D1–D8 against `openspec/README.md`'s placement rules, and `TESTING.md` and the e2e README against the scenario and its cleanup. Done: D1–D4, D6, and D7 describe the scenario's behaviour, normative in the delta and described in `TESTING.md` and the e2e README; D5 is code with its tests; D8 is the delta's own placement; the evidence boundaries stay in this design. `TESTING.md` and the README were read against the cleanup by the fresh-context checks of the two fix rounds, and match it.
- [x] 7.4 **Narrative compression.** Compress completed-task notes in sections 1–6 to final behaviour, material evidence, deferrals, and destinations, moving durable rationale into `design.md` first. Done: sections 4–6 and the two fix rounds' notes compressed to behaviour, evidence, and destinations. The mutation list, the storefront-serialisation reasoning, and the absent e2e type checker moved to `design.md#evidence-boundaries`; the one-buy-run assumption to its risks; the e2e package's inherited transitive imports to `design.md#notes-for-later-work`. Sections 1–3 keep their notes; task text and correction notes are unchanged.
- [x] 7.5 **Roadmap currency.** Confirm that `docs/development/ROADMAP.md`'s Goal 4 live-qualification row and `#payment-qualification-boundaries` stay true — mock access is not authenticated access, and live qualification stays with the payments service — and record the disposition. Done: no roadmap edit. Goal 4's live-qualification row and `#payment-qualification-boundaries` stay true: the scenario proves mock composition against a configured payments target, not authenticated bare-metal access, and live qualification stays with the payments service.
- [x] 7.6 **Campaign index currency.** Set this change's row under "Roadmap goal — Make the settlement mechanism a composed choice" in `openspec/changes/README.md` to `in closeout`, notes describing the archived state, then point it at the archive (7.11). Leave other rows' `Depends on` alone. Done: the row is `in closeout` under "Roadmap goal — Make the settlement mechanism a composed choice", its notes describing the closing state; it points at the archive in 7.11. The unowned item "Unowned work found by `qualify-bare-metal-payment-deal`" records the status route's structured reason. `unbacked-bare-metal-listings`' note that it converts this scenario's direct loop pauses stands. Other rows' `Depends on` unchanged; `make check-change-index` passed.
- [x] 7.7 **Packaging.** Run `make check-packaging`, then `make check-architecture-change CHANGE=qualify-bare-metal-payment-deal`. The change touches no `.agents/`, `.claude/`, or `.codex/` file, so `make check-agent-skills` is not owed. Done: `make check-packaging` passed; `make check-architecture-change CHANGE=qualify-bare-metal-payment-deal` passed, the change owning no architecture row.
- [x] 7.8 **End-to-end pipeline.** Record the run the latest passing validation names and its result as regression evidence that the lanes deploy and run. `e2e_bare_metal_payment_deal` skips there for want of a payments target, so record it as skipped, not passed; the scenario's evidence is section 1's configured run. Done: `reviews/08-validation.md` names pipeline run 39797271150 at `da0f7c444`, the pre-closeout fix commit: success — e2e-vm 134 passed; e2e-bare-metal 51 passed, 3 skipped; e2e-apicredits 1 passed, 3 skipped — with the owner's local part passed and the Helm part waived for that commit, after passing at `eafef0625` (`reviews/06-validation.md`). `HEAD` differs from `da0f7c444` in documentation and the index only. `e2e_bare_metal_payment_deal`'s three calls skipped there for want of a payments target, so no pipeline scenario exercises the change; its evidence is section 1's configured run and the unit and service-integration tests.
- [x] 7.9 **Promotion.** The `test-compatibility` requirement is written by the archive in 7.11 from this change's delta; `TESTING.md` and the e2e README are written in section 6. Write a design-promotion record in `design.md` naming, for D1–D8, the delta requirement, permanent document, or code-only disposition of each. Done: no permanent document beyond those is owed — `TESTING.md` and the e2e README were written in section 6 and kept current by both fix rounds. The design-promotion record names D1–D8's locations, the unowned structured reason, and the roadmap and index dispositions; the `test-compatibility` requirement is the archive's.
- [x] 7.10 **Documentation citations.** Run `make check-doc-citations CHANGE=qualify-bare-metal-payment-deal` and resolve every match, then `make check-change CHANGE=qualify-bare-metal-payment-deal`, which runs the pinned `@fission-ai/openspec@1.14.0` strict validation. Done: `make check-doc-citations` passed, every cited path resolving; `make check-change` passed, its pinned strict validation of the delta included.
- [x] 7.11 **Archival.** `bunx @fission-ai/openspec@1.14.0 archive qualify-bare-metal-payment-deal -y`, merging the `test-compatibility` delta into `openspec/specs/` (the permanent spec does not carry it, so no `--skip-specs`), then point the index row at the archive directory. Done: archived without `--skip-specs`, the permanent spec not carrying the requirement; the merged `test-compatibility` diff reads back as the delta states it, and the index row points at the archive.
