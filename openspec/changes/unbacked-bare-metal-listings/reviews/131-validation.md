# Validation — unbacked-bare-metal-listings — e15a5b23e1db

- **Commit:** e15a5b23e1db0889947ff6740e051aa5df8a59e6 on unbacked-bare-metal-listings
- **Result:** passed — local, default Helm validation, and all three E2E pipeline lanes passed in the owner's environment; the payments-target tests skipped as expected.
- **Parts:** local passed · helm passed · pipeline passed
- **Pipeline:** run 39817716311, success

Every part below ran in the owner's environment, not in this session: this session had no working GitHub token and may not push, dispatch, or run Helm commands. The owner sent the evidence, unpacked at `.snapshot/owner-validation-e15a5b2/`. I checked it as follows:

- `SHA256SUMS` verifies for every file.
- `results.json` and both part summaries name the full commit above and match this checkout's `HEAD` (`git rev-parse HEAD`). Both report a clean worktree before and after, and `head_after` is unchanged.
- `pipeline.json` is run 39817716311 with `headSha` equal to the commit and conclusion `success` for all three jobs. The baseline run ID recorded before dispatch is 39797271150.
- The pytest summary lines in `pipeline/actions.log` match the counts below, and the Helm `e2e.log` shows 13 passed, 240 deselected.
- The trusted-oracle test is `PASSED` at `actions.log` line 13050.

The owner's own record is kept beside the evidence as [01-validation.md](../../../../.snapshot/owner-validation-e15a5b2/01-validation.md). It is numbered in the owner's checkout; this record replaces it here.

## Local

Ran in the owner's environment.

| Attempt | Step | Result | Duration |
|---|---|---|---|
| 1 | clean before | passed | — |
| 1 | [dist-clean](../../../../.snapshot/owner-validation-e15a5b2/validation/local/1/dist-clean.log) | passed | — |
| 1 | [check-packaging](../../../../.snapshot/owner-validation-e15a5b2/validation/local/1/check-packaging.log) | passed | 21.2s |
| 1 | [test](../../../../.snapshot/owner-validation-e15a5b2/validation/local/1/test.log) | passed | 210s |
| 1 | clean after | passed | — |

One attempt; no rerun. Summary: [local summary](../../../../.snapshot/owner-validation-e15a5b2/validation/local/1/summary.json).

## Helm

Ran in the owner's environment, the default `make validate-helm` on `docker-desktop`, without `HELM_ALL_SCENARIOS=1`.

| Attempt | Step | Result | Duration |
|---|---|---|---|
| 1 | clean before | passed | — |
| 1 | kube context | passed | — |
| 1 | storefront environment (preflight) | passed | — |
| 1 | docker | passed | — |
| 1 | kube node | passed | — |
| 1 | [local secrets](../../../../.snapshot/owner-validation-e15a5b2/validation/helm/1/local%20secrets.log) | passed | 0.3s |
| 1 | [stop forwards](../../../../.snapshot/owner-validation-e15a5b2/validation/helm/1/stop%20forwards.log) | passed | — |
| 1 | ports free | passed | — |
| 1 | retained volumes | passed | — |
| 1 | [dist-clean](../../../../.snapshot/owner-validation-e15a5b2/validation/helm/1/dist-clean.log) | passed | — |
| 1 | [build-dev](../../../../.snapshot/owner-validation-e15a5b2/validation/helm/1/build-dev.log) | passed | 110.9s |
| 1 | [storefront environment](../../../../.snapshot/owner-validation-e15a5b2/validation/helm/1/storefront%20environment.log) | passed | 0.5s |
| 1 | [test-render](../../../../.snapshot/owner-validation-e15a5b2/validation/helm/1/test-render.log) | passed | 19.5s |
| 1 | [undeploy](../../../../.snapshot/owner-validation-e15a5b2/validation/helm/1/undeploy.log) | passed | 3.3s |
| 1 | release volumes | passed | — |
| 1 | [deploy-local](../../../../.snapshot/owner-validation-e15a5b2/validation/helm/1/deploy-local.log) | passed | 39.6s |
| 1 | [forward](../../../../.snapshot/owner-validation-e15a5b2/validation/helm/1/forward.log) | passed | — |
| 1 | forwarded ports | passed | — |
| 1 | [e2e](../../../../.snapshot/owner-validation-e15a5b2/validation/helm/1/e2e.log) | passed | 2.8s |
| 1 | [unforward](../../../../.snapshot/owner-validation-e15a5b2/validation/helm/1/unforward.log) | passed | — |
| 1 | clean after | passed | — |

