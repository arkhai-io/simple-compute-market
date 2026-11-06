# Buyer numerical presentation and optional horizon checkpoint

Base: 59eec7967. Draft PR #351; stacked on #349/#350 unchanged.
This slice completes 4.1b only. Restart at 4.2; full mixed-listing first use,
affected app-integration/E2E validation, review and post-review closeout remain.

## Before and after

Before, VM commands refused a missing duration before recurring selection;
negotiation scaled units by lease hours and the shape codec evaluated
`int(duration_seconds)`. Bare-metal quoted and checked whole-term totals only.
Buyers exposed lifecycle rights but not numerical setup/reserve or effective
accepted horizon, and VM settlement recovery omitted pre-approval disclosure.

Now, mechanisms inject `present_payment`: a unit-bearing monetary quote, separate
setup once amount and initial reserve in that quote's asset/minor-unit scale.
The registry checks billing basis/asset and exact equality to any accepted
accessor quote. Neutral buyers never parse mechanism period/setup/reserve fields.
Missing presenters fail closed. Installed payments remain once-only; no deployed
rate servicing or setup mandate support is enabled by this presentation contract.

Fresh output names the derived class, quote unit, unchanged asking-rate unit,
setup, reserve (not spend or a loss cap), both listing bounds and requested
horizon. Omitted recurring horizons remain absent in provision intent; reserved
selections require an explicit duration, without a one-hour default. VM hourly
bounds scale over one billing period, never a recurring lease horizon; its shape
codec derives one period without converting a missing duration to int. Bare-metal
checks accepted monetary amount/asset/billing basis against the quote and holds
an explicitly requested duration unchanged.

Accepted output uses retained Agreement money/start/unrounded duration/end,
not current listing terms. VM `run_settle_from_log` renders it before dispatching
any approval effects. Bare-metal has no separate resumed-approval command; its
fresh accepted path renders the same shared rows. Existing lifecycle disclosures
and their authority/evidence limits are unchanged.

## Committed first-use setup

Target: invocation-owned, process-local diagnostics in this checkout, **not** a
Cloud deployment, running hosted payment lane or browser surface. Persona/auth:
public deterministic development fixtures; no secrets required. State: fresh
once and proposed recurring options, bounds, retained Agreement bytes; no
persistent state or destructive seeding. No inherited deployment selector is used.

Prepare the current wheels and locked environments from repository root:

```sh
make dist-ci
make -C domains/vms/buyer reinit
make -C domains/bare_metal/buyer reinit
```

Personally exercised entry points, directly opening each diagnostic surface:

```sh
(cd domains/vms/buyer && uv run --frozen --no-sync python ../../../openspec/changes/negotiate-open-ended-compute-terms/buyer_presentation_probe.py vm)
(cd domains/bare_metal/buyer && uv run --frozen --no-sync python ../../../openspec/changes/negotiate-open-ended-compute-terms/buyer_presentation_probe.py bare)
```

Readiness: locked imports and actual mechanism registry construction pass before
the replay. No authority, HTTP, site or deployed-service readiness is claimed.
The fixture explicitly injects a **proposed mechanism owner** for period/setup/
reserve interpretation; it does not modify installed compositions. Its two-period
initial reserve calculation is diagnostic data, not a frozen hosted mandate rule.

Both replays observe the same values:

```text
Class: on-demand
Selected price: 625000 minor units of USD/6 per_period (PT15M, 900 seconds)
Setup once charge: 750000 minor units of USD/6
Initial reserve: 1250000 minor units of USD/6; reserved funds, not spend or a loss cap.
Maximum duration: 86401 seconds
Available until: 2026-11-08T00:00:01Z
Requested horizon: Omitted; seller resolves the finite bound at the agreed start
Accepted price: 625000 minor units of USD/6 per_period (PT15M, 900 seconds)
Effective horizon: 43201 seconds (not rounded to periods)
Maximum accepted end: 2026-11-07T00:00:01+00:00
PROPOSED PRESENTATION PORTS ONLY: no live rate, mandate, approval or lease
```

Omitted, 1801-second and 43201-second requests all quote one 625000-unit period.
VM's multiplier codec agrees with that quote without requiring the horizon;
flat hourly bounds scale by 900/3600, not lease hours. Its interactive confirmation
labels the accepted quote per-period, not total. Bare-metal accepts the exact
per-period quote and rejects changed accepted money. Installed payments refuse
the proposed rate fields, and a missing presentation port refuses rather than
inventing numbers.

The VM diagnostic also calls the actual accepted recovery entry point, supplying
retained Agreement bytes and replacing only recovery loading/transport/effects
with controlled collaborators. This proves entry-point disclosure, **not** the
authenticity of that synthetic recovery fixture, live approval or provisioning.
Existing authenticated recovery tests remain the proof for retained evidence.
The disclosure helper ignores a deliberately changed/expired current-listing
argument and keeps the accepted price and 43201-second horizon unchanged.

## Focused validation

Existing tests only; no new permanent acceptance tests were added. The kept CLI
duration check now exercises nonpositive explicit duration rather than imposing
duration before selection. Two existing schema-opaque negotiation fixtures
explicitly omit the production mechanism acceptance callback because their
synthetic Alkahest-tagged parameters are not an escrow option; their selection-pin
and injected plan-validator assertions are unchanged.

Run pytest with `uv run --frozen --no-sync` in each package. Clear upper- **and**
lower-case HTTP/HTTPS/ALL proxy variables for buyer tests, so the real loopback
recovery test does not try to construct an inherited SOCKS proxy transport:

```sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync pytest tests -q
```

| Package | Existing target | Result |
| --- | --- | --- |
| Settlement runtime | `tests -q` | 175 passed |
| VM buyer | `tests -q` | 215 passed |
| Bare-metal buyer | `tests -q` | 32 passed |
| Core buyer | `tests/unit/test_orchestrator.py tests/unit/test_selected_option_negotiation.py -q` | 25 passed |
| Alkahest | `tests/unit/test_settlement_config.py -q` | 84 passed |
| Arkhai payments | `tests/test_settlement_config.py tests/test_agreement.py tests/test_buyer.py -q` | 51 passed |

Targeted mypy from settlement runtime passes for two source files:

```sh
uv run --frozen --no-sync --with mypy mypy --follow-imports=silent --ignore-missing-imports src/market_settlement_runtime/presentation.py src/market_settlement_runtime/buyer_terms.py
```

This is not repository-wide typing. `make check-packaging`,
`make check-change CHANGE=negotiate-open-ended-compute-terms` and pinned
`bunx @fission-ai/openspec@1.14.0 validate negotiate-open-ended-compute-terms --strict`
pass, including comment hygiene, import placement, citations and amount-read
classification. No production code depends on this change directory.
Initial implementation checks caught legacy raw-proposal unit conversion,
synthetic fixture boundaries, and the new amount-read classifications; these were
corrected and re-driven, not waived. The replay's initial incomplete VM listing
and recovery stub were corrected. No test assertion was weakened to accommodate
a product defect. No service, tunnel, browser page, container or external target
was started or left running.

Full CLI publication/selection first use remains 4.2. The affected application
integration/E2E lanes remain 4.3; no E2E lane or live recurring consumer was started
in this slice. Use the prescribed Podman provider and readiness gate there.
Promotion and archival remain post-review.
