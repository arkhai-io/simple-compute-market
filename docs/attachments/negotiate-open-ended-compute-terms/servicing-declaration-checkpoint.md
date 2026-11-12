# Servicing-declaration checkpoint

Base: e33521d02, draft PR #351. This slice completes task 3.1. Resume at
3.2; the committed fixture also supplies the declaration qualification inputs
for 3.3, which remains unchecked until the intervening task is complete.

The declaration this records — a contract revision per mechanism with
`published`/`proposed` status and a lane identity — was replaced before the change
landed by per-mechanism qualified treatments and `setup`; see
`openspec/specs/settlement-configuration/spec.md`, "Rate servicing is a composition
capability". The sections below describe the evidence as observed.

## Changed behavior

One composition-owned `RateServicing` object selects the adapter-required contract
revision against current declarations. A declaration identifies the mechanism,
revision and published/proposed status. A proposed declaration also identifies a
stable test lane and is admitted only with that exact composition-owned opt-in.
Missing, different-revision or different-mechanism declarations fail closed.
Neither a listing nor a buyer can assert this capability. Deployed compositions
have no declaration and still offer no recurring servicing.

Both storefront compositions pass this same object to publication and negotiation.
The recurring encoder receives the selected declaration on `RatePresetRequest`.
Publication gates both structured recurring clauses and final option envelopes;
a builder cannot bypass the gate by returning rates for an ordinary clause.
Either period/reserve marker requires servicing, including a malformed pair;
mechanisms still own parsing, billing projection and supported-wire validation.

Cached recurring selections refuse with signed HTTP 409 and
`settlement_option_withdrawn_refetch` after declaration withdrawal, revision
mismatch or lane mismatch. The listing remains available when its valid reserved
peers survive. Negotiation checks before policy/pricing and again before final
acceptance artifacts are persisted. Existing accepted-deal servicing is not
conditioned on new-offer eligibility.

Spot owns the third-door materialization consumer; convergence owns startup and
accepted-deal continuation. This change supplies their selector contract, not
those implementations or evidence. No rate service, approval, stop, recurring
mandate or provisioned lease is claimed.

Permanent destinations after review: D6 in settlement configuration's specification
and storefront publication's architecture. No permanent promotion is made here.

## Committed first-use setup

Target: invocation-owned in-process VM or bare-metal storefront app with real
SQLite in the caller's checkout. Persona: signed administrator and signed buyer
using deterministic public development signers; never use these identities on a
public network. Seed: one backed pool and one capacity/shape listing with reserved,
hosted once and separately priced on-demand/spot candidates, both listing bounds,
an injected effective pool deadline and a proposed fixture encoder.

The fake revision `fixture-rate-v1` is not a published payments contract. Proposed
selection explicitly opts into lane `terms-probe`. Site, chain and registry
boundaries are controlled doubles; no deployment selector, credential, external
service or ignored setup file is required. All app lifespans, temporary databases
and fixture resources close on exit.

From repository root:

```sh
make dist-ci
make -C kit/settlement-runtime reinit
make -C domains/vms/storefront reinit
make -C domains/bare_metal/storefront reinit
```

Then open either runnable surface:

```sh
(cd domains/vms/storefront && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync python ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/recurring_publication_probe.py vm)
(cd domains/bare_metal/storefront && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync python ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/recurring_publication_probe.py bare)
```

Both commands were personally run. Readiness is the authenticated typed system
status response at the beginning of each diagnostic, not deployed payments/site
readiness. They then poll projections, run one publication cycle and read its
listing through the administrator's typed client. The signed buyer selects the
previously read recurring option while the declaration is absent, has a different
revision, or has a different lane. For every refusal, all real SQLite
`negotiation_threads` rows are byte-for-value unchanged. The subsequent publication
cycle omits both recurring peers and preserves two reserved peers on the same
listing identity. Restoring the matching declaration restores four options.
A matching published declaration independently permits publication.

The pure selector diagnostic also exercises published, proposed without opt-in,
wrong lane, exact lane, wrong mechanism, wrong revision and absent declarations.
The existing publication observations (penalty/default override, missing encoder,
runway, unsupported setup/treatment, missing effective deadline, unbounded and
absolute-only horizons) continue to pass. These are proposed-fixture observations,
not live rate execution or acceptance-time horizon guarantees.

## Existing regression validation

After fresh wheel installation, run each command from the named package:

| Package | `uv run --frozen --no-sync pytest` targets | Result |
| --- | --- | --- |
| Settlement runtime | `tests -q` | 175 passed |
| VM storefront | `tests/unit/test_server_app_composition.py tests/unit/test_listing_settlement_config.py tests/unit/test_settlement_reconciliation.py tests/integration/test_buyer_selection_negotiation.py tests/integration/test_publication_loop.py tests/integration/test_payment_settlement.py -q` | 108 passed |
| Bare-metal storefront | `tests/test_http_negotiation.py tests/test_app_composition.py tests/integration/test_payment_settlement_client.py tests/test_http_system.py tests/test_http_publication_rates.py -q` | 158 passed |

Storefront commands clear the six proxy variables exactly as the probe commands
do. Existing payment/settlement regressions exercise accepted once-deal continuity,
including offers being disabled. They do not prove rate continuation.

Targeted typing from `kit/settlement-runtime`:

```sh
uv run --frozen --no-sync --with mypy mypy --follow-imports=silent --ignore-missing-imports src/market_settlement_runtime/rate_servicing.py src/market_settlement_runtime/rate_publication.py
```

Two source files pass; this is not whole-repository typing.
`make check-packaging`, `make check-change CHANGE=negotiate-open-ended-compute-terms`
and pinned strict OpenSpec validation pass. The change check includes comment
hygiene and documentation citations. No permanent tests were added; kept app
composition fixtures follow the new injected resource.

## Resolved attempts and limits

- The first VM diagnostic used `vm.v1` instead of the domain's `compute.v1`
  envelope and received the expected 400 before the gate. Correcting the diagnostic
  reached signed 409/refetch with unchanged negotiation rows, and both final
  diagnostics passed.
- The existing shape-priced buyer integration scenario initially failed because
  its local storefront row had no retained seller publication proof/trust. Its
  fixture now supplies the actual captured publication body with a real seller
  signature and trust. That as-published resource, rather than the storefront's
  local row, is the buyer input. Verification assertions are unchanged. The focused
  scenario and both-domain target sets pass after this repair.
- Agent-id and websocket deprecation warnings remain. No E2E deployment or pipeline
  was started for this slice; that qualification remains in 4.3/5.8. No browser
  surface changed; evidence is execution, not visual.
- Acceptance-time horizon/start/runway enforcement (3.2), final 3.3 recording,
  buyer disclosure/first-use (section 4), final rebase/review and post-review
  closeout/promotion/archive remain pending. No external resources or resident
  servers remain.
