# Billing projection checkpoint

Observed 2026-11-07, starting at `6528ccc08`, for draft PR #351 (stacked on
#349 and #350). This completes the projection/VM multiplier slice 2.1a, not
parent task 2.1 or the terms feature. D2a and D-a–D-e remain unchanged.

## Changed surface

- `MechanismRegistration.project_billing` is an optional mechanism-owned hook.
  The registry dispatches it and exposes an `agreed_price` convenience; missing
  projectors and unknown registrations fail closed. Reading an accepted option
  does not require current offer enablement/readiness.
- Installed Alkahest and once-only payments options explicitly project `total`;
  contact projects its rateless introduction as a whole. The payments adapter's
  strict parameter codec rejects rate/setup fields instead of assuming total.
  This does not implement hosted recurring mandates.
- VM buyer codecs and storefront policy/reference/final multiplier derivation
  receive billing projection from their composition. Exact multiplication uses
  one period for `per_period`, the agreed duration for `total`, and rounds upward
  once, with the existing uint256 refusal. Pure raw quote helpers retain their
  whole-term default; production selected-option calls resolve the installed
  mechanism. Existing flat/absolute quote truncation is unchanged.
- Proof-retention logic is extracted to `pricing_record.py` so composition can
  dispatch projections without an import cycle through the amount codec. Its
  data and deep-copy behavior are unchanged.

Core still does not parse any mechanism's period. Recovery/mandate readers and
buyer caps are deliberately not migrated before bound-evidence enforcement.
No accepted logs are rewritten and no current listing substitutes for evidence.

## First-use setup and replay

The prepared target is an invocation-local Python process owned by the driver's
checkout. The committed diagnostic uses deterministic development identities
and account fixtures from `codec_probe.py`; no secrets, persona login, external
seed state, deployment selector, server, browser, container or authority service
is required. It performs no approval I/O and leaves no resident process.

From a fresh checkout:

```sh
make dist-ci
(cd domains/vms/buyer && make reinit && \
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  uv run --frozen --no-sync python \
  ../../../openspec/changes/negotiate-open-ended-compute-terms/billing_projection_probe.py)
```

This exact first-use surface was executed. After the codec probe's four existing
PASS lines, it prints:

```text
installed once projection; absent projector and unsupported rate parameters refused: PASS
VM buyer codec and exact multiplier quote use one injected period, not horizon: PASS
upward final rounding and accepted per-period labels: PT15M=625000, PT1M=41667: PASS
LIMIT: no proof-binding enforcement, hosted rate materialization, approval or deployment
```

The proposed projection is installed through an injected registration in the
invocation, not through production configuration. The probe runs the real VM
amount codec at two horizons and the exact quote function; it does not prove a
rate Agreement can pass seller acceptance/materialization. The accepted-price
label is driven with fixture Agreement data. No permanent acceptance test was
added and no existing test assertion was weakened.

## Existing focused regressions

Run after `make dist-ci`; each package's `make reinit` (core uses
`python3 ../scripts/uv_project.py reinit`) installs its wheel-derived environment.

```sh
(cd kit/settlement-runtime && make reinit && uv run --frozen --no-sync pytest \
  tests/unit/test_configuration.py tests/unit/test_scalar_declaration.py \
  tests/unit/test_accepted_obligation.py -q)
(cd kit/alkahest && make reinit && uv run --frozen --no-sync pytest \
  tests/unit/test_settlement_config.py -q)
(cd kit/contact-exchange && make reinit && uv run --frozen --no-sync pytest \
  tests/unit/test_settlement_config.py -q)
(cd kit/arkhai-payments && make reinit && uv run --frozen --no-sync pytest \
  tests/test_agreement.py tests/test_buyer.py tests/test_settlement_config.py -q && \
  uv run --frozen --no-sync mypy src)
(cd domains/vms/storefront && make reinit && ENABLE_EVENT_QUEUE=true \
  AGENT_WALLET_ADDRESS='' uv run --frozen --no-sync pytest \
  tests/unit/test_vm_multiplier.py tests/integration/test_vm_multiplier.py \
  tests/unit/test_sync_negotiation_seller_round_hook.py -q)
(cd domains/vms/buyer && make reinit && \
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  uv run --frozen --no-sync pytest tests/test_negotiate_stage_dispatch.py \
  tests/test_buy_orchestrator.py tests/test_buyer_client.py \
  tests/test_buyer_client_resume.py -q)
(cd core && python3 ../scripts/uv_project.py reinit && \
  uv run --frozen --no-sync pytest tests/unit/test_rate_helpers.py \
  tests/unit/test_settlement_options.py -q)
```

Observed: runtime configuration **66 passed**; Alkahest configuration **84
passed**; contact configuration **37 passed**; payments focused **51 passed**;
VM storefront **19 passed**; VM buyer **45 passed**; core **21 passed**. Payments
mypy checks **22 source files**. Configuration/buyer/arithmetic suites are unit
level; the VM multiplier integration invokes runtime calls against real SQLite,
not an application HTTP client or deployed storefront. No application/deployment
integration result is claimed by those numbers.

## Corrections during first use

- The initial diagnostic fixture omitted required seller/pool identity. Adding
  those public fixture fields repaired the diagnostic; this was not a product defect.
- An existing helper caller caught a newly mandatory projector argument. The
  storefront helper now defaults to its installed registry projection; the
  focused suite was rerun and passes.
- An exploratory mandate-reader migration exposed an optional-asset typing error.
  That migration was removed from this slice entirely: reader migration waits for
  authenticated pricing evidence, as the prior checkpoint requires. No typing
  failure or incomplete mandate-reader migration is carried forward.
- One first regression command used `tests/unit` for the payments kit; its tests
  are directly under `tests/`. Corrected commands above passed.

## Repository gates and limits

`make check-packaging`, `make check-change CHANGE=negotiate-open-ended-compute-terms`
and `bunx @fission-ai/openspec@1.14.0 validate negotiate-open-ended-compute-terms --strict`
all passed. They checked wheel/lock/package architecture, comment hygiene and the
active change. This packet claims no full-suite or deployed E2E result.

Before 2.1b can establish acceptance binding, choose the carrier described in
`openspec/changes/negotiate-open-ended-compute-terms/design.md` under
“Acceptance-evidence binding question”. The current Agreement listing hash commits
a full seller database representation that the retained buyer subset/publication
cannot reconstruct, and resize's pricing pin is seller-local. Historical signature
verification alone would overstate acceptance binding. The recommended additive
signed-acceptance pricing pin is not implemented or silently assumed.

Parent 2.1 remains unchecked. Remaining work: carrier choice, seller-proof and
transcript-price enforcement, remaining both-domain reader/cap/check migration,
direct-read guard, then 2.2 onward in order. No deployment readiness, hosted rate
execution, live checkout, billing stop, independent implementation review,
promotion, archival, final rebase or ready-for-review state is claimed. No external
resources were started.
