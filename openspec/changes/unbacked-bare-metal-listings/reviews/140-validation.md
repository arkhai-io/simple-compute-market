# Validation — unbacked-bare-metal-listings — aa00b15fd4e4

- **Commit:** aa00b15fd4e43dff93b95eac6575856f2d906b01 on unbacked-bare-metal-listings
- **Result:** passed — every part ran and passed at the relocked commit
- **Parts:** local passed · helm passed · pipeline passed
- **Pipeline:** run 40009822297, success

This commit is `8ac565773` (sections 11–13 and the scenario-hold fix) plus one relock
commit. An earlier attempt at `8ac565773` passed every test, but `make test` rewrote
seven committed `uv.lock` files. At the owner's instruction, the locks were regenerated
with `make lock`, committed as `aa00b15fd`, and pushed, and that commit was validated
from the start. See "About the validation".

## Local

| Attempt | Step | Result | Duration |
|---|---|---|---|
| 1 | clean before | passed | 0s |
| 1 | dist-clean | passed | 0s |
| 1 | check-packaging | passed | 21.0s |
| 1 | test | passed | 222.3s |
| 1 | clean after | passed | 0s |

Logs: `.snapshot/validation/aa00b15fd4e4/local/1/`.

## Helm

| Attempt | Step | Result | Duration |
|---|---|---|---|
| 1 | clean before | passed | 0s |
| 1 | kube context | passed (docker-desktop) | 0s |
| 1 | storefront environment | passed | 0s |
| 1 | docker | passed | 0s |
| 1 | kube node | passed | 0s |
| 1 | local secrets | passed | 0.3s |
| 1 | credential helper | warning — `docker-credential-desktop.exe` did not answer within 5s; builds were unaffected | 0s |
| 1 | stop forwards | passed | 0s |
| 1 | ports free | passed | 0s |
| 1 | retained volumes | passed (none) | 0s |
| 1 | dist-clean | passed | 0s |
| 1 | build-dev | passed | 116.0s |
| 1 | storefront environment | passed | 0.6s |
| 1 | test-render | passed | 18.9s |
| 1 | undeploy | passed | 7.7s |
| 1 | release volumes | passed (none remain) | 0s |
| 1 | deploy-local | passed | 19.4s |
| 1 | forward | passed | 0s |
| 1 | forwarded ports | passed | 0s |
| 1 | e2e | passed — `contracts`, `e2e_alkahest_escrow_codecs`, `e2e_alkahest_trusted_oracle`: 14 passed | 3.0s |
| 1 | unforward | passed | 0s |
| 1 | clean after | passed | 0s |

Logs: `.snapshot/validation/aa00b15fd4e4/helm/1/`.

