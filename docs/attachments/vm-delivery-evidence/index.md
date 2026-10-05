# VM verified-facts delivery — implementation self-check

Tested implementation: `645a8a32` (main refactor `f9f56eea`). Scope: tasks 2.4–2.5 of `route-settlement-by-mechanism`. This is checkout-local wiring evidence, not independent acceptance or live payment/VM qualification. Promotion remains in 2.6.

## Setup and replay

Required/prepared target: the `vm-delivery-evidence` worktree of simple-compute-market, based on `bd51e317`. No remote deployment or inherited selector is used. Internal dependencies are built into `.dist` and reinstalled through the storefront's `reinit`; no editable sibling packages are injected. The example owns a fresh temporary SQLite database and deterministic Ed25519 buyer, seller and trusted-payment-service personas. Payment HTTP and physical delivery are controlled in-process. No credentials or external services are required.

From the repository root, this prepares and opens the story surface:

```sh
make dist && make -C domains/vms/storefront reinit && uv run --project domains/vms/storefront --locked --find-links .dist --with "$PWD/.dist/arkhai_vms_buyer-0.3.4-py3-none-any.whl" --with "$PWD/.dist/arkhai_kit_arkhai_payments-0.1.0-py3-none-any.whl" python domains/vms/storefront/examples/payment_smoke.py
```

Readiness is successful in-process composition and signed settlement requests, not a deployed-service probe. The example cleans its database and coordinator automatically. Databases containing the former `vm_payment_records` schema require an explicit reset; replay uses a disposable database and adopts no historical payment escrows.

## Observations

- Before approval: `pending`, zero deliveries. After approval: `provisioning`. After the owned task completes, retry: `ready`, exactly one delivery. SQL inspection: zero `escrows` rows.
- The delivery double invokes the real VM planner with verified evidence. It decodes the accepted provision envelope and reads the frozen VM facts; no mechanism switch or escrow lookup supplies authorization or lease bytes.
- Existing recovery cases reopen a real SQLite database, reuse the immutable request/site and durable physical identity, and poll without scheduling or beginning a replacement. Changed physical-result identities are rejected.
- The selected seller entry owns source revalidation, attestation reconciliation and claim binding. Continuations are reconstructed from exact accepted Agreement state, never persisted as callables. Foreground delivery and recovery use negotiation-scoped checkpoints and expiring claims directly; the escrow-coordinate repository adapter and escrow-context discovery fallback are removed.
- An ambiguous Alkahest submission stays query-only. Reading a physical result does not erase the submission-intent checkpoint. The pinned SDK still has no supported attestation-discovery query: ambiguous recovery remains pending/operator-visible rather than blindly resubmitting.
- Invalid authorization is rejected before physical failure policy. Actual provider failure is routed to the selected entry's existing failure policy; Alkahest keeps genuine escrow/obligation state and payment creates neither.

## Validation

After `make dist` and storefront `reinit`:

```sh
cd domains/vms/storefront
ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' uv run --no-sync pytest tests/unit/test_vm_fulfillment_planner.py tests/unit/test_fulfillment_provisioning.py tests/unit/test_fulfillment_resume_runtime.py tests/unit/test_fulfill_vm_obligation_error_handling.py tests/unit/test_fulfillment_reconciliation.py tests/unit/test_settlement_composition.py tests/unit/test_fulfillment_service.py tests/unit/test_domain_runtime_wiring.py tests/unit/test_architecture_imports.py tests/unit/test_settlement_start_authority.py tests/unit/test_migrations.py tests/unit/test_failure_policy.py tests/integration/ -q
```

Final result: **233 passed**. This includes the existing typed storefront-client integration suite. Ruff unused/import checks and formatting, comment hygiene, and strict change validation passed. No storefront static Make target is declared; no full repository suite or live payment/hardware lane was run. No permanent tests were added. Existing cases were adapted for the evidence contract, including replacing unknown-mechanism planner rejection with unverified-evidence rejection and changing malformed authorization from physical compensation to fail-before-effect behavior.

The final controlled example prints:

```text
before approval: pending deliveries: 0
after approval: provisioning
retry: ready deliveries: 1
payment escrow rows: 0
```

An extra temporary real-SQLite diagnostic observed provider failure, one failure-policy invocation, and zero replacement starts. Initial adaptation failures were missing fixture context/accepted-source state. Flat provision fixtures hid an incorrect SSH-field decoder; extending the smoke through the planner exposed it; the planner now uses the domain's provision-envelope decoder. One validation command named the nonexistent `test_failure_actions.py`; it ran no tests and was replaced by the existing `test_failure_policy.py`.

Process completion notices intermittently could not read logs; direct retained-path inspection recovered the counts. Existing owner: [mlegls-pi process-log issue](~/dev/mlegls-pi/docs/issues/managed-process-retained-logs-disappear-during-test-run.md). Observation recorded in that repository at `86a62a2`.

No screenshots apply. No server, container, tunnel, browser page or external resource remains running. Permanent destinations remain `openspec/specs/vm-storefront-fulfillment/{spec.md,architecture.md}` and `openspec/specs/physical-provisioning/{spec.md,architecture.md}` after review in 2.6.
