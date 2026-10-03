# Payments verification checkpoint

Starting revision: `b22b953f`. Storage convergence: `ad260371`. Import relocation: `b6f53da8`.

## Scope and observations

Real-ledger VM story: **held** for approve/poll/receipt gate, repeated settle, and a process restart before provider dispatch. Bare-metal and API-credit real-ledger stories: **unobservable** (not yet driven). Visual: false; screenshots: none.

- VM and bare-metal mandates now load only from `negotiation_threads.settlement_data`. Ordered domain migrations transfer absent shared data and remove duplicate mandate columns. Receipt evidence remains domain-owned.
- VM storefront: 895 unit passed, one skipped; 152 integration passed after storage convergence and import relocation. Bare-metal storefront: 92 passed after convergence.
- Focused checks before import relocation: core schemas 91, Alkahest 179, negotiation-runtime 7, payments kit 7, core buyer 111, core storefront 149 (two skipped), VM buyer 180, API-credit domain 35, service 32, storefront 70, buyer 17; release tooling 80 passed. `make dist` built portable wheels.
- After import relocation: VM buyer 180, API-credit storefront 70 and buyer 17 passed. Hoisting `chain_by_name` by value broke the existing monkeypatch seam; importing its owning module at scope preserves late lookup and restored the suite. No import cycle was found.
- `make -C core typecheck` passed (core 9 files; registry client 5). Payments kit's configured mypy, generated-model and upstream-vector checks passed.
- VM storefront configured mypy (`uv run --with mypy mypy src` from the package) reported 52 errors across 22 files, checked 67. Errors are chiefly missing annotations, plus existing Optional/Identity/Response typing. Baseline comparison and repair remain required; this is not a passing typing check.

## Real-ledger setup

Local checkout `/Users/mlegls/dev/arkhai/arkhai-payments`, unchanged source. Podman compose project `payments-c5b735ea02d5`, Formance on loopback `3168`, named ledger `payments_dev`; HTTP service on `3180`. Development `X-Account-ID` auth with synthetic payer/payee ending `0011`/`0012`; dispute authority ends `0013`. No Cloud target or real funds. The service used disposable receipt and operator credentials, not recorded here. The checkout-owned containers and foreground service were stopped at checkpoint; the named volume remains. `/health` returned `{"status":"ok"}` after setup. Public identity pin is read from that checkout's seed transaction before testing new agreements.

`smoke_common.py` and `vm_smoke.py` are diagnostic replays, not permanent acceptance tests. VM delivery is an injected controlled selected-site provider, not a real VM. The VM replay uses two separate Python processes and exits with code 75 after receipt verification records provisioning but before provider dispatch. Observed: approval → poll → receipt verified → provisioning; first process exited 75 before dispatch. A second process loaded the same database, reached ready, and repeated settlement returned ready with deliveries=1. This establishes restart before the first physical effect, not crash recovery after a provider has accepted a VM.

Start the existing checkout-owned ledger and service in one managed process (the final command stays in the foreground):

```sh
podman machine start
cd ~/dev/arkhai/arkhai-payments
export FORMANCE_PORT=3168
bun run ledger:local
NODE_ENV=development PAYMENTS_PORT=3180 \
  ARKHAI_DISPUTE_AUTHORITY=00000000-0000-4000-8000-000000000013 \
  RECEIPT_SIGNING_KEY=$(openssl rand -hex 32) \
  DEV_OPERATOR_TOKEN=$(openssl rand -hex 24) bun run service
```

Before rerunning, confirm this absolute checkout remains the intended owner of compose project `payments-c5b735ea02d5`; do not inherit Cloud selectors or reset its volume. The seed is idempotent. After verification, `scripts/ledger-local.sh down` stops this checkout's containers without deleting state; stop the foreground service too.

Runnable VM entry point from SCM's repository root, after `make dist` and that ledger/service setup:

```sh
state=$(mktemp -d)
uv run --project domains/vms/storefront --locked --find-links .dist \
  --with "$PWD/.dist/arkhai_vms_buyer-0.3.4-py3-none-any.whl" \
  python docs/attachments/settle-through-arkhai-payments/vm_smoke.py "$state" crash
# Expected exit 75; preserve state for the second process.
uv run --project domains/vms/storefront --locked --find-links .dist \
  --with "$PWD/.dist/arkhai_vms_buyer-0.3.4-py3-none-any.whl" \
  python docs/attachments/settle-through-arkhai-payments/vm_smoke.py "$state" resume
rm -r "$state"
```

## Remaining

- VM real-ledger replay passed after repairing buyer mandate unwrapping. Extend the crash point if post-provider-acceptance recovery is required; the observed crash precedes dispatch.
- Bare-metal and API-credit real-ledger approval, receipt gate, repeated settlement and process-restart smokes; explicitly distinguish real ledger/credit authority from controlled hardware providers.
- Finish configured typing, compare/repair its base failures without weakening checks. Run packaging/wheel checks and registry integration collection (known FastAPI 204-with-body failure at `core/registry/src/api/admin_routes.py:86`; only repair if one line).
- Review the accepted decisions against owning permanent specs/architecture for 4.3; sibling owns promotion. 4.1 and 4.3 remain unchecked.

## Friction

- Managed process retention lost logs for some storefront test runs. Workaround: tee into a worktree-owned file; issue: `mlegls-pi/docs/issues/managed-process-retained-logs-disappear-during-test-run.md`.
- `podman machine start` in a standalone managed process appeared successful but its machine did not remain reachable afterward. Keeping startup, ledger setup and HTTP server in one live managed process worked. Cause is not established; issue: `mlegls-pi/docs/issues/managed-podman-start-exits-before-machine-remains-reachable.md`.
- Make targets differ: core has `test-core`, not `reinit`; VM buyer `build` makes a PyInstaller binary, not its wheel. Use `uv build --wheel --out-dir .dist domains/vms/buyer` for the diagnostic's wheel.
- Diagnostic readiness initially inherited a SOCKS proxy; loopback requests use `trust_env=False`. The generated receipt Identity and Agreement's dictionary principals require explicit wire conversion. These were harness errors, not product failures.
