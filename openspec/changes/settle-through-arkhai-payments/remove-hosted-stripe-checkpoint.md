# Hosted Stripe removal checkpoint

Task 3.2 is not complete. Package/domain and deployment cuts are committed; documentation cleanup and typing remain.

## Landed

- `aa97accd`: removed `kit/hosted-settlement`, core hosted transport and shared hosted routes, domain hosted authorization/routes/evidence/lifecycle and bare-metal funding commands; removed registrations, persistence wiring, obsolete tests and dependencies; refreshed locks. VM and API-credit payment composition is Alkahest-only. Bare metal retains `contact-exchange.v1`, its existing nonfinancial introduction mechanism, alongside Alkahest.
- `c39090ea`: removed Stripe-only Compose/config examples, protected workflows, credential/release tooling, manifests and Helm fixtures; updated schemas/values, package/release matrices and review scope.
- `f0f9e123`: passed the recorded buyer signer into the API-credit recovery-completion check.
- No new package/module was generated. Surviving compositions and CLIs were simplified in place. No Arkhai payments registration was added; `kit/settlement-runtime` was not moved.
- The superseded-change index marks the six named hosted changes and hosted sections of `disburse-a-settlement-disposition`; their directories remain.

Starting ref: `ab14c88039cd2413b8cf889d823a95e1d53895de`. Implementation changes 257 files: 8,515 insertions and 57,792 deletions, including lock refreshes.

## Remaining

1. Remove current hosted/Stripe descriptions from quickstarts, development docs, the e2e role guide and owning permanent capability docs. Broad Markdown pruning was restored to the starting ref because it removed unrelated explanations and mixed Alkahest examples. Only the hosted-only credential document is deleted. Section 4 promotion/roadmap remains parent-owned.
2. Repair typing: 28 findings across 14 changed-source files. Exact diagnostics: [remove-hosted-stripe-typing.txt](remove-hosted-stripe-typing.txt); inputs: [remove-hosted-stripe-typing-sources.txt](remove-hosted-stripe-typing-sources.txt). Failures include Literal defaults/BaseModel schema overrides, dynamic configuration sections, optional trust/chain values, CLI tuple/list inference and escrow amount types. They have not been demonstrated to be baseline-only. A six-file check following imports also fails in shared clauses/configuration; no green typing claim is made.
3. Check regression retention. Marker-based AST pruning removed enclosing test functions/classes referencing deleted hosted behavior and can discard unrelated cases in mixed containers. Surviving regressions passing does not prove coverage retention.
4. Finish the reference sweep. Unsupported-config rejection and dependency-boundary assertions deliberately name removed modules. Inert buyer-profile authority bindings and signed API-credit issuance evidence remain; avoid deleting shared identity/issuance support solely by keyword.
5. Re-run relevant integration/packaging checks after repairs. No real registry/storefront/provisioner/payment deployment or full repository integration suite was run.

## What did not work

- Broad textual/AST deletion produced syntax errors and dangling names. Compile and surviving regressions guided repairs; the partial commits now compile.
- Broad documentation pruning lost unrelated text and examples; it was reverted.
- CLI tests initially consumed stale wheels; affected packages were rebuilt into `.dist` and reinstalled non-editably before the latest runs.
- API-credit service tests without `PYTHONPATH=src` stalled in TestClient startup; the corrected command passed 32 tests.
- Helm had no selected local version; explicit `mise exec helm@3.15.3` worked.

## Validation

Latest surviving regressions: **1,970 passed, one skipped**.

| Package | Passed |
|---|---:|
| VM buyer | 170 |
| VM storefront | 863 (one skipped) |
| API-credit buyer / storefront / domain / service | 15 / 60 / 26 / 32 |
| Bare-metal buyer / storefront / domain | 9 / 92 / 60 |
| Config / settlement-runtime / Alkahest | 108 / 75 / 179 |
| Core buyer / core | 97 / 91 |
| Scripts / e2e unit | 74 / 19 |

Run `.venv/bin/python -m pytest` from each package directory: `tests/unit` for VM/API-credit storefronts, config, settlement-runtime, core buyer, core and Alkahest; `tests` for domain/buyer packages and scripts; `tests/unit` for e2e-tests. API-credit service uses `PYTHONPATH=src ../../../.venv/bin/python -m pytest src/tests -q --tb=short`.

Passed: affected wheel builds and non-editable installation, Python compileall, changed-file Ruff F/I, Helm default/EVM/overlapping-identity structural renders, `git diff --check`, `make check-comment-hygiene`.

Helm replay: `mise exec helm@3.15.3 -- bash helm/scripts/test-render.sh`.

Installed first-use smoke checks passed: `.venv/bin/market settlement --help`, `.venv/bin/market credits buy --help`, `.venv/bin/market bare-metal --help`. Settlement help advertises status and Alkahest, not Stripe.

Typing replay from repository root:

```sh
.venv/bin/mypy --ignore-missing-imports --follow-imports=silent \
  $(cat openspec/changes/settle-through-arkhai-payments/remove-hosted-stripe-typing-sources.txt)
```

Setup is local/disposable, installed from `.dist` wheels. No credentials, remote target or seeded seller state were prepared; no server remains running. Ignored wheel/env state is not a deployment handoff; use existing package Makefile build/reinit targets for a fresh consumer environment. This checkpoint is not ready for independent acceptance.
