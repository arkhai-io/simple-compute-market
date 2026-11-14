# Horizon acceptance checkpoint

Base: d8300a817, draft PR #351. This slice completes terms tasks 3.2–3.3.
Resume at 4.1. The original stacking on PRs #349/#350 is unchanged.

Two behaviours this records were replaced before the change landed: an omitted
horizon whose limiting bound is fractional is floored to whole seconds rather than
refused, and acceptance also refuses a horizon leaving no runway; see
`openspec/specs/negotiation-protocol/spec.md`, "Compute horizons bind both seller
bounds". The sections below describe the evidence as observed.

## Behavior

The shared negotiation runtime fixes one acceptance clock and then calls an
optional, schema-opaque domain hook before building artifacts or writing any
acceptance. Openings, counters, buyer acceptance and administrative acceptance
use the same hook. It does not duplicate provisioning/resume window logic.

Both compute domains resolve relative and absolute listing bounds at that start.
Recurring omission selects the lesser finite bound; an explicit shorter horizon
is unchanged, including 2,401 seconds rather than a rounded period count. An
explicit recurring start must be whole seconds. Unnamed recurring `now` resolves
to the authority's whole-second precision before signing. Once-only `now` retains
its fractional precision. Expired/excessive/sub-period horizons and missing
reserved duration fail closed. A fractional limiting absolute bound requires an
explicit shorter integer horizon, never silent rounding; a non-limiting fractional
bound does not disturb an integer relative maximum.

The runway uses exactly `floor(accepted_at) + approval_window`, not the listing's
publication clock. With the fixture's 300-second approval window, 1,200-second
delivery deadline and 900-second period, 2,399 seconds refuses with
`The horizon leaves no runway: minimum duration_seconds is 2400`. A future start
uses the later of that start and approval expiry. The selected option is unchanged;
resolved duration/start belong to the Agreement. VM's round-zero/default duration
and its rate-pin fallback no longer invent a reserved term. Delivery/recovery
fallbacks are not changed.

`RateTermTiming` and `rate_term_projections` are injected mechanism-owned parsing
and capability ports. They supply positive whole-second period/approval timing
and foundation `TermContext`, never a storefront parser for payment fields.
Missing projections refuse recurring acceptance. The foundation validates the
selected lifecycle, including term-end `settles_through` and installed partial-period
support. Its existing payments derivation maps `last_boundary` to
`end.partialPeriod: returned`; no second mapping or charged substitution was added.
Deployed compositions supply neither a rate timing projection nor rate servicing.

Bare-metal exact-selection pricing previews a horizon for admission/building;
final artifacts and persisted physical terms are rebuilt against the runtime's
fixed acceptance instant. The rebuilt obligation must keep the exact negotiated
money. Recurring Agreement-only pricing uses one period, not the horizon.
Both domains' wire codecs permit omitted recurring horizons; the buyer CLI work
that exposes/discloses that choice is still 4.1.

## Reproducible first-use setup

Target: invocation-owned in-process VM or bare-metal storefront, real temporary
SQLite, controlled external site/registry/chain boundaries. Persona: signed
administrator and signed buyer with deterministic public development signers;
never use these identities on a public network. Seed: one backed capacity listing
with reserved, hosted once, on-demand and spot candidates, both capacity bounds,
an injected effective deadline, proposed encoder/timing projections and an exact
`terms-probe` lane declaration. No credentials, ignored state, remote deployment
selector, browser or external server is required. All resources close on exit.

From repository root:

```sh
make dist-ci
make -C kit/settlement-runtime reinit
make -C kit/negotiation-runtime reinit
make -C domains/vms/domain reinit
make -C domains/bare_metal reinit
make -C domains/vms/storefront reinit
make -C domains/bare_metal/storefront reinit
```

Then run either personally exercised entry point:

```sh
(cd domains/vms/storefront && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync python ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/recurring_publication_probe.py vm --acceptance)
(cd domains/bare_metal/storefront && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy uv run --frozen --no-sync python ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/recurring_publication_probe.py bare --acceptance)
```