Not run against Helm: `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `multi_registry`,
`e2e_compute_dynamic_listings`, `e2e_listing_shapes`, `e2e_vm_introduction`,
`e2e_non_erc20_settlement`, `e2e_bare_metal_publication`, `e2e_bare_metal_introduction`,
`e2e_bare_metal_mock_deal`, `e2e_credits_deal`, `e2e_credits_payment_deal`. For every
one, the default charts carry no settlement mechanism and do not run every service the
pipeline's compose stacks run.

## Pipeline

Run 40009822297 on `aa00b15fd`, success. Logs: `.snapshot/e2e-logs/40009822297/`.

- **e2e-vm** — 135 passed, 187 deselected: `test_full_deal.py` 31,
  `test_full_deal_buyer_cli.py` 27, `test_multi_registry.py` 21, `test_listing_shapes.py`
  17, `test_alkahest_escrow_codecs.py` 12, `test_compute_dynamic_listings.py` 10,
  `test_buy_oneshot_buyer_cli.py` 8, `test_vm_introduction.py` 6,
  `test_non_erc20_settlement.py` 2, `test_alkahest_trusted_oracle.py` 1.
- **e2e-bare-metal** — 51 passed, 271 deselected: `test_bare_metal_mock_deal.py` 35,
  `test_bare_metal_publication.py` 11, `test_bare_metal_introduction.py` 5.
- **e2e-apicredits** — 1 passed, 3 skipped, 318 deselected: `test_credits_deal_buyer_cli.py`
  1 passed. All three `test_credits_payment_deal.py` cases skipped; their own guards skip
  them when the payments service is not configured or not ready, so this is the lane's
  standing behaviour, not a result.

## Coverage of this change

| Scenario | Basis | Lane | Result |
|---|---|---|---|
| `e2e_deal` | task notes (Alkahest readiness through status, the probe gating publication); section 13 holds | e2e-vm | passed (31) |
| `e2e_deal_buyer_cli` | task notes; modified by section 13 | e2e-vm | passed (27) |
| `e2e_buy` | task notes (probe-gated Alkahest options); modified by section 13 | e2e-vm | passed (8) |
| `e2e_alkahest_escrow_codecs` | task notes | e2e-vm; Helm | passed (12); passed |
| `e2e_alkahest_trusted_oracle` | task notes (round 1 second triage) | e2e-vm; Helm | passed (1); passed |
| `contracts` | task notes (Helm served list) | Helm | passed |
| `multi_registry` | task notes; modified by section 13 | e2e-vm | passed (21) |
| `e2e_compute_dynamic_listings` | task notes; modified by section 13 | e2e-vm | passed (10) |
| `e2e_listing_shapes` | task notes; modified by section 13 | e2e-vm | passed (17) |
| `e2e_non_erc20_settlement` | task notes; modified by section 13 | e2e-vm | passed (2) |
| `e2e_vm_introduction` | task notes; modified by section 13 | e2e-vm | passed (6) |
| `e2e_bare_metal_publication` | task notes (backed supply unchanged); modified by section 13 | e2e-bare-metal | passed (11) |
| `e2e_bare_metal_introduction` | task notes; modified by section 13 | e2e-bare-metal | passed (5) |
| `e2e_bare_metal_mock_deal` | task notes (probe-gated Alkahest options); modified by section 13 | e2e-bare-metal | passed (35) |
| `e2e_credits_deal` | task notes (not probe-gated; readiness through status) | e2e-apicredits | passed (1) |
| `e2e_credits_payment_deal` | task notes | e2e-apicredits | skipped (3), by its own readiness guards |
| `e2e_pool_declared_modes` | modified by section 13 (`test_pool_declared_offering_modes.py`) | none | not run, in no lane's module list |
| `e2e_bare_metal_unbacked_introduction` | task notes (sections 19, 20, 22) | none | does not exist yet: section 22, unimplemented, creates it |

The change's own behaviour, unbacked bare-metal supply, has no end-to-end evidence at
this commit. Its scenario arrives with section 22. The green pipeline shows that
sections 1–13 leave the existing deal, publication, and introduction scenarios intact,
and that section 13's module-scoped holds work on every lane.

## Environment

None.

## Failures

None.

## About the validation

- **`check-locks` passes locks that `uv sync` rewrites.** At `8ac565773`, local attempt 1
  (`.snapshot/validation/8ac56577379a/local/1/`) passed `check-packaging`, including
  `check-locks`, and every suite in `make test`. That `make test` then rewrote seven
  locks:
  - `domains/{bare_metal,vms}/storefront`
  - `domains/{bare_metal,vms}/provisioning/adapter`
  - `e2e-tests`
  - `provisioning/compute`
  - `provisioning/compute/service`

  They had been written by a different uv: the section 13 corrections note a repair
  pass on uv 0.11.17, and this machine runs 0.12.19. The two forms resolve the same
  versions, but they are written differently:
  - the 0.11.17 form puts a per-dependency platform marker on every dependency, each
    repeating the lock's `supported-markers`;
  - it also carries wheels for unsupported platforms, such as greenlet's s390x and
    riscv64 wheels.

  `check-locks` treats both forms as current. The scripts' clean-after guard caught the
  rewrite, as designed. Nothing pins a uv version, so this recurs whenever contributors
  lock with different uv releases. Two remedies would stop it:
  - pin the uv version (`required-version`);
  - have `check-locks` compare a fresh `uv lock` byte for byte.

  At the owner's instruction, the locks were relocked with `make lock` as commit
  `aa00b15fd`. No resolved name or version changed, and that commit was validated here.
- The Docker credential helper warning recurs (`docker-credential-desktop.exe` slow to
  answer). It did not affect this run.
