# Triage — 140-validation — unbacked-bare-metal-listings

- **Validated commit:** `aa00b15fd4e43dff93b95eac6575856f2d906b01`
- **Reviewed commit (139-implementation):** `8ac56577379a50686e6cd6e45fb7c2f2ddeca215`
- **Commit waiver:** the commits differ by one commit, `aa00b15` "relock so make test
  leaves the locks unchanged", which touches only seven `uv.lock` files and changes no
  resolved name or version. The owner waived the same-commit rule ("Waive."), so this
  record and `139-implementation` are triaged as one round. Ledger: `139-implementation`
  / `commit`.

Result: passed — local, Helm, and pipeline (run 40009822297; e2e-vm 135 passed, e2e-bare-metal
51 passed, e2e-apicredits 1 passed and 3 skipped by `e2e_credits_payment_deal`'s own
readiness guards). No `V<n>` failure and no `## Environment` entry, so nothing to triage
as a finding.

Coverage gaps recorded, not findings: `e2e_pool_declared_modes` is in no lane's module
list; `e2e_bare_metal_unbacked_introduction` does not exist until Section 22, so no
end-to-end evidence yet covers unbacked bare-metal supply itself.

Observation about the validation tooling, presented with 139 F4 and not triaged against
this change: `check-locks` accepts locks that `uv sync` rewrites, and nothing pins a uv
version (`required-version`), so the lock churn recurs whenever contributors lock with
different uv releases. The owner raised exact pins on internal wheels in reply; after
discussion, no action on either ("No action needed on the uv-version idea").

Evidence for the round triaged in `139-implementation.triage.md`.