One attempt; no rerun. Summary: [Helm summary](../../../../.snapshot/owner-validation-e15a5b2/validation/helm/1/summary.json). The served scenarios passed: `contracts` (1 test) and `e2e_alkahest_escrow_codecs` (12 tests), 13 passed and 240 deselected. The local release remains deployed; port-forwards were stopped.

Not run against Helm: the scenarios below. A default-list exclusion is not an observed failure and does not prove the charts cannot run the scenario.

| Scenario | Reason |
|---|---|
| `e2e_deal` | Outside the default Helm scenario list; VM deal parity not assessed. |
| `e2e_deal_buyer_cli` | Outside the default list; VM buyer-CLI deal parity not assessed. |
| `e2e_buy` | Outside the default list; one-shot VM buyer parity not assessed. |
| `multi_registry` | The default release has no second storefront/registry topology. |
| `e2e_compute_dynamic_listings` | Outside the default list; VM publication/admin parity not assessed. |
| `e2e_alkahest_trusted_oracle` | Outside the default list. It needs only the chain, so the runner's blanket reason does not establish that the charts cannot serve it. |
| `e2e_listing_shapes` | Outside the default list; listing-shape parity not assessed. |
| `e2e_vm_introduction` | The default forwards include no Mailpit endpoint. |
| `e2e_non_erc20_settlement` | Outside the default list; VM settlement parity not assessed. |
| `e2e_bare_metal_publication` | The default release does not deploy the bare-metal services. |
| `e2e_bare_metal_introduction` | The default release does not deploy the bare-metal services or forward Mailpit. |
| `e2e_bare_metal_mock_deal` | The default release does not deploy the bare-metal services. |
| `e2e_credits_deal` | The default release does not deploy the API-credit services. The runner's `not_run` map omits it (see "About the validation"). |
| `e2e_credits_payment_deal` | The default release deploys neither the API-credit services nor a payments target. The `not_run` map omits it as well. |

## Pipeline

