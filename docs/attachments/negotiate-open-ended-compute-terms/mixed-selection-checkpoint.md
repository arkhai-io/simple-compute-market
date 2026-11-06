# Mixed-listing first use and integration checkpoint

Base: f396ec4e4; PR #351 remains stacked on #349/#350. Proposed contract first use is not a hosted rate deal.

## Committed setup

Target: checkout-owned, invocation-local ASGI storefront applications and real SQLite databases. Persona/auth: deterministic public development signers/accounts; no secrets. State: one freshly published bounded capacity identity per domain, with Alkahest reserved, hosted once, on-demand and spot options. No inherited deployment selector, persistent seed or installed recurring servicing is used.

Prepare from repository root:

```sh
make dist-ci
make -C domains/vms/buyer reinit
make -C domains/bare_metal/buyer reinit
make -C domains/vms/storefront reinit
make -C domains/bare_metal/storefront reinit
```

Personally exercised entry points:

```sh
(cd domains/vms/storefront && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync python ../../../openspec/changes/negotiate-open-ended-compute-terms/mixed_selection_probe.py vm)
(cd domains/bare_metal/storefront && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync python ../../../openspec/changes/negotiate-open-ended-compute-terms/mixed_selection_probe.py bare)
```

Readiness is authenticated typed system status before site projections/publication. The published option bytes and listing bounds reach each buyer's own locked interpreter. Actual Typer commands run from selection, with controlled identity/discovery and proposed mechanism billing/presentation/capability ports. VM stops immediately after selected disclosure; bare metal stops at its approval factory. Neither selection command reaches negotiation, approval or provisioning effects.

## Observed outcomes

Both commands select hosted reserved with explicit 3600 seconds and on-demand/spot with omitted or explicit 2401-second horizons. Default rights recommendations and authority checks run without a waiver. Output includes:

- reserved total 2500000; on-demand 625000 and spot 375000 minor units of USD/6 per PT15M (900 seconds);
- zero separate setup for these presets; diagnostic two-period reserve 1250000/750000, explicitly not spend or a loss cap;
- maximum 7200 seconds and absolute bound 2035-01-01T00:00:00Z;
- omitted horizon or exact 2401-second requested horizon;
- delivery deadline 1200 seconds after approval/start;
- payer started-period billing, term-end last-boundary billing, spot payee notice 120 seconds with last-boundary billing; on-demand penalty 15000000 in the quote asset; authority, dispute-window and retention limits.

VM also selects the published Alkahest option through its command and shows no delivery promise rather than refusing absent lifecycle. Both domains' shared default rights policy/disclosure admit that no-adapter option. Bare metal's payment purchase command has no installed Alkahest buyer stage: rights/disclosure only, not an Alkahest purchase claim or a new stage.

The same replay observes signed cached-option refusal with absent/wrong-revision/wrong-lane servicing declarations: signed 409/refetch, unchanged negotiation rows, publication retains reserved options and identity. Matching declarations restore recurring peers. Omitted/shorter horizons produce exact signed VM acceptance artifacts; bare-metal positive acceptance is a no-write opening-plan artifact, not rate mandate/capture. All existing publication/runway/penalty/treatment/setup diagnostics pass.

These are **proposed injected ports**, not hosted capabilities. The reserve calculation is diagnostic, not a frozen mandate rule. The [accepted presentation replay](buyer-presentation-checkpoint.md) covers retained accepted money/horizon and separate setup presentation. Installed recurring publication, approval, materialization, continuation and billing stop remain disabled.

## Existing regressions

Run from each package with `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync pytest`:

| Package | Targets | Result |
|---|---|---|
| VM storefront | `tests/integration/test_publication_loop.py tests/integration/test_pool_overrides_api.py tests/integration/test_listing_identity_carryover.py tests/integration/test_buyer_selection_negotiation.py tests/integration/test_payment_settlement.py -q` | 140 passed |
| Bare-metal storefront | `tests/test_http_negotiation.py tests/test_app_composition.py tests/integration tests/test_http_system.py tests/test_http_publication_rates.py -q` | 185 passed after explicit-duration fixture repair |
| Bare-metal storefront | `tests/integration/test_payment_settlement_client.py -q` | 16 passed after fixture repair |
| VM buyer | `tests -q` | 215 passed |
| Bare-metal buyer | `tests -q` | 32 passed |

The kept reserved purchase fixture relied on an implicit hour. It now requests its intended 3600 seconds explicitly; run-log reload, settlement, physical-window and teardown assertions are unchanged. No permanent acceptance tests were added or assertions weakened. `make check-packaging` passes, including wheel/lock/environment, architecture and amount-read checks. Initial replay attempts corrected diagnostic-only missing imports, an incomplete config double and an omitted top-level listing bound; both final replays pass.

## End-to-end readiness

No live deployment reached readiness. Attempted distinct checkout-owned projects `terms-12-vm` and `terms-12-bare` using committed lane files and the required provider. The default provider's unconfigured Docker Compose shim is avoided by this selector. `docker` itself is not installed, so the Makefile's hard-coded Docker entry point is unavailable.

Commands attempted from repository root, foreground, before any specs:

```sh
PODMAN_COMPOSE_PROVIDER="$(command -v podman-compose)" podman compose -p terms-12-vm -f compose.vms.yml -f compose.vms-local.yml -f compose.payments-double.yml -f compose.vms-lane.yml up --no-build
PODMAN_COMPOSE_PROVIDER="$(command -v podman-compose)" podman compose -p terms-12-bare -f compose.bare-metal.yml -f compose.dev.yml -f compose.payments-double.yml -f compose.bare-metal-local.yml up --no-build
```

Both exit 1 before a service starts:

- VM: `ValueError: Env file at <resolved-parent>/core/registry/.env.docker-compose does not exist`. Prefix redacted to avoid publishing a host filesystem path; exact message/suffix preserved. The file exists under this checkout's `core/registry`, but the provider resolves the included relative path outside the checkout.
- Bare metal: `RuntimeError: volume [domains/bare_metal/../../shared-env] not defined in top level` (exact exception).

VM listing shapes (`e2e_listing_shapes`, `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`), VM reserved compute (`e2e_deal`) and bare-metal reserved mock compute (`e2e_bare_metal_mock_deal`) are **unobservable/unrun**, not failed product scenarios or passing E2E evidence. No browser run follows failed readiness. Pipeline qualification remains outstanding.

The existing [Compose assembly gap](../../../openspec/changes/README.md#unowned-work-left-by-this-campaign) carries these reproductions. The tracker CLI was tried but reports `no supported tracker: canonical docs/issues/ absent`; repository rules use OpenSpec gaps rather than GitHub Issues for its own work. No separate GitHub issue was filed.

Cleanup used these exact projects' `down -v --remove-orphans`; bare metal's parser refuses cleanup for the same volume error. Label-filtered inspection confirms neither project owns containers, networks or volumes. No server, browser page, tunnel or external resource remains.
