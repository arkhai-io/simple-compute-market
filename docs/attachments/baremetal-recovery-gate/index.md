# Bare-metal Alkahest recovery gate — repair evidence

Scope: verify F1 and review F8 from the joined settlement closeout. Base: `49b9fff39c87a92b746f6c43279c01910a575436`; branch: `fix-baremetal`. Tested production revision: `f29d6a32`. Review F8 changes only tests and this packet. This is a controlled backend self-check, not independent acceptance or live chain/hardware qualification. Visual: false; screenshots: none.

## Setup

The target is this checkout's installed wheels and real storefront services with fresh temporary SQLite databases. Tests use synthetic EIP-191 buyer/seller principals and the existing injected chain verifier and site/provisioning boundary fixtures. No external credentials, inherited deployment selectors, shared databases or deployments are used. Build and reinit completed successfully; the verifier replay explicitly installs the storefront wheel non-editably. No server, container or browser was started.

From the repository root:

```sh
make dist
make -C domains/bare_metal/storefront reinit
uv pip install --python domains/bare_metal/storefront/.venv/bin/python --reinstall --no-deps .dist/arkhai_bare_metal_storefront-0.2.5-py3-none-any.whl
```

First-use entry (fresh persisted adoption, reopen, protected physical begin):

```sh
cd domains/bare_metal/storefront && uv run --no-sync pytest tests/test_http_settlement.py -k alkahest_recovery -q
```

## Verify F1 — held

`revalidate_alkahest` refuses reclaim in progress, succeeded or manual-required, any mechanism status other than ready, and non-pending collection. A materialized identity alone is not authority. Active journal recovery invokes the configured chain verifier with the persisted proposal, accepted amount/duration, listing and selected chain; its exact obligation index must match the adopted journal record. Missing chain resources and invalid authoritative evidence fail closed.

Proving tests in `tests/test_http_settlement.py`:

- `test_alkahest_recovery_refuses_non_active_journal_before_physical_effects`: seven persisted journal variants, followed by reopening SQLite and calling the production fulfillment service. Each refuses without a physical lifecycle row, reservation or begin call.
- `test_alkahest_recovery_rechecks_chain_before_physical_effects`: an active local journal does not authorize a revoked chain source, a different obligation index or a boolean index. Refusal leaves no lifecycle or physical effect. Restoring valid source verification permits recovery, and repeat begin retains one reservation and one fulfillment.
- The existing settlement restart/status check retains the normal idempotent response and now configures the chain authority and observes the second source verification. Its former single-call/no-chain expectation is intentionally replaced: recovery must not trust local adoption alone.

The audit's isolated reclaimed-journal diagnostic, rerun against the installed wheel, observed:

```text
refused= SettlementRequestError verified settlement is no longer active
```

The prior `reclaimed_journal_authorized_by_revalidation=True` observation is no longer produced. The isolated diagnostic has no chain or hardware effects; the production recovery tests prove the protected-effect boundary and authoritative-source check.

## Review F8 — held

Removed the literal seller-stage set assertion and the surrounding callable, non-None and capability-declaration assertions from `tests/test_domain_runtime.py`. The contract validation smoke, bare-metal codecs and accepted-artifact adapter checks remain; no replacement declaration-restating test was added. This intentionally removes assertions about the chosen declarations, not a production behavior or failure gate.

The domain-runtime and application-composition suites passed **11 checks** after this removal. The production recovery entry was also re-driven: **10 passed, 6 deselected**, and the non-editable installed-wheel reclaimed-state replay again refused with the same result above.

## Validation

- `make dist`, storefront `reinit`, non-editable storefront wheel install: passed.
- Affected HTTP settlement, fulfillment service and settlement-plan suites: **26 passed**.
- The existing 15-suite bare-metal focused group on the F1 revision: **90 passed**, including the ten new recovery cases.
- Final F8 domain-runtime/application-composition check: **11 passed**; final F1 recovery-only re-drive: **10 passed**. These are overlapping measurements, not additive counts.
- `make check-comment-hygiene` and `git diff --check`: passed. No new imports, dependencies or schema changes.

Reproduce affected suites:

```sh
cd domains/bare_metal/storefront
uv run --no-sync pytest tests/test_http_settlement.py tests/test_fulfillment_service.py tests/test_settlement.py -q
uv run --no-sync pytest tests/test_domain_runtime.py tests/test_app_composition.py -q
uv run --no-sync pytest tests/test_selection_dispatch.py tests/test_negotiation.py tests/test_domain_runtime.py tests/test_settlement.py tests/test_migrations.py tests/test_persistence.py tests/test_escrow_identity_backfill.py tests/test_fulfillment_service.py tests/test_site_clients.py tests/test_import_boundaries.py tests/test_http_settlement.py tests/test_http_negotiation.py tests/test_http_introductions.py tests/test_introduction_delivery.py tests/test_app_composition.py -q
```

Temporary test databases are owned and cleaned by pytest. All supervised commands finished; no external running resources remain. Shared closeout documents and permanent promotion are recorded in `openspec/changes/archive/2026-10-09-route-settlement-by-mechanism`.