Run [39817716311](https://github.com/arkhai-io/simple-compute-market/actions/runs/39817716311), dispatched and fetched in the owner's environment. Evidence: [Actions log](../../../../.snapshot/owner-validation-e15a5b2/pipeline/actions.log), [run and job metadata](../../../../.snapshot/owner-validation-e15a5b2/pipeline.json), and the compose logs under `.snapshot/owner-validation-e15a5b2/pipeline/`.

| Lane | Result | Selected test outcomes | Summary line in `actions.log` |
|---|---|---|---|
| `e2e-vm` | passed | 135 passed, 118 deselected | 14084 |
| `e2e-bare-metal` | passed | 51 passed, 202 deselected | 3958 |
| `e2e-apicredits` | passed | 1 passed, 3 skipped, 249 deselected | 8041 |

Total 187 passed and 3 skipped. The three skips are the API-credit payment tests, which skip when no payments target is configured (`e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_payment_deal.py`); the selected Docker configuration defines none.

## Coverage of this change

This is the round-1 fix commit for the implemented sections 3–10, not the complete change. Basis: those sections' verification and round-1 notes in `tasks.md`, and the scenario modules the commit added or modified under `e2e-tests/`. Per-scenario test counts below are the owner's, from the lane logs.

| Scenario | Basis | Lane | Result |
|---|---|---|---|
| `e2e_deal` | Sections 5, 7, 8; create fixture now uses derived release conditions | VM | passed (31 tests) |
| `e2e_deal_buyer_cli` | Sections 7–9; buyer derivation and plan check before funding | VM | passed (27 tests) |
| `e2e_buy` | Sections 4 and 9; one-shot create fixture; derives and checks funding inputs | VM | passed (8 tests) |
| `multi_registry` | Section 8 and round-1 note; pinned opening, independent registry authorities | VM | passed (21 tests) |
| `e2e_compute_dynamic_listings` | Publication and provisioning regression while Alkahest readiness changes | VM | passed (10 tests) |
| `e2e_alkahest_escrow_codecs` | Sections 3–5 and 8; pinned escrow codec create/read | VM | passed (12 tests) |
| `e2e_alkahest_escrow_codecs` | Same scenario against the fresh Helm chain | Helm | passed (12 tests) |
| `e2e_alkahest_trusted_oracle` | New scenario in this commit; Section 3 round-1 note | VM | passed (1 test) |
| `e2e_listing_shapes` | Section 5; publication of options derived from ready clauses | VM | passed (17 tests) |
| `e2e_vm_introduction` | Non-Alkahest regression coverage | VM | passed (6 tests) |
| `e2e_non_erc20_settlement` | Sections 7 and 8; settlement against the accepted plan | VM | passed (2 tests) |
| `e2e_credits_deal` | Sections 6–9; admin fixture steps chain probe and listing seed before discovery | API credits | passed (1 test) |
| `e2e_credits_payment_deal` | Section 6 names it; the round-1 note excludes it as evidence for Alkahest seed readiness | API credits | skipped (3 tests) |
| `e2e_bare_metal_publication` | Sections 4 and 5; backed publication and ready option derivation | Bare metal | passed (11 tests) |
| `e2e_bare_metal_mock_deal` | Sections 4, 5, 7–9; pinned opening, accepted-plan settlement, typed-client funding | Bare metal | passed (35 tests) |
| `e2e_bare_metal_introduction` | Contact-exchange regression while settlement composition changes | Bare metal | passed (5 tests) |
| `contracts` | Helm external-layer check of RPC availability and chain ID | Helm | passed (1 test) |

Limits of this evidence:

- The trusted-oracle scenario exercises real SDK escrow creation, fulfillment, arbitration, and collection against the lane's chain. It does not drive a storefront's oracle-gated option readiness.
- No pipeline scenario configures an unusable Alkahest section. Wrong-chain recovery, provider-startup rejection, and signed-failure negative paths are covered by unit and integration tests in the local target, not end to end.
- Sections 11–22 are not implemented in this commit. In particular `e2e_bare_metal_unbacked_introduction` belongs to Section 22 and is absent, so this result is not evidence that unbacked bare-metal discovery and introduction are complete.
- No payment settlement or refund success is claimed.

## Environment

In this session, `gh auth status` failed because `GH_TOKEN` was invalid, so the pipeline could not be dispatched here. The owner settled it by running the full validation in their own environment with a working token and sending the evidence above. No environmental failure occurred in the owner's run, and no remedy or rerun was needed.

## Failures

None.

## About the validation

1. `PIPELINE_MARKER_VARIABLES` (`scripts/validate_slice.py`) reads `E2E_MODULE` and `E2E_BARE_METAL_MODULE` but not `E2E_APICREDITS_MODULE`. The JSON `not_run` map therefore omits both API-credit scenarios, which did not run against Helm. They are listed in this record.
2. `NOT_SERVED` gives one blanket reason for every unselected marker. `e2e_alkahest_trusted_oracle` needs only the chain and funded development wallets, so its exclusion by the fixed `HELM_SCENARIOS` list is not evidence that missing services prevent it. It was not attempted against Helm. The served list should be reassessed separately.

Neither changes the observed pass of the selected Helm tests. This session ran no validation code and changed no tracked file.
