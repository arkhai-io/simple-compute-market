# Confirmation findings N1–N3

## Revision and setup

- Reviewed base: `7c303dba1`.
- Repair revision: `fd85d9873` on worker branch `fixH`.
- Required and prepared environment: local Python library/in-process VM storefront
  integration, with SQLite databases owned by each test's temporary directory.
  No hosted deployment is required or claimed.
- Personas: the existing deterministic development buyer, seller and site
  identities from the integration fixtures; never use these on a public network.
  Negotiation capture receives the authenticated-middleware context. Payment and
  dispute services use the existing contract fakes; no external credentials.
- State: the kept fixtures create an accepted deal, verified payment commitment
  and controlled VM delivery. The concurrency check owns an independent SQLite
  writer; recovery uses signed site reports and reconstructs the composition.
- Readiness observed: `make dist-ci`, package reinitialization, all 63 servicing
  tests and all 28 focused VM integration tests passed before repository gates.
- This is nonvisual API/library evidence; no screenshots or resident servers.

## Reproduction entry point

Run from a clean checkout of the repair revision. The package reinitialization
steps install internal wheels built from that checkout rather than relying on
another worktree's environment.

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist-ci
make -C kit/deal-servicing test typecheck
make -C domains/vms/storefront reinit
(
  cd domains/vms/storefront
  ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' \
    uv run --find-links ../../../.dist pytest -q \
      tests/integration/test_lifecycle_database_execution.py \
      tests/integration/test_lifecycle_cycle.py \
      tests/integration/test_payment_settlement.py
)
```

These commands were run locally and reach each changed library surface directly;
there is no browser/deployment startup or menu-navigation dependency.

## Claims and observations

| Finding | Action and before-repair sensitivity | Repaired observation |
| --- | --- | --- |
| N1 | The kept correction-ordering test records an earlier pending `release_failed` site report and a later seller provisioning failure in both arrival orders, then replays them through reconstructed SQLite sessions. Before repair, report-first produces `assert 0 == 1` for the filing count; the other eight correction tests pass. | Both pending-source orders retain exactly one filing through replay. The asynchronous seller read exposes that same filing as pending beside the earlier report's end attribution. Classified-source cases still suppress a later filing, while genuinely earlier late failure evidence retains its required revision. |
| N2 | The kept independent-writer check calls real VM negotiation acceptance capture while another SQLite connection owns the write lock. Before repair, the writer's bounded release wait returns false: `SQLite blocked the event loop from releasing an independent writer`. | The event loop releases the independent writer before its timeout. Capture completes and retains both buyer and seller envelopes plus the accepted mandate's expiry. Existing cycle and interruption cases still pass. |
| N3 | The kept history-recovery check asserts the ingested later report's cause, for both complete pull and partial push. Before repair both cases report `release_failure` instead of `release_failed`. | Both cases retain the producer's `release_failed` vocabulary, reconcile both signed reports and stop polling only after history recovery, including after reconstruction. |

Regression sources:

- [Correction ordering and seller read](../../../kit/deal-servicing/tests/integration/test_correction_adoption.py)
- [VM database execution](../../../domains/vms/storefront/tests/integration/test_lifecycle_database_execution.py)
- [VM history recovery](../../../domains/vms/storefront/tests/integration/test_lifecycle_cycle.py)

## Validation

- Servicing: **63 passed**; mypy: **11 source files**, no issues.
- VM lifecycle database, cycle and payment-settlement integration: **28 passed**.
- `make check-architecture`: **passed**.
- `make check-packaging`: **passed**, rebuilding the wheelhouse.
- `make check-locks`: **passed**.
- `make check-comment-hygiene`: **passed**.
- `bunx @fission-ai/openspec@1.14.0 validate agreed-evidence-and-early-termination --strict`:
  **passed**. Validation is scoped to this agreed change. An exploratory `--all`
  run also visited unrelated draft changes and returned 86 valid / 18 invalid
  items (missing draft deltas and retained-scenario omissions); it is not a
  claim that every active proposal is implementation-ready.
- Full shim-backed `make test` on `fd85d9873`: **passed in 7m54s**.
  This includes VM unit **1196 passed / 1 existing optional skip**, VM integration
  **524 passed**, the kit suites and their typing checks, provisioning, domain,
  release-tooling and Helm structural/render checks.
- `git diff --check`: **passed**. No owned server, container, tunnel or browser
  page remains running; no remote deployment was started.

Full qualification entry point, after the focused commands above:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make check-architecture
make check-packaging
make check-locks
make check-comment-hygiene
bunx @fission-ai/openspec@1.14.0 validate agreed-evidence-and-early-termination --strict
eval "$(~/.local/share/simple-compute-market/podman-shim/setup)"
make test
```

The repair adds no authority/financial policy or accepted known limit. Permanent
promotion and change-wide archival remain the owner's existing section 16 work.
