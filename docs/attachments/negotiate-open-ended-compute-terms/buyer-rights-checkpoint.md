# Buyer rights and lifecycle disclosure checkpoint

Base: fea9455da. Draft PR #351; stacking on #349/#350 is unchanged.
This slice completes 4.1a only. Restart at 4.1b; 4.1 remains unchecked.

The single run-scoped waiver this records was replaced before the change landed by
one waiver per refusal, with `--allow-unprotected-terms` as their shorthand; see
`openspec/specs/buyer-orchestration/spec.md`, "Each default refusal has its own
waiver". The sections below describe the evidence as observed.

## Behavior and boundary

Both buyer compositions apply the same default rights recommendations that
storefront publication diagnoses. They refuse on-demand without a positive
premature-stop penalty, adapter-backed compute without a delivery deadline,
and seller/term-end partial-period treatments other than returned.
The run-scoped `--allow-unprotected-terms` switch explicitly waives those
recommendations together, not unsupported capabilities, malformed codec values
or unaccepted dispute authorities. Fresh runs record the switch.

Fresh VM buy/negotiate and bare-metal buy disclose lifecycle terms before
negotiation and from the exact accepted option before approval. These rows are
visible without an interactive prompt and go to stderr; JSON stdout stays
machine-readable. A mechanism with no lifecycle adapter is shown as making no
lifecycle delivery promise, not rejected for having no deadline. Authority
identity/window/hold cap, per-stopper notice/treatment, term-end treatment,
penalty amount/asset/earned-held ceiling and worst case, activation/start,
stop-then-hint, pending stops, setup non-delivery semantics and evidence retention
come from the foundation codec/contract. No reserve-ahead loss cap is promised.

**Not complete:** class/price-unit/setup/reserve numerical presentation, optional
recurring horizons, bounds/effective-horizon presentation and accepted recovery's
pre-approval disclosure. No full recurring CLI buy, mandate or provisioned lease
is claimed. The installed payment billing projection remains once-only.

## Committed replay setup

Target: invocation-owned, process-local policy/disclosure diagnostic in this
checkout, not a Cloud deployment, HTTP service or running payment lane.
Persona/auth: public development authority and account fixtures only; no signing
credential or secret is required. State: freshly constructed hosted once,
on-demand, spot, missing-deadline/penalty, charged-treatment and no-adapter
candidates; no persistent state or destructive seeding.

The fixture uses the actual context factory from the chosen domain buyer and
explicitly replaces rate capabilities with **proposed injected data**. It does
not change either installed composition or claim its rate adapter can execute.
Readiness: imports and policy context construction pass before selection; no
deployed authority/site/HTTP readiness is implied. No inherited selector is used.

From repository root, prepare current wheels and locked environments:

```sh
make dist-ci
make -C kit/settlement-runtime reinit
make -C domains/vms/buyer reinit
make -C domains/bare_metal/buyer reinit
```

Personally exercised entry points, each landing directly on its diagnostic
selection/disclosure surface:

```sh
(cd domains/vms/buyer && uv run --frozen --no-sync python ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/buyer_terms_probe.py vm)
(cd domains/bare_metal/buyer && uv run --frozen --no-sync python ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/buyer_terms_probe.py bare)
```

Both replays select hosted once/on-demand/spot under the proposed context,
refuse each missing recommendation by the shared reason, permit an explicit
recommendation waiver, and still refuse unsupported returned treatment with
the waiver. The Alkahest no-adapter candidate selects in the **rights policy**
and prints no delivery promise. This is not Alkahest mechanism compatibility or
bare-metal purchase-stage support. Full mixed-listing buyer selection is 4.2.

Representative observed rows in both domains:

```text
Delivery deadline: Active within 1200 seconds after your approval (or the agreed start, if later), or the seller has not delivered.
Buyer stop: Entitled with 0 seconds' notice; settles_through=started_period (final partial period charged).
Seller stop: Entitled with 120 seconds' notice; settles_through=last_boundary (final partial period returned).
Term end: settles_through=last_boundary (final partial period returned).
Premature-stop penalty: Up to 15000000 minor units of USD/6
no penalty: refused: a default buyer refuses this option: on-demand has no positive premature-stop penalty
no deadline: refused: a default buyer refuses this option: no delivery deadline
waiver cannot bypass an unsupported returned treatment: PASS
PROPOSED RIGHTS/DISCLOSURE FIXTURE ONLY: no live rate, mandate, approval or lease
```

CLI help was also opened through `market buy --help` in the VM buyer environment
and `market bare-metal buy --help` in the bare-metal buyer environment. Both expose
the explicit waiver. Existing CLI regression tests exercise real Typer dispatch
with controlled command collaborators; the diagnostic above does not claim to
replace 4.2's full buyer first use.

## Focused validation

Existing tests run with `uv run --frozen --no-sync pytest` from each package,
clearing HTTP/HTTPS/ALL proxy variables for buyer tests:

| Package | Target | Result |
| --- | --- | --- |
| Settlement runtime | `tests -q` | 175 passed |
| VM buyer | `tests/test_buy_resume_cli.py tests/test_explain_cli.py tests/test_negotiate_stage_dispatch.py -q` | 18 passed |
| VM buyer | `tests -q` | 215 passed |
| Bare-metal buyer | `tests -q` | 32 passed |

No permanent tests were added or assertions weakened.

Targeted typing from settlement runtime:

```sh
uv run --frozen --no-sync --with mypy mypy --follow-imports=silent --ignore-missing-imports src/market_settlement_runtime/buyer_terms.py
```

One source file passes, not whole-repository typing. An initial literal-key
narrowing error and a diagnostic fixture using the wrong dispute interface were
fixed and replayed, without relaxing validation.

`make check-packaging`, `make check-change CHANGE=negotiate-open-ended-compute-terms`
and pinned strict OpenSpec validation pass. No E2E lane was started in this slice.
There is no deployed rate/mandate, approval, stop, authority, deadline enforcement
or provisioning evidence here. Section 4.3 still owes the existing reserved
compute/listing-shape E2E attempt with the specified Podman provider; final
rebase/review and post-review promotion/archive also remain pending.

No browser page, server, tunnel, container or external target was started or
left running.
