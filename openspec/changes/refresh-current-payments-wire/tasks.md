# Tasks

## 1. Published contract consumer

- [x] 1.1 Inspect the selected standalone schema and vectors for public suitability, vendor them under `kit/arkhai-payments/schema/` and `test-vectors/`, retaining historical vectors separately; verify exact hashes and document transformations in `schema/SOURCE.md`.
- [x] 1.2 Extend `kit/arkhai-payments/tests/test_wire_contract.py` and existing canonical/vector tests to reproduce optional end and zero gross failures and exercise producer snapshots, required null, optional omission, bounds and extra-field refusal; retain failing baseline evidence before generation.
- [x] 1.3 Reconcile `kit/arkhai-payments/scripts/generate_models.py` with the selected required-nullable definitions and exact balance property-name string constraints, regenerate `src/market_arkhai_payments/models.py`, and update `kit/arkhai-payments/scripts/check_vectors.py`; verify deterministic generation, current producer signatures/transaction IDs/attachment hashes and historical raw signatures without hand-edited generated output.
- [x] 1.4 Run the complete payment kit unit/library-integration suites and typing; update its README and SOURCE notes to describe the verified publication, not an unavailable-vector workaround. Record actual test levels and any uncovered live shapes.
- [x] 1.5 Update the kit package version and affected dependent pyproject constraints/locks using repository tooling; run affected payment settlement tests, `make check-comment-hygiene` and `make check-packaging` before the intermediate commit. Do not rebuild unchanged deployment artifacts gratuitously.

### Section 1 evidence and handoff

- Publication inspection found no operational data in the selected vectors. The
  standalone schema's source identifier alone was replaced with the neutral URN;
  original/vendored schema and exact current/historical vector hashes are recorded
  in `kit/arkhai-payments/schema/SOURCE.md`. Deterministic development accounts and
  seeds are explicitly marked unsuitable for public-network use.
- Negative baseline: the added current-wire suite against the original generated
  models produced **8 failed, 20 passed**: effective ends, zero gross in snapshot
  and embedded receipt, safe-integer upper bounds, and HTTP URL acceptance.
  Raw diagnostic output is retained outside Git. Final complete kit suite:
  `PYTHONPATH=kit/arkhai-payments/src python -m pytest kit/arkhai-payments/tests -q`
  — **145 passed**. These are unit tests with controlled transports and authorities;
  no real storage-backed kit integration or live service is exercised.
- `python kit/arkhai-payments/scripts/generate_models.py --check` passes;
  `python kit/arkhai-payments/scripts/check_vectors.py` passes current producer mandates, approvals,
  4 signed snapshots and all snapshots/events in 2 producer scenarios, plus
  historical raw identities/signature framing/attachments. The scenario check
  validates producer data, not execution of an external reducer.
  In `kit/arkhai-payments`, `python -m mypy src examples/local_e2e.py` passes all 16 source files.
- Standalone references exposed two generator seams: nested `DealCommitment`
  wrappers require comparisons through `wire_json`, and `Balance.available`
  property-name references otherwise generate unhashable root-model keys.
  Generation dereferences the identical asset string constraints and checks the
  constrained-key output before rendering its equivalent typing-valid annotation.
  Acceptance and invalid-asset tests cover that seam. No derivation, canonical
  serialization, receipt frame or transaction identity algorithm changed.
- Focused dependent application integration, using the current payment source and
  existing installed dependencies: VM
  `domains/vms/storefront/tests/integration/test_payment_settlement.py` — **22 passed**;
  API-credit `domains/apicredits/storefront/tests/integration/test_payment_settlement.py`
  plus `test_payment_recovery.py` — **17 passed**; bare-metal
  `domains/bare_metal/storefront/tests/integration/test_payment_settlement_client.py`
  — **16 passed**. Apps, authentication and SQLite are real; payment and domain
  authorities are controlled. Bare-metal includes a CLI call over loopback. These
  do not prove external funding, provisioning or hardware revocation.
- SDK version is 0.5.0. Seven direct consumer constraints and ten affected locks
  were refreshed with `make lock PROJECTS="kit/arkhai-payments domains/apicredits domains/apicredits/buyer domains/apicredits/service domains/apicredits/storefront domains/bare_metal/buyer domains/bare_metal/storefront domains/vms/buyer domains/vms/storefront e2e-tests"`.
  `make check-comment-hygiene`, `git diff --check` and `make check-packaging` pass;
  the built payment wheel's model bytes equal the final generated source.
  Sandbox cache restrictions required an environmental continuation using the
  existing cache; initial restricted dependent-suite attempts were interrupted
  without a result. No duplicate environments, container images or charts were built.
- E2E coverage owed to the frozen round: `e2e_credits_payment_deal` and
  `e2e_bare_metal_payment_deal` exercise external payment integration when their
  separately configured authorities are available. No existing VM payment E2E
  marker or provider-funding marker establishes this wire refresh by itself.
  Exact deployed/selected response compatibility, historical operational receipts,
  full-suite/independent review and CI/E2E/Helm evidence remain section 2 work.
- Owed by validation: `tests.yml`, `build · kit-arkhai-payments`, must build the
  portable payment wheel; `test · test-kits`, `test · test-storefront`,
  `test · test-bare-metal` and `test · test-apicredits` must pass the affected
  kit/domain suites; `check · architecture` must confirm dependency boundaries.
  No push-only evidence is claimed by this section.

Independent section-1 source review found no actionable findings; see `reviews/01-implementation.md`. Full frozen-round validation remains outstanding.

## 2. Frozen candidate validation

- [ ] 2.1 Freeze source and artifact inputs; complete one full suite, combined independent review, CI/E2E and Helm round under the approved cadence, binding evidence to the candidate and disclosing environmental continuations and unrun scenarios.
- [ ] 2.2 Verify rebuilt consumer response compatibility with BOTH the currently deployed authority contract and selected publication before any consumer/endpoint/server change; prove and record identity if the same check covers both, or establish compatible rollout order if they differ. Separately verify retained historical receipt signatures. Record response scope and immutable evidence privately; no credentials, operational addresses or raw service records enter Git.

No existing E2E marker proves hosted payment-provider funding. Existing Arkhai settlement scenarios cover buyer/seller integration; live funding and physical delivery remain separate acceptance evidence. Record precise exercised markers and push-only workflow/job obligations once implementation identifies the affected suites.

## 3. Closeout

- [ ] 3.1 Confirm comment hygiene and imports added by this change; run `make check-comment-hygiene`, returning source defects to implementation rather than editing code in closeout.
- [ ] 3.2 Check accepted decisions against documentation ownership; compress completed task notes to final behavior, evidence, deferrals and destinations, retaining necessary rationale in design.
- [ ] 3.3 Reconcile `docs/development/ROADMAP.md` and `openspec/changes/README.md` with actual readiness; explicitly record no-impact dispositions and preserve all outstanding physical qualification work.
- [ ] 3.4 Run `make check-packaging` and `make check-architecture-change CHANGE=refresh-current-payments-wire`; resolve owned exceptions and confirm recorded E2E evidence exercises the actual consumer boundary.
- [ ] 3.5 Promote accepted explanation to `openspec/specs/market-composition/architecture.md#agreement-based-payment-composition`, finalize kit README/SOURCE and this design-promotion record; normative promotion is the spec delta at archival. Confirm no repository-wide architecture change, or promote one if implementation actually required it.
- [ ] 3.6 Run `make check-doc-citations CHANGE=refresh-current-payments-wire` and pinned strict OpenSpec validation, resolving every citation; archive only after all preceding requirements, then perform closeout review/triage and archive cleanup with accurate index status.
