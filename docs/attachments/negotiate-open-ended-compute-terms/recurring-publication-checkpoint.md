# Recurring-publication checkpoint

Observed from base 4be6803d4, draft PR #351. This slice completes task 2.3's
publication contract and injected qualification, not live recurring servicing.
Resume at 3.1.

Three behaviours this records were replaced before the change landed: bare metal's
`pricing.bare_metal.settlements` hint by the shared clause tiers, its reserved hold by
no relative limit, and the refused fractional default by flooring; see
`openspec/specs/storefront-publication/spec.md`, "Compute settlement clauses resolve
from one shared source" and "Unbounded recurring candidates close independently". The
sections below describe the evidence as observed.

## Behavior and ownership

- A structured settlement clause may carry recurring with period,
  reserve_ahead_seconds, optional positive setup_amount, payer notice
  (default zero), optional payee notice, payee/term-end treatment and optional
  canonical minor-unit penalty. Omission keeps once publication. Separate
  clauses price separate entitlement combinations on the existing capacity/shape
  identity; no stored class or publication dimension is added.
- The neutral helper contract is in
  [rate_publication.py](../../../kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py).
  An installed helper supplies a unit-bearing quote, parsed period, approval
  window, adjudication and mechanism capabilities. Derivation checks the
  authority against the composition's offered advertisement, computes the
  payer-only default penalty as 24 periods' quoted price (explicit zero opts
  out), derives the unrounded finite default horizon and checks its runway.
  The shared lifecycle codec validates supported treatments and authority
  minima. The encoder cannot replace the resolved rights, mechanism, asset,
  period or reserve. No hosted helper is installed by this slice.
- Unsupported returned treatment and unvendored setup produce named omissions.
  An unbounded/sub-period/no-runway candidate is omitted with diagnostics.
  Valid reserved peers remain; a candidate with no options follows the existing
  no-settlement-option close path, not an unknown-mechanism hold.
- Both compositions expose an effective pool-facts reader keyed by site/pool.
  Once and recurring hosted options take its delivery deadline, not a raw clause
  value. VM's direct option reconciliation supplies the persisted bounds and
  binding's pool too, so it does not accidentally drop recurring peers or their
  deadline while refreshing readiness. The renewable dependency has not supplied this port on the base:
  its default is no enforced deadline, never an invented provider default.
  Such hosted options publish with the shared default-buyer refusal diagnostic;
  Alkahest has no lifecycle and makes no delivery promise. Changing a supplied
  effective deadline changes future hosted option IDs, not capacity identity.
- Diagnostics reach the cycle report and system-status derivation, including
  where other options survive. Task 4.1 must reuse default_buyer_refusals
  for buyer acceptance rather than implementing a divergent policy.
- Bare-metal pool clauses resolve override > pricing.bare_metal.settlements
  pool hint > configured clauses, whole-list, including explicit empty lists.
  Malformed hint structure holds the pool. Reserved-only pools preserve the
  positive relative maximum rule; recurring pools reach per-option derivation.
  An absolute bound alone can therefore admit recurring options without
  admitting reserved capacity options.
- A fractional absolute end that cannot yield an unchanged whole-second
  recurring Agreement duration is refused, not rounded. Publication checks a
  whole-second reference start only; task 3.2 still owes actual acceptance-time
  start, horizon and approval-expiry validation.

Permanent destinations remain D3/D5's settlement/publication specifications and
architecture companions after code review. No promotion or archive is claimed.

## Owned first-use setup

Target: an invocation-owned in-process storefront app and real temporary SQLite
database in the caller's checkout. Persona: the existing harness's signed
administrator with deterministic public development identities. State: one
backed pool and one capacity/shape listing; real settlement registrations and
publication composition; injected proposed helper, effective deadline reader,
site/chain/registry boundary doubles. Token metadata is seeded under the
invocation's temporary cache. No secrets or external target selectors are used.

The probe first opens the typed system-status surface, then steps projections
and publication and reads the resulting listing through the typed client.
Readiness observed is this app's authenticated HTTP surface, not a deployment,
hosted payments service or site deadline authority. Every app/lifespan,
temporary directory and any fixture loopback server closes on exit.

From repository root:

    make dist-ci
    make -C domains/vms/storefront reinit
    make -C domains/bare_metal/storefront reinit

Then run either directly loadable invocation below:

    (cd domains/vms/storefront && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync python ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/recurring_publication_probe.py vm)
    (cd domains/bare_metal/storefront && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync python ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/recurring_publication_probe.py bare)

