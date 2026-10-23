# Validation — unbacked-bare-metal-listings — da1929a6e5ac

- **Commit:** da1929a6e5acbb5b976cabedd3c8267b4da3aad3 on unbacked-bare-metal-listings
- **Result:** failed — the e2e-vm lane fails two multi-registry scenarios because the commit's scenario creates its listings without the release condition its own helper now requires
- **Parts:** local passed · helm passed · pipeline failed
- **Pipeline:** run 107609315856, failure (e2e-vm; e2e-bare-metal and e2e-apicredits succeeded)

This validation ran in manual mode. `gh` had no working token, so nothing was pushed or dispatched here. The pipeline run is the one `make round-view` dispatched for this commit at 01:33Z, and its logs were supplied by the owner under `.snapshot/e2e-logs/run-107609315856/`. The sandbox has no helm binary and lacks Anvil, so the owner ran the final local and Helm parts on their own machine at the same commit. Their results were unpacked as `local/2` and `helm/1`.

## Local

| Attempt | Step | Result | Duration |
|---|---|---|---|
| 1 (sandbox) | clean before | passed | 0.0s |
| 1 (sandbox) | dist-clean | passed | 0.1s |
| 1 (sandbox) | check-packaging | passed | 61s |
| 1 (sandbox) | test | failed (environment, see below) | 362.3s |
| 1 (sandbox) | clean after | passed | — |
| 2 (owner's machine; its summary.json says attempt 1) | clean before | passed | 0.0s |
| 2 (owner's machine) | dist-clean | passed | 0.0s |
| 2 (owner's machine) | check-packaging | passed | 17.4s |
| 2 (owner's machine) | test | passed | 274.0s |
| 2 (owner's machine) | clean after | passed | — |

Local result: passed, on the owner's run. The sandbox attempt is kept as evidence. Logs are under `.snapshot/validation/da1929a6e5ac/local/1/` and `local/2/`.

## Helm

Ran on the owner's machine (kube context `docker-desktop`), attempt 1, all steps passed.

| Attempt | Step | Result | Duration |
|---|---|---|---|
| 1 | preflights (context, storefront environment, docker, node, secrets, forwards, ports, retained volumes) | passed | ≈0.3s |
| 1 | dist-clean | passed | 0.0s |
| 1 | build-dev | passed | 106.4s |
| 1 | storefront environment | passed | 0.5s |
| 1 | test-render | passed | 17.7s |
| 1 | undeploy | passed | 2.8s |
| 1 | release volumes | passed | 0.0s |
| 1 | deploy-local | passed | 40.5s |
| 1 | forward / forwarded ports | passed | 0.0s |
| 1 | e2e | passed | 3.1s |
| 1 | unforward | passed | 0.0s |
| 1 | clean after | passed | — |

The Helm `e2e` step ran only `-m "contracts or e2e_alkahest_escrow_codecs"`: 13 passed.

Not run against Helm: e2e_deal, e2e_deal_buyer_cli, e2e_buy, multi_registry, e2e_compute_dynamic_listings, e2e_listing_shapes, e2e_vm_introduction, e2e_non_erc20_settlement, e2e_bare_metal_publication, e2e_bare_metal_introduction, e2e_bare_metal_mock_deal — the default charts serve no settlement mechanism, and not every service the pipeline's compose stacks run. None of these is a pass.

## Pipeline

Run 107609315856 at da1929a, failed overall.

- **e2e-bare-metal:** passed, 51 passed, 201 deselected.
- **e2e-apicredits:** passed, 1 passed, 3 skipped, 248 deselected.
- **e2e-vm:** failed, 2 failed, 131 passed, 1 skipped, 118 deselected.
  - Failed: `vms/test_multi_registry.py::TestStage06a_NegotiateWithBob::test_06a_buyer_starts_negotiation_with_bob` and `TestStage06b_NegotiateWithAlice::test_06b_buyer_starts_negotiation_with_alice` (V1).
  - Skipped: `test_06c_negotiations_are_distinct_objects_on_distinct_storefronts`, as a consequence of the 06a/06b failures.
  - Passed in the same lane: `test_non_erc20_settlement.py` (native-token and erc1155 cases were seen in the log) and `test_vm_introduction.py`, all five stages.

## Coverage of this change

| Scenario | Basis | Lane | Result |
|---|---|---|---|
| `multi_registry` (06a, 06b) | Section 8 task notes: the opening is pinned with the listing's condition | e2e-vm | **failed** (V1) |
| `e2e_non_erc20_settlement` | Section 8 task notes: opens pinned | e2e-vm | passed in the observed cases |
| `e2e_vm_introduction` | The change's unbacked VM introduction scenario | e2e-vm | passed |
| `e2e_bare_metal_mock_deal` and the bare-metal introduction and publication scenarios | Section 8 task notes and the change's bare-metal scenarios | e2e-bare-metal | lane passed (51 passed) |
| `e2e_deal`, `e2e_buy`, `e2e_deal_buyer_cli` | Section 8 task notes | e2e-vm | lane's remaining tests passed; not individually checked in the log |
| API-credit deal | Section 8 task notes | e2e-apicredits | passed, 1 passed and 3 skipped |
| Contracts and Alkahest escrow codecs | Helm e2e step | helm (owner's machine) | passed, 13 passed |

## Environment

**Sandbox lacks the Alkahest test chain runtime.**
- *Evidence:* local attempt 1, `domains/vms/storefront` `make test-integration`: 450 passed and 2 failed (`tests/integration/test_alkahest.py::test_rust` and `::test_python`) with "EnvTestManager could not start the local Alkahest test chain runtime… could not spawn node: No such file or directory". The sandbox has no `anvil`.
- *Remedy and decision:* the owner ran `make validate-local` on their own machine at the same commit. The result is attempt 2, which passed. No remedy was applied to the sandbox.

**`gh` token expired.**
- *Evidence:* `gh auth status` reported the GH_TOKEN as invalid.
- *Remedy and decision:* the owner could not refresh it and chose manual mode. The pipeline logs of the run dispatched by `make round-view` were supplied instead of `make fetch-e2e-logs`. No push or dispatch ran during this validation.

## Failures

### V1 — e2e-vm `multi_registry` stages 06a and 06b raise `StopIteration` in `alkahest_opening`

- **Part:** pipeline
- **Evidence:** `.snapshot/e2e-logs/run-107609315856/2_e2e-vm.txt` lines 5320–5535. Both tests fail at `test_multi_registry.py:363` in `_escrow_named_by`, then `compute_deal_stages.py:116` in `alkahest_opening`, in the `next(...)` over `listing.demands`, with `E   StopIteration`. The summary reads "2 failed, 131 passed, 1 skipped".
- **Cause:** commit

Section 8 (20eb232) made `alkahest_opening` take the release condition from the listing's advertised `demands`. It also added `_escrow_named_by` to `test_multi_registry.py`, and stages 06a and 06b now call it. The stages that create the listings still call `create_listing(...)` with `accepted_escrows=ACCEPTED_ESCROWS` and no `demands=` (`test_multi_registry.py` stage 03c, Bob's listing, and the matching stage for Alice's). The registry listings therefore advertise no release condition, and `next(...)` finds nothing. Every other VM scenario that opens an escrow (`test_full_deal.py`, `test_buy_oneshot_buyer_cli.py`, `test_full_deal_buyer_cli.py`, `test_non_erc20_settlement.py`) passes `demands=_recipient_demands(...)` at creation. The fix belongs to triage: give the multi-registry listings a release condition at creation. A listing advertising no condition is a mistake in how the scenario builds its listings, not in the code under test.

## About the validation

- The sandbox's `validate-local` cannot run `domains/vms/storefront`'s `test-integration` without Node and Anvil. The preflight does not check for them, so the failure surfaced only 6 minutes into `make test`. A preflight for the Alkahest test chain toolchain would have caught it earlier.
- The owner's `local` summary.json says attempt 1 and its log paths name `local/1`, because it was produced on another machine. It was unpacked as `local/2` so it would not overwrite the sandbox attempt, and its paths do not match its directory.
