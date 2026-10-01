# Hosted Stripe removal checkpoint

Task 3.2 is not complete. Package/domain and deployment cuts, typing repairs, restored regression coverage and targeted operator documentation are committed. Current hosted descriptions in permanent capability documents remain.

## Landed

- `aa97accd`: removed `kit/hosted-settlement`, core hosted transport and shared hosted routes, domain hosted authorization/routes/evidence/lifecycle and bare-metal funding commands; removed registrations, persistence wiring, obsolete tests and dependencies; refreshed locks. VM and API-credit payment composition is Alkahest-only. Bare metal retains `contact-exchange.v1`, its nonfinancial introduction mechanism, alongside Alkahest.
- `c39090ea`: removed Stripe-only Compose/config examples, protected workflows, credential/release tooling, manifests and Helm fixtures; updated schemas/values, package/release matrices and review scope.
- `f0f9e123`: passed the recorded buyer signer into the API-credit recovery-completion check.
- `aba7600e`: repaired the 28 changed-source typing findings. Mypy now passes all 42 listed source files.
- `9cbaf257`: restored/reframed neutral settlement acceptance, policy, clause ordering, startup/import boundaries, reconciliation, wheelhouse portability and Alkahest composition/publication coverage. Contact-exchange amountless acceptance coverage is retained. An AST comparison against starting ref `ab14c88039cd2413b8cf889d823a95e1d53895de` identified removed functions for review; hosted-only flows, migrations and release artifacts were not restored.
- `5683e63b`: targeted cleanup of README, buyer/seller quickstarts, bare-metal and API-credit seller guides, development architecture/config/testing/release docs and e2e role guidance. Hosted-specific setup and flows were removed, not translated into Arkhai payments credentials or operations.
- The domain-authoring guide's hosted-only conditional-settlement section is removed.
- No production package/module was generated. Surviving compositions and CLIs were simplified in place. No Arkhai payments registration was added; `kit/settlement-runtime` was not moved.
- The superseded-change index marks the six named hosted changes and hosted sections of `disburse-a-settlement-disposition`; their directories remain.

## Remaining

1. Targeted current-hosted documentation cleanup remains in `openspec/specs/README.md` and these capability documents: `test-compatibility` (spec/architecture), `market-composition` (spec/architecture), `storefront-publication` (spec), `settlement-servicing` (spec), `buyer-orchestration` (spec/architecture), `deployment-state` (spec/architecture), `marketplace-identity` (spec), `cli-query-language` (spec/architecture), `api-credits` (architecture), `negotiation-protocol` (spec), and `settlement-configuration` (spec/architecture). Delete only obsolete hosted sentences/sections; preserve neutral and Alkahest invariants. Use “Arkhai payments (arkhai.payments.v1)” where a peer mechanism belongs, without copying Stripe contracts into that mechanism. Broad spec rewrites and Section 4 promotion/roadmap remain parent-owned.
2. Finish sweep disposition. The required sweep was run; it is not zero. `kit/config/src/market_config/settlement_migration.py` retains deliberate rejection of old hosted configuration and a stale hosted-service environment docstring. Dependency-boundary tests intentionally forbid removed modules. Registry integration test names and one VM listing test option ID still use hosted/Stripe labels and need a fixture-semantic review. Active/superseded change documents legitimately retain old terms; their directories must remain.
3. No real registry/storefront/provisioner/payment deployment or full repository integration suite was run. Parent-owned Arkhai payments compositions, Agreement changes and runtime move still need integrated validation.
4. Once complete, remove this checkpoint and the typing-source sidecar and compress durable evidence into the one-line Section 3.2 task tick. Keep Section 3.2 unchecked until the remaining cleanup is done.

Replay the reference sweep:

```sh
rg -n -i 'stripe|hosted_settlement|fiat\\.stripe|hosted-settlement' \
  --glob '!openspec/changes/archive/**'
```

## What did not work

- Broad textual/AST deletion produced syntax errors, dangling names and collateral loss of mixed-container test coverage. Compile checks, typing repair and the removed-function audit guided repairs; do not repeat marker-based pruning.
- Broad documentation pruning lost unrelated text and examples and was reverted. The later operator-documentation commit removes hosted-specific sections instead; remaining normative documents need their own targeted pass.
- CLI tests initially consumed stale wheels. Affected packages were rebuilt into `.dist` and reinstalled non-editably before validation.
- API-credit service tests without `PYTHONPATH=src` stalled in TestClient startup; the corrected command passes.
- Helm had no selected local version; explicit `mise exec helm@3.15.3` worked.

## Validation

Latest affected regression run: **2251 passed, one skipped**; all 18 invocations exited zero.

| Package | Result |
|---|---|
| `core/buyer` | 109 passed, 1 warning in 0.76s |
| `core` | 91 passed in 0.28s |
| `core/storefront` | 150 passed in 1.10s |
| `kit/settlement-runtime` | 82 passed in 0.80s |
| `kit/config` | 121 passed in 0.65s |
| `kit/alkahest` | 179 passed in 1.13s |
| `kit/contact-exchange` | 37 passed in 0.35s |
| `domains/vms/buyer` | 180 passed in 0.80s |
| `domains/vms/storefront` | 895 passed, 1 skipped, 3 warnings in 11.44s |
| `domains/apicredits/buyer` | 16 passed in 0.58s |
| `domains/apicredits/storefront` | 66 passed, 4 warnings in 1.16s |
| `domains/apicredits` | 35 passed, 3 warnings in 29.79s |
| `domains/apicredits/service` | 32 passed, 3 warnings in 1.17s |
| `domains/bare_metal` | 60 passed in 0.37s |
| `domains/bare_metal/buyer` | 9 passed in 0.40s |
| `domains/bare_metal/storefront` | 92 passed, 1 warning in 4.06s |
| `scripts` | 78 passed in 2.54s |
| `e2e-tests` | 19 passed in 0.26s |

Run `.venv/bin/python -m pytest` from each package directory. Use `tests/unit` for core, core buyer/storefront, settlement-runtime/config/Alkahest/contact-exchange, VM/API-credit storefronts and e2e-tests; `tests` for domain/buyer packages and scripts. API-credit service uses `PYTHONPATH=src ../../../.venv/bin/python -m pytest src/tests -q --tb=short`.

Typing replay from repository root:

```sh
.venv/bin/mypy --ignore-missing-imports --follow-imports=silent \
  $(< openspec/changes/settle-through-arkhai-payments/remove-hosted-stripe-typing-sources.txt)
```

Result: no issues in 42 source files. The old failed diagnostic artifact is removed.

Passed: affected wheel builds/non-editable installation, Python compileall, changed-file Ruff F/I, Helm default/EVM/overlapping-identity structural renders, installed CLI help smoke checks, `git diff --check`, `make check-comment-hygiene`, and `openspec validate settle-through-arkhai-payments`.

Helm replay: `mise exec helm@3.15.3 -- bash helm/scripts/test-render.sh`.
CLI replay: `.venv/bin/market settlement --help`, `.venv/bin/market credits buy --help`, `.venv/bin/market bare-metal --help`. Settlement help advertises status and Alkahest, not Stripe.

Setup is local/disposable, installed from `.dist` wheels. No credentials, remote target or seeded seller state were prepared; no server remains running. Ignored wheel/environment state is not a deployment handoff; use existing package Makefile build/reinit targets for a fresh consumer environment. This checkpoint is not independent acceptance.
