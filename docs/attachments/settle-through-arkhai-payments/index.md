# Payments verification

Base `5cfa48f1`; payment repairs `2a355383` (bare-metal typed amount comparison), `12575468` (API-credit canonical principal comparison), `26b0f71d` (registry 204 compatibility). Promotion compared against `e97b4b7a`. Visual: false; screenshots: none.

## Outcomes and limits

| Claim | Action and observed result |
|---|---|
| VM real-ledger receipt gate/restart/idempotency | **held**, inherited replay at `378e9a09`: approve → poll → verified receipt → provisioning; process exit 75 before provider dispatch; second process ready; repeated settle ready, deliveries=1 |
| Bare-metal real-ledger receipt gate/restart/idempotency | **held**: before approval settlement_pending and fulfillment rejected; buyer approves/polls; seller verifies receipt; exit 75 after selected-site scheduling/materialization before provider dispatch; second process active, domain receipt ready; repeated settlement and begin reuse identities, deliveries=1 |
| API-credit real-ledger receipt gate/restart/idempotency | **held**: before approval HTTP 202 and grants=0; approve/poll/verified receipt; exit 75 before issuance dispatch; second process commits a real credit-authority grant then exits 75 before storefront acknowledgement; third process ready with private credentials; repeated settlement equal, grants=1, balance=10 |

These are seeded accepted-Agreement library diagnostics, not complete publication/discovery/signed-negotiation CLI journeys or permanent acceptance tests. Payments use the actual local HTTP service and Podman Formance ledger. VM and bare-metal physical authorities/providers are controlled; there is no live hardware access, revocation, or post-provider-acceptance VM/bare-metal crash claim. API credits uses the actual SCM credits HTTP app, migrations, quota ledger and issuance authority, not a mocked issuer. Credentials are asserted, never printed. Production WorkOS auth, cash-provider funding, hold release/fees/disputes, full-deal qualification and physical teardown remain producer/system-lane boundaries.

## Regression counts

All below passed after `make dist`. Reproduce with plain bash `set -o pipefail; make -C <package> reinit test 2>&1 | tail -3`; VM unit count is in the full output before its integration summary.

| Suite | Passed | Skipped |
|---|---:|---:|
| core schemas (`make -C core test-core`) | 91 | 0 |
| core/buyer | 111 | 0 |
| core/storefront | 149 | 2 |
| kit/negotiation-runtime | 7 | 0 |
| kit/arkhai-payments | 7 | 0 |
| kit/alkahest | 179 | 0 |
| VM buyer | 180 | 0 |
| VM storefront unit | 895 | 1 |
| VM storefront integration | 152 | 0 |
| Bare-metal buyer | 9 | 0 |
| Bare-metal storefront (including repaired amount comparison) | 92 | 0 |
| API-credit buyer | 17 | 0 |
| API-credit storefront (including repaired principal comparison) | 70 | 0 |
| API-credit domain | 35 | 0 |
| API-credit service | 32 | 0 |
| Registry unit | 95 | 0 |
| Registry integration | 87 | 0 |
| Release/wheelhouse tooling | 80 | 0 |

Bare-metal buyer has no Makefile: `cd domains/bare_metal/buyer && uv sync --dev --find-links ../../../.dist && uv run --find-links ../../../.dist pytest -q`. API-credit domain has no reinit: use `make -C domains/apicredits test-domain`, not its aggregate test target. Core has test-core, not reinit. Count capture used tee outside pytest temporary roots because managed retained logs disappeared again; no raw runner transcript is committed. Reinit rewrote lock formatting/index URLs; that incidental churn was restored, not committed.

## Typing, packaging and documentation