Both entry points were personally opened and run. Each confirms:

1. One listing with Alkahest reserved, hosted once, on-demand and spot candidates,
   separately priced; hosted lifecycle deadlines equal the effective port, not
   the deliberately different raw clause value.
2. The 24-period default penalty, an explicit zero seller override and its
   truthful default-buyer diagnostic.
3. Missing encoder omission while reserved peers and capacity identity remain.
4. A default horizon of 1500 seconds refused with the minimum 2400 seconds
   (300 approval + 1200 delivery + 900 period), while reserved peers survive.
5. Unsupported returned treatment and setup gating, without silent downgrade.
6. No deadline promise when the effective port resolves none; diagnostics
   remain visible and a later effective deadline changes hosted identities.
7. Unbounded recurrence omitted; absolute-only recurrence admitted under the
   same identity; bare-metal reserved admission remains stricter.

These are proposed injected-encoder observations, not live hosted rate,
approval, billing-stop, provisioned lease or acceptance-time guarantees.

## Existing regressions and checks

All package commands use uv run --frozen --no-sync pytest TARGETS -q after
the declared wheel build and per-package make reinit; storefront commands
clear proxies as above.

| Package | Targets | Result |
| --- | --- | --- |
| VM domain | tests | 60 passed |
| Bare-metal domain | tests | 224 passed |
| Settlement runtime | tests | 175 passed |
| Payments kit | tests/test_settlement_config.py | 24 passed |
| VM storefront | tests/unit tests/integration/test_publication_loop.py tests/integration/test_pool_overrides_api.py tests/integration/test_listing_identity_carryover.py | 1340 passed, 1 skipped |
| Bare-metal storefront | tests | 589 passed |
| VM storefront final reconciliation/import-placement follow-up | tests/unit/test_settlement_reconciliation.py tests/unit/test_listing_settlement_config.py tests/integration/test_publication_loop.py | 77 passed |

Targeted mypy:

    cd kit/settlement-runtime && uv run --frozen --no-sync --with mypy mypy --follow-imports=silent --ignore-missing-imports src/market_settlement_runtime/rate_publication.py

Passes for one source file, not whole-repository typing.

make check-packaging passes with fresh wheels, matching locks, architectural
rules and the fail-closed amount inventory. The one new amount read is explicitly
classified as a helper-supplied unit-bearing reference quote used for the penalty,
not an Agreement or multiplier read. make check-change CHANGE=negotiate-open-ended-compute-terms and the pinned
bunx @fission-ai/openspec@1.14.0 validate negotiate-open-ended-compute-terms --strict
pass, including comment hygiene, citations and the amount-read inventory.

No permanent tests were added. Existing kept fixtures follow the new composition
resource seam. The VM app harness now accepts an explicit configuration and
composition factory so first use reaches the real composition rather than its
old option-building double.

## Resolved attempts

- A guessed payments tests/unit target did not exist; the package's kept
  target is tests/test_settlement_config.py.
- The first probe used an example dispute interface where the composition
  installs mediation; the committed probe supplies that installed interface.
- First use found that the bound carrier is canonical UTC text, not a datetime;
  derivation now accepts that text, validates UTC and uses exact timedelta
  arithmetic. Both probes were re-driven.
- A direct cycle fixture did not supply configured clauses; an empty default
  accidentally shadowed its payload builder's own configured list. Omitted
  cycle defaults now defer; the production composition supplies its real list.
- The amount-read check refused the new reference read until its exact purpose
  was added to the inventory. Initial typing found entitlement-key/expanded
  model typing mismatches; explicit literal typing and model validation resolved
  them, then the diagnostic was re-driven.
- The VM unit suite exposed a stale blanket ban on core-carrier imports in
  specialization modules. The repository architecture permits that dependency;
  the kept test now permits market_core but still forbids role/composition
  packages. This deliberately narrows that assertion to the current written
  architecture; it is not an exception for the new code.
- The full bare-metal suite exposed an old manually seeded contact option
  carrying a monetary price. Its billing projection correctly refuses that
  shape. The fixture now uses the current rateless option identity, preserving
  the existing settle/fulfillment assertions rather than widening production
  acceptance.

Existing agent-id and websocket deprecation warnings remain. No actual E2E lane
was started; deployment readiness, real provisioning, rate service execution,
servicing declaration gates, horizon acceptance, complete CLI disclosure,
independent review, final rebase, promotion and archival remain unclaimed.
No external resources or resident servers are retained.
