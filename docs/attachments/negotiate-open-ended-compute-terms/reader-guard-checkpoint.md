# Accepted price readers and direct-read guard

Observed 2026-11-07 from base `41ca62783`, draft PR #351. This completes 2.1c
and the quote/read boundary in 2.1, not the open-ended terms feature.

The direct-read guard this records was later removed by the owner's round-1
decision (record 01, R6); its script, inventory, `make` target and probe no longer
exist, and the sections naming them below describe the evidence as observed.

## Behavior

- Payments Agreement-to-mandate derivation and stored-mandate/buyer checks use
  the core quote with the installed payments projection. The once adapter
  requires an asset-bearing total and still refuses rate parameters.
- Bare-metal buyer quote checks and seller accepted dispatch/payment recovery
  use accessor money. VM amount/cap/reference derivation and signed pricing
  verification use the earlier projection/pin slices unchanged.
- Exact escrow recovery takes an explicit billing projector and refuses a
  per-period quote. VM and API-credit compositions supply Alkahest's projector.
  Accepted integer money never passes through run-log float summaries. The
  existing no-Agreement legacy fallback is unchanged.
- Alkahest's projector recognizes both existing acceptance shapes: published
  accepted-escrow wrappers and explicit negotiated EscrowProposal parameters.
  Neither admits lifecycle terms or unknown parameter shapes. The existing
  bare-metal signed HTTP settlement suite initially refused the explicit shape;
  after repairing the projector all 35 selected scenarios pass.
- The AST guard inventories every production amount attribute/mapping/reflection
  read without trusting receiver names/types. It covers key/getter/reflection
  aliases and wrappers containing reads. Exact path, function, expression,
  occurrence count and reason were recorded in the guard's JSON inventory;
  unknown reads, changed counts and stale entries fail. New untracked production
  files are included. The only raw Agreement read outside the accessor is generic
  negotiation's equality check against codec-derived expected money, not financial
  interpretation. Other entries classify quote, obligation, event, resource,
  wire-parser and proposal-scalar reads.
- The guard's `make` target ran in packaging and change checks. This
  syntactic repository rule is not a proof about runtime-generated Python or an
  authentication boundary.

## First-use setup and replay

The owned target is an invocation-local process in the verifier's checkout.
The committed probes use existing deterministic development identities/accounts;
never use them on a public network. No secrets, login, ignored seed files,
external authority or resident server is needed. Temporary guard fixtures are
removed on exit. These entry points were personally executed:

```sh
make dist-ci
(cd domains/vms/buyer && make reinit && uv run --frozen --no-sync python ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/consumer_price_probe.py)
(cd domains/vms/buyer && uv run --frozen --no-sync python ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/acceptance_pin_probe.py)
```

The reader probe derives/re-verifies a once mandate with exact `2**100 + 1`
minor-unit money, beyond float precision but within payments' 38-digit limit.
Escrow recovery preserves it and refuses missing/per-period projections. Changed
Agreement money and unsupported hosted rates are refused. The guard probe
exercises declaration/write/serialization positives, rejected reads through
attributes/mappings/wrappers/aliases/reflection, count drift, stale entries and
new-file scanning. The acceptance probe replays historical proof and immediate/
continuation acceptance recovery for 5,000,000 total and injected PT1M 41,667
per-period pricing. These are temporary change diagnostics, not collected
permanent tests or deployed recurring materialization.

## Existing regression and typing evidence

After rebuilding wheels and refreshing each package with its declared `make reinit`
(core instead uses `uv run --frozen --find-links ../.dist`):

| Package | Existing selected tests | Result |
| --- | --- | --- |
| `kit/arkhai-payments` | `tests/test_agreement.py tests/test_buyer.py tests/test_seller.py` | 52 passed |
| `domains/bare_metal/storefront` | `tests/test_selection_dispatch.py tests/test_http_settlement.py` | 35 passed |
| `domains/bare_metal/buyer` | `tests/test_cli_completion.py tests/test_run_log_recovery.py` | 16 passed |
| `core/buyer` | `tests/unit` | 168 passed |
| `domains/vms/buyer` | `tests/test_resume_helpers.py tests/test_buy_resume_cli.py tests/test_vm_settlement_helpers.py tests/test_negotiate_stage_dispatch.py tests/test_buy_orchestrator.py` | 51 passed |
| `kit/alkahest` | `tests/unit/test_settlement_config.py` | 84 passed |
| `core` | `tests/unit/test_rate_helpers.py tests/unit/test_settlement_options.py ../scripts/tests/test_check_change.py` | 42 passed |
| `domains/apicredits/buyer` | `tests/test_settle_credentials.py tests/test_buy_selection.py` | 7 passed |

Run selected tests from the package with `uv run --frozen --no-sync pytest <files> -q`.
For HTTP/in-process buyer/storefront tests clear inherited proxy variables using
`env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy`.
Core buyer emits the existing retired-identity serialization warning; API-credit
buyer emits existing model/schema serialization warnings.

Payments `uv run --frozen --no-sync mypy src` checked 22 files. Targeted VM typing:
`uv run --frozen --no-sync --with mypy mypy --follow-imports=silent --ignore-missing-imports src/arkhai_vms_buyer/pricing_record.py src/arkhai_vms_buyer/settlement_stages.py`
checked 2 files with imported code followed silently. Packaging, architecture,
locks, guard, comment hygiene, change checks and pinned strict OpenSpec validation
passed with `make check-packaging` and `make check-change CHANGE=negotiate-open-ended-compute-terms`.

Kept tests retain their assertions: the core exact-money fixture supplies a total
projector; the bare-metal command fixture names the required payee. Change-check
command expectations include the guard. No permanent tests were added or assertions
weakened. Initial probe fixtures assumed a nonexistent once-part `terms` wrapper
and an amount above payments' 38-digit range; corrected fixtures use the real wire
shape and valid exact amount. Initial commands guessed nonexistent test files or
a core `reinit` target; the paths and recipes above are the passing corrections.

## Incidental confirmation repair

The VM confirmation treated accepted monetary totals as hourly rates and scaled
by duration again. The installed once mechanisms now show that total unchanged;
resumed escrow display labels it total and reads exact accepted money through the
projector. This is a small price-display repair, not completion of 4.1's lifecycle
and recurring disclosure. The consumer probe above now drives the real Rich
confirmation with a two-hour 5,000,000 total, verifies the displayed payment remains
5,000,000 and declines without an effect. Existing VM buyer
`tests/test_buy_orchestrator.py tests/test_buy_pricing_and_filters.py tests/test_resume_helpers.py tests/test_buy_resume_cli.py`
pass **54 tests**; packaging and change checks pass again.

## Limits

No deployed E2E, live checkout/approval, hosted recurring mandate, billing stop,
independent review, final rebase, promotion or archive is claimed. PT1M is injected.
Listing bounds, option publication, servicing doors, horizon acceptance and full
CLI disclosure remain in 2.2 onward. No external resources or servers were started.