- VM configured mypy: `cd domains/vms/storefront && uv run --find-links ../../../.dist --with mypy mypy src`. Current: **52 findings in 22 files, 67 source files checked**. Scratch worktree at `353776c3`, independently built wheels and reinit: **52 findings in the same 22 files, 64 checked**. Sorted path/message/code multisets after removing line numbers are identical; **introduced=0, resolved=0, pre-existing=52**. Only server/buyer-auth line offsets changed. Pre-existing codes: no-untyped-def 37, union-attr 6, arg-type 4, assignment 2, attr-defined 1, unused-ignore 1, unreachable 1. The check is not green; no suppressions or unrelated annotation repairs were added.
- Core configured typing and registry-client typing passed (5 source files each in this run). Payments kit typing passed (9 sources), upstream conformance vectors and generated-model freshness passed.
- Final `make dist` passed: **38 py3-none-any wheels**; payments wheel contains generated models, settlement_config.py and py.typed; no hosted-settlement wheel. `mise exec helm@3.15.3 -- make test-deployment-packaging` passed 80 release-tooling checks plus all 23 Helm structural assertions. No container-image deployment claim.
- The previous registry FastAPI 204-with-body collection failure at `core/registry/src/api/admin_routes.py:86` was pre-existing. Current locked FastAPI 0.123.5 did not reproduce it. The permitted one-line repair adds response_model=None; explicit FastAPI 0.115.8 integration rerun passed **87**, preserving HTTP 204 behavior.
- Strict change validation, all permanent-spec validation, and comment hygiene passed after the documentation corrections. [Accepted-decision comparison](decision-review.md) lists permanent destinations, the small Agreement/credit wording corrections, and the larger API-credit configuration implementation mismatch owned by [SCM #254](https://github.com/arkhai-io/simple-compute-market/issues/254).

## Real-ledger setup and readiness

Required/prepared target: local `/Users/mlegls/dev/arkhai/arkhai-payments`, unchanged source, checkout-owned compose project `payments-c5b735ea02d5`, Formance loopback `3168`, ledger `payments_dev`, payments HTTP `3180`. Development X-Account-ID auth: synthetic payer/payee ending 0011/0012, dispute authority 0013. No Cloud selectors or real funds. Existing idempotent seed and named volume reused without reset. Readiness observed: `podman info` reachable, exact compose container names, `/health` HTTP 200 with status ok. The trusted public receipt pin comes from the checkout's seed transaction before each new Agreement. Disposable receipt/operator keys are generated at launch, not recorded.

Start in a foreground managed process; poll Podman readiness because machine start may return early:

```sh
podman machine start
for i in {1..120}; do podman info >/dev/null 2>&1 && break; sleep 2; done
podman info >/dev/null || exit 1
cd ~/dev/arkhai/arkhai-payments
export FORMANCE_PORT=3168
bun run ledger:local
NODE_ENV=development PAYMENTS_PORT=3180 \
  ARKHAI_DISPUTE_AUTHORITY=00000000-0000-4000-8000-000000000013 \
  RECEIPT_SIGNING_KEY=$(openssl rand -hex 32) \
  DEV_OPERATOR_TOKEN=$(openssl rand -hex 24) bun run service
```

After `make dist`, run bare metal from SCM root (preserve the same state between processes):

```sh
state=$(mktemp -d)
uv run --project domains/bare_metal/storefront --find-links .dist \
  --with "$PWD/.dist/arkhai_bare_metal_buyer-0.1.4-py3-none-any.whl" \
  python docs/attachments/settle-through-arkhai-payments/bare_metal_smoke.py "$state" crash
# Expected exit 75.
uv run --project domains/bare_metal/storefront --find-links .dist \
  --with "$PWD/.dist/arkhai_bare_metal_buyer-0.1.4-py3-none-any.whl" \
  python docs/attachments/settle-through-arkhai-payments/bare_metal_smoke.py "$state" resume
rm -r "$state"
```

API-credit authority: this worktree owns loopback `3181` and disposable `.wm/credits-authority` state, quota resource credits-smoke=10000 units. A generated mode-0600 admin-key authenticates the typed issuance client; no committed credential. Start foreground:

```sh
mkdir -p .wm/credits-authority
uv run --project domains/apicredits/service --find-links .dist \
  python docs/attachments/settle-through-arkhai-payments/credits_authority.py .wm/credits-authority
```

Readiness observed: actual app lifespan complete and `/health` HTTP 200. Then run in a second process:

```sh
state=$(mktemp -d)
for phase in crash lost resume; do
  uv run --project domains/apicredits/storefront --find-links .dist \
    python docs/attachments/settle-through-arkhai-payments/api_credit_smoke.py \
    "$state" "$phase" .wm/credits-authority
  # crash/lost must exit 75; resume must exit 0. Stop on any other exit.
done
rm -r "$state"
```

The VM replay remains `vm_smoke.py` with the analogous crash/resume phases, `--project domains/vms/storefront --find-links .dist --with "$PWD/.dist/arkhai_vms_buyer-0.3.4-py3-none-any.whl"`. Diagnostic entries were opened/run here; state and generated credentials are reproducible, not inherited setup requirements.

Cleanup: stop both foreground services; `cd ~/dev/arkhai/arkhai-payments && FORMANCE_PORT=3168 scripts/ledger-local.sh down` stops only this checkout's containers and retains its named volume. The verification's services/containers and scratch baseline worktree are removed before handoff.

## Friction and failed attempts

- Bare metal initially rejected an accepted wire amount string against the stored integer; fixed with typed Agreement comparison, redriven and 92 regressions passed.
- API credits initially compared Agreement dictionary principals with Identity objects; fixed by canonical normalization, redriven and 70 regressions passed.
- Harness corrections: API-credit SQLite listing resources require decoding; its HTTP client needs explicit direct AsyncHTTPTransport because inherited SOCKS proxy configuration can require absent socksio. Payments loopback requests already disable environment proxy trust. One simultaneous reinit temporarily removed a dependency while the diagnostic imported it; sequential use eliminated that setup race. These are not product receipt/issuance failures.
- Managed process retention: existing issue `mlegls-pi/docs/issues/managed-process-retained-logs-disappear-during-test-run.md`; tee retained all suite counts here. Existing issue `mlegls-pi/docs/issues/managed-podman-start-exits-before-machine-remains-reachable.md`; readiness polling worked in this run.
- Helm shim had no selected version and its script suppressed the diagnostic. [SCM #253](https://github.com/arkhai-io/simple-compute-market/issues/253) records the observation and successful mise exec workaround.