Readiness is the typed authenticated system-status response before publication.
This is app readiness, not a payments service or deployed site readiness check.
The adjacent `horizon_probe.py` adds pure boundary examples and signed buyer
refusals. No permanent acceptance tests were added.

Observed in both domains:

- Signed refusal for sub-period, insufficient runway, excessive horizon, fractional
  recurring start and missing reserved duration; every refusal leaves all real
  SQLite negotiation-thread rows unchanged.
- Default 7,200 and explicit 2,401-second horizon artifacts retain the exact option
  and original requested wire (including omission). Whole-second rate starts and
  resolved physical-term durations agree.
- Pure diagnostics cover equality with the maximum, absolute-only limiting bounds,
  expired/unbounded defaults, fractional limiting/non-limiting bounds, future start,
  once-only fractional precision and missing timing projection.
- Published/proposed/absent/wrong-revision/wrong-lane declarations replay both
  terms-owned doors. Publication omits rate peers and keeps reserved peers under
  the same listing identity. Cached selection refuses with signed 409/refetch
  before negotiation writes. Exact proposed-lane opt-in and published declarations
  admit publication. Spot owns materialization and convergence owns continuation;
  their execution is not claimed or required for terms task 3.3.

**Evidence boundary:** VM's fixture reaches a committed, signed acceptance with
an explicitly injected accepted-data placeholder, not a mandate. Bare metal's
valid paths use the negotiation runtime's no-write opening plan, checking its
Agreement and physical-term artifacts. A deliberately attempted full bare-metal
commit reached its separate payments-capture consumer and refused
`payment settlement data is malformed`: an empty fixture is not a rate mandate.
That attempt was in disposable SQLite and was discarded. It is not counted as
successful commitment. Spot owns the real rate mandate/capture handoff; no
materialization, approval, billing stop or provisioned lease is claimed here.

## Focused regression validation

Run from each named package with `uv run --frozen --no-sync pytest`:

| Package | Targets | Result |
| --- | --- | --- |
| Negotiation runtime | `tests -q` | 62 passed |
| Settlement runtime | `tests -q` | 175 passed |
| VM domain | `tests -q` | 60 passed |
| Bare-metal domain | `tests -q` | 224 passed |
| VM storefront | `tests/integration/test_buyer_selection_negotiation.py tests/unit/test_vm_negotiation_strategy.py tests/unit/test_server_app_composition.py tests/unit/test_sync_negotiation_seller_round_hook.py tests/unit/test_sync_negotiation_escrow_normalization.py tests/unit/test_sync_negotiation_hold_cap.py -q` | 70 passed |
| Bare-metal storefront | `tests/test_http_negotiation.py tests/test_app_composition.py -q` | 106 passed |

Storefront commands clear the six proxy variables as the probes do. Domain
negotiation policies are covered by the VM storefront targets: the standalone VM
negotiation package has no tests or Makefile, so an initial guessed `reinit`
command there was corrected to the existing consumer targets.

Targeted mypy from `kit/settlement-runtime`:

```sh
uv run --frozen --no-sync --with mypy mypy --follow-imports=silent --ignore-missing-imports src/market_settlement_runtime/horizon.py
```

One source file passes; this is not whole-repository typing. First attempts found
missing optional-type narrowing and the final mechanism-obligation amount-read
classification; both were corrected without weakening the fail-closed guard.
The existing VM composition fake follows the new injected port; assertions are
unchanged. Agent-id/deprecation warnings and a deliberately raised websocket
exception in the kept composition test remain non-failing diagnostics.

`make check-packaging`, `make check-change CHANGE=negotiate-open-ended-compute-terms`
and pinned strict OpenSpec validation pass. The change check initially found one
unnecessary local diagnostic import; it is now module-level, and both probes were
rerun successfully after the fix. No E2E lane was started in this slice. Section 4 buyer display/first use/validation,
final rebase/review and post-review documentation promotion/archive remain pending.
No resident server, browser page, tunnel or external resource remains.
