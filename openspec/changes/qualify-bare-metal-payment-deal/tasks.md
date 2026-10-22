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

## 4. Clean up after failure and pin the completion fix

Accepted in the design review's triage (`reviews/01-design-external.triage.md`); planning shapes this section.

- [ ] 4.1 Record the deal's negotiation, transaction, and fulfillment as soon as each exists, reading them from the original run when `market bare-metal buy` fails after approval; in the module cleanup, refund any transaction not yet refunded, then tear down any fulfillment not yet torn down, best effort (D6; 01 F2).
- [ ] 4.2 Restructure the supply fixture's cleanup so each owned step is attempted on its own and its failure reported at the end, with loop resumption in an outer `finally`, by `docs/development/TESTING.md`'s finaliser rule (D7; 01 F3).
- [ ] 4.3 Unit-level regression tests for `market bare-metal buy` and `market bare-metal request-introduction` completing with dictionary-backed accepted provision terms: each command's `run_ended` event carries them, and each test fails if its command calls `.model_dump()` on them (D5; 01 F5).
- [ ] 4.4 Update `docs/development/TESTING.md` and `e2e-tests/README.md` to the cleanup contract of D6 and D7 (01 F2, 01 F3).
