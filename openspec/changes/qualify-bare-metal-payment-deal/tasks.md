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

Done. `domains/bare_metal/buyer/tests/test_cli_completion.py` (unit): each command is driven through Typer's runner with its configuration, identity, registry, and negotiation replaced on `arkhai_bare_metal_buyer.cli` — and, for `buy`, its payment stage, approval, and settlement transport — as `test_buyer_composition.py` already does for the introduction context; the run log is real, under a temporary `XDG_STATE_HOME`. Replacing module-level names departs from `docs/development/TESTING.md`'s unit-test mocking convention; the commands take no injected collaborators, and making them injectable would restructure the bare-metal CLI beyond this change, so the departure is recorded in `design.md#evidence-boundaries`. An agreed `buy` and an agreed `request-introduction`, each with dictionary accepted terms, exit 0 and write `run_ended` carrying the terms as they arrived (4.1, 4.2). The introduction test builds a genuine contact-exchange `SettlementPlan`, since the command validates it.

Evidence: bare-metal buyer suite passed, 15. Mutation: restoring `.model_dump(mode="json")` in both commands fails both tests with the original `AttributeError`. `make -k test` passed except the two known environmental gaps (the VM storefront's Alkahest chain tests; the Helm render step without `helm`). Fresh-context compliance check: no layering, comment, packaging, or key-marking violation; fixed the collaborator list above, which had named the payment-stage replacements for both commands, and a reassigned parameter; the mocking departure is recorded rather than refactored, as above. `make check-change` passed.

End-to-end: as planned.

## 5. Compensate a failed payment deal and clean up independently

Delivers D6 and D7, implementing the `test-compatibility` delta's scenario "A stage fails after the payment is approved". Touches `e2e-tests/tests/e2e/roles/helpers/` (a new cleanup helper), `e2e-tests/tests/unit/`, and `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_payment_deal.py`.

- [x] 5.1 Add a cleanup helper to `e2e-tests/tests/e2e/roles/helpers/` that attempts each named step in order, recording a failure without stopping the later steps, then runs each always-run step the same way, and raises one error naming every step that failed (D7; 01 F3).
- [x] 5.2 Unit-test 5.1: a failing step does not stop later steps or the always-run steps; every failure is reported by name; a clean run raises nothing (D7).
- [x] 5.3 In the payment scenario, record the purchase's negotiation and transaction from the buy command's run events as soon as the command returns, before asserting its success, so a command that failed after approval still leaves them recorded (D6; 01 F2).
- [x] 5.4 Rebuild the supply fixture's cleanup on 5.1: when a transaction is recorded and the deal's teardown stage has not completed, refund it through the pinned seller, then tear the purchase's fulfillment down by its negotiation, waiting for capacity release; then disarm gates, drain, and remove the pool override, mock rules included; with the storefront's lifecycle loops, fulfillment convergence, and the lease watchdog resumed as always-run steps, by `docs/development/TESTING.md`'s finaliser rule (D6, D7; 01 F2, 01 F3).

Verification: e2e unit suite (`make -C e2e-tests test-unit`; unit) for 5.1; the payment scenario collects its three calls against the lane's settings; `make test`; comment hygiene. End-to-end: `e2e_bare_metal_payment_deal` exercises 5.3 and 5.4 only against a configured payments target; the pipeline configures none, so it skips there and is no evidence for this section, and its failure path is not exercised by any run.

Done. `e2e-tests/tests/e2e/roles/helpers/cleanup.py`'s `run_cleanup` attempts each named step, records any failure — a `pytest.fail` inside a step included — and runs the always-run steps in a `finally`, so only an interrupt stops the ordinary steps, and even then the always-run ones run; it then raises `CleanupFailed` naming every failed step (5.1). The payment scenario's supply fixture cleans up through it (5.4): find the outstanding purchase, refund it, release its host, remove the mock rules, drain provisioning, remove the pool override; then, always, resume the lease watchdog, fulfillment convergence, and the storefront's loops. A deal is outstanding while the refund stage has not recorded its teardown, so a passing run redoes nothing.

Plan divergence (5.3): the purchase's negotiation and transaction are read from the buyer's run directory when cleanup runs, not recorded from the command's events when it returns. `BuyerCli.run` raises on a timed-out command without returning, so recording on return would miss exactly the case cleanup exists for; the run log is the record. D6's wording is aligned. Whether a host was delivered is read before the refund (`find the outstanding purchase`): before a refund, an undelivered deal answers 404, and after one its evidence is no longer admitted without a lifecycle and answers 409, so reading it afterwards would report a failure where there is nothing to release.

Tests: `e2e-tests/tests/unit/test_cleanup_helper.py` (unit): a failing step stops neither later nor always-run steps and every failure is named; a `pytest.fail` inside a step is recorded like any failure; a clean run raises nothing; an interrupt stops the ordinary steps but the always-run ones still run (5.2).

Evidence: e2e unit suite passed, 57; the payment scenario collects its three calls; ruff passes on the changed files. Mutations: catching only `Exception` fails the `pytest.fail` case; running the always-run steps outside the `finally` fails the interrupt case; stopping at the first failure fails two cases. `make -k test` passed except the two known environmental gaps. No type checker is installed for `e2e-tests` here, so the scenario's typing was not rechecked. The cleanup itself runs only against a configured payments target, and its failure path in no run; it is proved by the helper's unit tests and by reading. Fresh-context compliance check: no guidance violation; fixed two cleanup defects it found — `pytest.fail` escaping the helper, and probing delivery after the refund — and, on its re-check, probing a deal no payment was approved for; and the import order ruff flagged in the scenario's existing imports. Declined: a unit test of `_purchase_from_run_log`, which only parses JSONL lines; `e2e-tests/pyproject.toml` not declaring `arkhai-core-buyer`, which the scenario already imported before this section (it arrives through `arkhai-bare-metal-buyer`).

Handoff: the run-log scan takes the last matching event across the buyer's run logs, which is right while the module makes one `market` run, as it does. Without an approved payment, cleanup neither probes nor releases, since no settlement can be verified and no host delivered. A purchase command that dies after approval but before settling leaves evidence the storefront never verified, which answers 409 before and after the refund: cleanup still refunds it, and reports the probe and the release as failed rather than reading the 409's wording to tell that case apart.

## 6. Document the cleanup contract

Delivers D6 and D7's operator-facing description. Touches `docs/development/TESTING.md` and `e2e-tests/README.md`.

- [x] 6.1 State in `docs/development/TESTING.md`'s bare-metal lane entry and `e2e-tests/README.md`'s "Bare-metal payment deal" that a failed run refunds and tears down any deal it left outstanding, and that every cleanup step runs with the held loops resumed last (D6, D7; 01 F2, 01 F3).

Verification: `make check-doc-citations CHANGE=qualify-bare-metal-payment-deal`; `make check-change CHANGE=qualify-bare-metal-payment-deal`. End-to-end: none.

Done. `docs/development/TESTING.md`'s bare-metal lane entry and `e2e-tests/README.md`'s "Bare-metal payment deal" describe the cleanup as the code does it: when a run fails before its refund call finishes, cleanup finds the purchase in the buyer's run log, refunds it if the log records the payment approved, and releases its host if one was delivered; each step is attempted after an earlier one fails; the loops the module paused resume last; mock-rule removal reports nothing (6.1). Evidence: `make check-doc-citations CHANGE=qualify-bare-metal-payment-deal` and `make check-change CHANGE=qualify-bare-metal-payment-deal` passed, which prove the citations resolve; that the prose matches the code rests on reading it against the fixture, which a fresh-context check did. It found the first wording unconditional where the code refunds only an approved payment and releases only a delivered host, and "the held loops" readable as the shared `bare_metal_loops_held` fixture, which this module does not use; both fixed, and D7 now says mock-rule removal goes through the shared driver, which ignores its own removal errors. End-to-end: none.

## 7. Closeout

The closeout task of `openspec/README.md#plan-closeout-requirements`, in its order. It edits documentation only; a part needing code returns the change to implementation.

- [ ] 7.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read every comment and docstring in the change's diff from `dev` for any that narrate the review or migration that introduced them. Do not edit code here.
- [ ] 7.2 **Import placement — confirm.** Check the imports the change added for any still local without a recorded reason.
- [ ] 7.3 **Documentation compliance.** Re-check D1–D8 against `openspec/README.md`'s placement rules, and `TESTING.md` and the e2e README against the scenario and its cleanup.
- [ ] 7.4 **Narrative compression.** Compress completed-task notes in sections 1–6 to final behaviour, material evidence, deferrals, and destinations, moving durable rationale into `design.md` first.
- [ ] 7.5 **Roadmap currency.** Confirm that `docs/development/ROADMAP.md`'s Goal 4 live-qualification row and `#payment-qualification-boundaries` stay true — mock access is not authenticated access, and live qualification stays with the payments service — and record the disposition.
- [ ] 7.6 **Campaign index currency.** Set this change's row under "Roadmap goal — Make the settlement mechanism a composed choice" in `openspec/changes/README.md` to `in closeout`, notes describing the archived state, then point it at the archive (7.11). Leave other rows' `Depends on` alone.
- [ ] 7.7 **Packaging.** Run `make check-packaging`, then `make check-architecture-change CHANGE=qualify-bare-metal-payment-deal`. The change touches no `.agents/`, `.claude/`, or `.codex/` file, so `make check-agent-skills` is not owed.
- [ ] 7.8 **End-to-end pipeline.** Record the run the latest passing validation names and its result as regression evidence that the lanes deploy and run. `e2e_bare_metal_payment_deal` skips there for want of a payments target, so record it as skipped, not passed; the scenario's evidence is section 1's configured run.
- [ ] 7.9 **Promotion.** The `test-compatibility` requirement is written by the archive in 7.11 from this change's delta; `TESTING.md` and the e2e README are written in section 6. Write a design-promotion record in `design.md` naming, for D1–D8, the delta requirement, permanent document, or code-only disposition of each.
- [ ] 7.10 **Documentation citations.** Run `make check-doc-citations CHANGE=qualify-bare-metal-payment-deal` and resolve every match, then `make check-change CHANGE=qualify-bare-metal-payment-deal`, which runs the pinned `@fission-ai/openspec@1.14.0` strict validation.
- [ ] 7.11 **Archival.** `bunx @fission-ai/openspec@1.14.0 archive qualify-bare-metal-payment-deal -y`, merging the `test-compatibility` delta into `openspec/specs/` (the permanent spec does not carry it, so no `--skip-specs`), then point the index row at the archive directory.
