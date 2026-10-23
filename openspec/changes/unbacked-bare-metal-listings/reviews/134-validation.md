# Validation — unbacked-bare-metal-listings — 9aa024e2448b

- **Commit:** 9aa024e2448b2758f71c23ee65a6021c8562369b on unbacked-bare-metal-listings
- **Result:** passed — local and served Helm checks passed; all three pipeline jobs succeeded. The owner authorized finalization from existing evidence while GitHub's aggregate run status remains pending.
- **Parts:** local passed · helm passed (served list) · pipeline passed (completed job evidence; aggregate pending)
- **Pipeline:** run [39835301963](https://github.com/arkhai-io/simple-compute-market/actions/runs/39835301963), all three jobs success; GitHub overall status still `in_progress`, conclusion unset at finalization

Ran 2026-10-22 with `HELM_ALL_SCENARIOS=1`. The clean change branch was fast-forwarded to the requested commit before validation. `make round-view-closed`, authentication, and `make push-branch` passed (push already up to date). `make round-e2e-baseline` returned no ID; the newest prior run was 39817716311, then the workflow was dispatched once. The commit and tracked worktree remained unchanged; no locks were refreshed, no source was edited, and no commit was made.

## Local

| Attempt | Step | Result | Duration |
|---|---|---|---|
| 1 | clean before | passed | 0s |
| 1 | dist-clean | passed | 0s |
| 1 | check-packaging | passed | 22.2s |
| 1 | test | passed | 209.7s |
| 1 | clean after | passed | 0s |

`make validate-local` exited 0. Packaging and the complete `make test` target passed, including Helm render checks. The Alkahest suite reported 415 passes during inspection, including the new construction tests. One attempt, no rerun. Retained evidence: [command output](../../../../.snapshot/validation-9aa024e-20261022T185347Z/validate-local.log) and [command exit statuses and timestamps](../../../../.snapshot/validation-9aa024e-20261022T185347Z/results.json).

## Helm

| Attempt | Step | Result | Duration |
|---|---|---|---|
| 1 | clean before | passed | 0s |
| 1 | kube context | passed | 0s |
| 1 | storefront environment | passed | 0s |
| 1 | docker | passed | 0s |
| 1 | kube node | passed | 0s |
| 1 | local secrets | passed | 0.3s |
| 1 | stop forwards | passed | 0s |
| 1 | ports free | passed | 0s |
| 1 | retained volumes | passed | 0s |
| 1 | dist-clean | passed | 0s |
| 1 | build-dev | passed | 111.2s |
| 1 | storefront environment | passed | 0.5s |
| 1 | test-render | passed | 18.3s |
| 1 | undeploy | passed | 3.8s |
| 1 | release volumes | passed | 0s |
| 1 | deploy-local | passed | 26s |
| 1 | forward | passed | 0s |
| 1 | forwarded ports | passed | 0s |
| 1 | e2e | failed | 154.7s |
| 1 | unforward | passed | 0s |
| 1 | clean after | passed | 0s |

**Raw command:** `make validate-helm HELM_ALL_SCENARIOS=1` exited 2. The expanded `e2e` step reported **112 passed, 5 failed, 18 skipped, 51 setup errors, 67 deselected** in 153.76 seconds. The supported codec tests passed. Under the skill's all-scenarios rule, the unsupported probes below test the served list rather than the commit; they do not turn a passing served-list result into a commit failure. Retained evidence: [command output](../../../../.snapshot/validation-9aa024e-20261022T185347Z/validate-helm.log) and [observations recorded from the inspected full test log](../../../../.snapshot/validation-9aa024e-20261022T185347Z/helm-scenario-observations.json).

All preflights, wheel/image builds, storefront reinstall, render checks, uninstall, fresh deploy, and cleanup passed on `docker-desktop`. The full main test log was inspected before its directory became unavailable; see About the validation. No failed scenario was rerun.

| Scenario | Observed outcome | Diagnosis |
|---|---|---|
| `e2e_alkahest_escrow_codecs` | 12 passed | passed; already served |
| `e2e_alkahest_trusted_oracle` | 1 passed | passed; can join the served list |
| `e2e_buy` | 5 passed, 1 failed, 2 skipped | expected unsupported host access: one-shot buyer follows the cluster-internal advertised seller URL; two dependent stages skip |
| `e2e_compute_dynamic_listings` | 10 passed | passed; can join the served list |
| `e2e_deal` | 31 passed | passed; can join the served list |
| `e2e_deal_buyer_cli` | 27 passed | passed; can join the served list |
| `e2e_listing_shapes` | 14 passed, 1 failed, 2 skipped | expected unsupported host access: its buy stage follows the same cluster-internal URL; two dependent stages skip |
| `multi_registry` | 6 passed, 2 failed, 12 skipped | expected unsupported topology: registry B has no local trust pins; Alice lacks admin credentials; remaining stages skip |
| `e2e_non_erc20_settlement` | 2 passed | passed; can join the served list |
| `e2e_vm_introduction` | 4 passed, 1 failed, 1 skipped | expected unsupported host access: buyer introduction follows the cluster-internal URL; seller-delivery stage skips; Mailpit is also not forwarded |
| `e2e_bare_metal_introduction` | 5 errors | expected unsupported profile: BARE_METAL_LANE.storefront_url missing |
| `e2e_bare_metal_mock_deal` | 35 errors | expected unsupported profile: same missing bare-metal lane configuration |
| `e2e_bare_metal_publication` | 11 errors | expected unsupported profile: same missing bare-metal lane configuration |

The runner omits `contracts` and both API-credit markers in all-scenarios mode. A separate invocation on the same deployment ran `make -C e2e-tests test-module MODULE="contracts or e2e_credits_deal or e2e_credits_payment_deal"`; this adds missing coverage rather than retrying failures. Its raw exit was 2: **1 passed, 4 setup errors, 248 deselected**. `contracts` passed; the credits deal failed setup for missing `API_CREDITS.COMPUTE_REGISTRY_URL`, and all three payment tests failed setup for missing `API_CREDITS.REGISTRY_URL`. This profile supplies no API-credit stack. Evidence: [supplemental test log](../../../../.snapshot/validation-9aa024e-20261022T185347Z/supplement-omitted-scenarios.log) and [supplemental commands and outcomes](../../../../.snapshot/validation-9aa024e-20261022T185347Z/supplement.json).

Thus both entries in `HELM_SCENARIOS` passed: RPC smoke (`contracts`, 1 supplemental test) and escrow codecs (12 main-run tests). Port-forwards were stopped after both runs. The tested local release remains deployed.

### Diagnosis of the expanded failures

All are outside the served list, with high-confidence topology/profile causes:

- **Three VM failures:** `test_b4_market_buy_reaches_ready` (`e2e_buy`), `test_04a_market_buy_discovers_by_memory_and_reaches_ready` (`e2e_listing_shapes`), and `test_04_the_buyer_cli_negotiates_and_reveals` (`e2e_vm_introduction`) follow a listing's advertised `http://arkhai-node-operator-storefront-bob:8001` URL from the host. The inspected log showed `Name or service not known`; the first two buyers exit 4 and introduction exits 1. The chart's `storefront.agentBaseUrl` (`helm/charts/storefront/templates/_helpers.tpl:95`) deliberately derives Service DNS, and `config-local.yml` forwards only host endpoints. Direct-client scenarios use the local override and pass. This is the current host-to-cluster reachability gap, not a settlement assertion failure. Original inspected log lines 1394–1471 and 1494–1504 held the failure details; that file is no longer available.
- **Two multi-registry failures:** `test_00e_registry_b_reachable` and `test_04b_bob_in_b_with_bearer` assert that `http://localhost:8082` has configured registry pins. None are configured in the local profile; the tested default release is not the two-registry topology. Original log lines 1474–1493 showed the assertion. Twelve stages skip, including for absent `ALICE.ADMIN_CREDENTIAL`. No unsigned fallback or fixture change was attempted.
- **51 bare-metal setup errors:** every selected bare-metal test stops on `BARE_METAL_LANE.storefront_url is not configured`, through `lane_setting` in that lane's `conftest.py`. The local profile does not name a bare-metal target, and this validation rebuilt only the default VM release. Unrelated older bare-metal pods present in the cluster were neither selected nor treated as evidence for this commit. Counts: introduction 5, mock deal 35, publication 11.
- **Four supplemental API-credit setup errors:** the retained supplemental log shows the missing settings named above. These prove absent local lane wiring, not a payment or credit-settlement failure.

Eighteen main-run skips are dependent stages or missing Alice configuration, not passes. No scenario marker was left unattempted after the supplement; setup failures provide no behavior coverage. Mail delivery in the introduction scenario was not reached and Mailpit is not forwarded by this target.

## Pipeline

| Lane | Job | Result | Scenario test outcomes | Duration |
|---|---|---|---|---|
| VM | 120021924743 | success | 135 passed, 118 deselected | 4m48s |
| Bare metal | 120021924315 | success | 51 passed, 202 deselected | 3m12s |
| API credits | 120021924699 | success | 1 passed, 3 skipped, 249 deselected | 2m31s |

All jobs completed successfully; the last finished at 18:58:12 UTC. GitHub's overall run remained `in_progress` with no conclusion after the jobs completed, verified through both `gh run view` and the Actions REST API. This is not reported as an aggregate `success` conclusion.

`make fetch-e2e-logs E2E_AFTER_RUN=39817716311` waited on that overall status. While it waited, each completed job's Actions log and compose artifact was downloaded directly. After the owner said **"Finalize validation from existing evidence"**, the read-only watcher was stopped; the fetch command consequently exited with an interrupted-watch error. It did not produce the usual combined `actions.log` or archive. The evidence below is the directly downloaded job output, not a claimed successful standard fetch.

Evidence: [run and job metadata](../../../../.snapshot/validation-9aa024e-20261022T185347Z/pipeline.json); job logs and compose logs under `.snapshot/e2e-logs/39835301963`; [per-scenario counts parsed from those job logs](../../../../.snapshot/validation-9aa024e-20261022T185347Z/pipeline-scenario-counts.json). VM job log line 4471 records the revised trusted-oracle scenario passing, and line 5505 gives its lane total. Bare-metal line 3916 gives its total. API-credit lines 3302–3306 record the three payment skips and lane total.

## Coverage of this change

This is the second fix commit for round 1 (Sections 3–10), not completion of the full change. Scenario basis comes from those sections' verification and both triage notes, plus the only scenario module changed by `git diff 9aa024e^ 9aa024e -- e2e-tests`, the trusted-oracle test.

| Scenario | Basis | Lane outcomes |
|---|---|---|
| `e2e_credits_deal` | Sections 6–9: explicit probe/seed step, ready publication, buyer funding | e2e-apicredits: 1 passed; Helm: 1 errors |
| `e2e_credits_payment_deal` | Section 6 explicitly excludes this as Alkahest seed-readiness evidence; pipeline has no payments target | e2e-apicredits: 3 skipped; Helm: 3 errors |
| `e2e_bare_metal_introduction` | Existing bare-metal contact-exchange regression | e2e-bare-metal: 5 passed; Helm: 5 errors |
| `e2e_bare_metal_mock_deal` | Sections 4–5 and 7–9: pinned opening, accepted-plan settlement, typed-client funding | e2e-bare-metal: 35 passed; Helm: 35 errors |
| `e2e_bare_metal_publication` | Sections 4–5: backed publication and ready Alkahest option derivation | e2e-bare-metal: 11 passed; Helm: 11 errors |
| `e2e_alkahest_escrow_codecs` | Sections 3–5 and 8: escrow codec create/read against the chain | e2e-vm: 12 passed; Helm: 12 passed |
| `e2e_alkahest_trusted_oracle` | Changed by this commit, Section 3 second-triage note: kit release_conditions and encode_authorized_release_condition tested against the deployed trusted-oracle arbiter | e2e-vm: 1 passed; Helm: 1 passed |
| `e2e_buy` | Sections 4 and 9: chain readiness and one-shot buyer derivation | e2e-vm: 8 passed; Helm: 5 passed, 1 failed, 2 skipped |
| `e2e_compute_dynamic_listings` | Publication/provisioning regression while readiness composition changes | e2e-vm: 10 passed; Helm: 10 passed |
| `e2e_deal` | Sections 5, 7, 8: derived conditions, pinned opening, accepted-plan settlement | e2e-vm: 31 passed; Helm: 31 passed |
| `e2e_deal_buyer_cli` | Sections 7–9: derived buyer funding held to the recorded seller plan | e2e-vm: 27 passed; Helm: 27 passed |
| `e2e_listing_shapes` | Section 5: Alkahest option derivation on ready publication clauses | e2e-vm: 17 passed; Helm: 14 passed, 1 failed, 2 skipped |
| `multi_registry` | Section 8 and round-1 notes: independent authorities and pinned openings | e2e-vm: 21 passed; Helm: 6 passed, 2 failed, 12 skipped |
| `e2e_non_erc20_settlement` | Sections 7–8: native-token/ERC1155 settlement against accepted plans | e2e-vm: 2 passed; Helm: 2 passed |
| `e2e_vm_introduction` | Existing non-Alkahest regression; later introduction work is still pending | e2e-vm: 6 passed; Helm: 4 passed, 1 failed, 1 skipped |

The changed trusted-oracle scenario now uses `release_conditions` and `encode_authorized_release_condition` to derive and encode the kit's advertised oracle-gated condition before funding, fulfillment, arbitration, and collection. It passed on both the VM pipeline and Helm chain. This is stronger evidence than the previous SDK-only scenario.

The hung-construction fix has focused local unit evidence: `test_a_construction_that_never_returns_is_started_once_and_holds_no_shared_worker` and `test_a_construction_that_finishes_late_is_adopted_by_the_next_probe` ran in the Alkahest suite. No pipeline scenario simulates a permanently hung constructor or an unusable Alkahest section. Degraded-start and application wiring work assigned to Section 11 is still pending. Sections 11–22, including `e2e_bare_metal_unbacked_introduction`, are not implemented here and gain no completion claim from this validation.

## Environment

The supported local and Helm checks required no environmental remedy or rerun. The expanded failure diagnoses above are expected unsupported topology/profile observations under the all-scenarios rule; no deployment/configuration fix was attempted.

The pipeline's three payment tests skip because the pipeline supplies no payments target, as Section 6's notes anticipate. No payment settlement/refund success is claimed.

GitHub's pending aggregate status was settled with the owner: direct completed-job evidence was obtained, then the owner authorized finalization from it. This record marks the pipeline passed on those job results while explicitly retaining the pending overall status. No workflow was cancelled, rerun, or redispatched.

## Failures

None. No commit-caused or unknown-cause failure remains after distinguishing the expected unsupported Helm probes.

## About the validation

1. **The served list can grow.** The following entire scenarios passed against the fresh Helm release: `e2e_deal` (31), `e2e_deal_buyer_cli` (27), `e2e_compute_dynamic_listings` (10), `e2e_non_erc20_settlement` (2), and `e2e_alkahest_trusted_oracle` (1). They can join `HELM_SCENARIOS`; no code was edited here. Partial passes in buy, shapes, multi-registry, or introduction are not promotion evidence.
2. **All-scenarios selection is incomplete.** `PIPELINE_MARKER_VARIABLES` in `scripts/validate_slice.py:63` omits `E2E_APICREDITS_MODULE`; replacing the served list with pipeline markers also drops `contracts`. Consequently the machine summary's empty `not_run` map overstates selection coverage. The missing markers were attempted separately as documented above.
3. **Raw Helm status needs interpretation.** The script marks the whole `e2e` step failed when an unserved probe fails. Its original raw command/exit is preserved, while this record applies the skill's served-list rule. No result file was rewritten to make the raw command appear successful.
4. **Evidence retention gap.** After inspection and before report writing, `.snapshot/validation/9aa024e2448b/` disappeared while HEAD and tracked files stayed unchanged. The cause is unknown; this session issued no deletion of those files. The original per-step logs and original `summary.json` files therefore cannot be included. Both command outputs retain the complete step summaries and durations, the main Helm output retains its final counts/error tail, and the supplemental and pipeline logs remain intact. `.snapshot/validation-9aa024e-20261022T185347Z/step-results-from-command-output.json` is explicitly reconstructed from command output; `helm-scenario-observations.json` records observations made before the loss and is not presented as the original test log. No rerun was made to replace lost evidence.
5. **GitHub finalization delay.** The standard fetch waits for an aggregate workflow conclusion even after all jobs and their logs are available. Direct job-log/artifact downloads supplied the evidence; the owner's explicit disposition and the pending aggregate state are recorded above.

## Next

There are no `V<n>` findings. The next-step computation still asks the owner to agree the next implementation round and its session mapping, listing pending Sections 11–22. The design proposes Sections 11–13 as round 2, then Sections 14–22 as round 3. This validation does not replace a review or invent a missing advancement disposition.
