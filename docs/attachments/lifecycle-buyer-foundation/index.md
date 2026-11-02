# Lifecycle client, buyer half and authority selection

This is implementer self-check evidence for tasks 7.1–7.3, not independent
acceptance. It is a nonvisual library/CLI journey; no screenshots apply.

## Setup and first use

The required target is the injected foundation and fresh buyer-selection paths,
not a hosted deployment. The prepared target is this branch's checkout-owned
Python 3.13 environments with their own package installed editable and internal
dependencies installed from freshly built `.dist` wheels. No inherited deployment
selector, shared database or external account is used. The signed
client example uses deterministic public development Ed25519 buyer/seller
personas, never public-network credentials. The buyer-half example creates and
removes its own temporary SQLite evidence/operation store. Selection uses only
public example configuration. No secret environment variables are required.

From a clean checkout, these commands land directly on the exercised surfaces:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C kit/deal-lifecycle-client reinit
(cd kit/deal-lifecycle-client && uv run --find-links ../../.dist python examples/first_use.py)
make -C kit/deal-lifecycle-buyer reinit
(cd kit/deal-lifecycle-buyer && uv run --find-links ../../.dist python examples/first_use.py)
make -C domains/vms/buyer reinit
(cd domains/vms/buyer && uv run --find-links ../../../.dist python examples/authority_selection.py)
```

All three entry points were opened and completed successfully. Readiness was
observed through wheel/environment preparation and completed first-use output;
no resident HTTP server is needed. The transport example uses an in-process
signed HTTP seam, not a deployed storefront or authority.

## Required claims and observations

| Claim | Action and observed result | Boundary |
|---|---|---|
| Signed lifecycle peer transport | The [client example](../../../kit/deal-lifecycle-client/examples/first_use.py) sends commit/hint and reads delivery through the installed client. It observes accepted outcomes and six captured request/response envelopes, refuses tampered and unsigned responses without capture, and refuses a changed same-request-ID retry before I/O. | Uses recorded-shape responses signed by a controlled seller, not section 13 routes. |
| One counterpart decides a command | The [buyer-half example](../../../kit/deal-lifecycle-buyer/examples/first_use.py) files through a fake dispute adapter and observes zero payment calls; an accepted result with mixed held/paid-out parts is returned unchanged. A payment command independently reaches only its payment adapter. | Actual payment and dispute transport composition belongs to 7.4. |
| Errors, late filing and replay are authority-owned | The example preserves pending extension and unknown lost-response answers, reads the recorded case after the lost answer, sends a late filing rather than locally closing its window, and observes the same derived key after reopening the durable store. Changed retry content reaches no adapter. | The fake adapter does not establish live service behavior. |
| Append packaging and hints stay separate | Append delegates evidence packaging to the dispute adapter. Filing sends stable-key hints. A failed hint is separately observed as unknown while the authority's accepted filing remains accepted. | Canonical surrender/outage journaling is deferred to 7.5. |
| Direct reads merge independent records | The half combines payment open extensions and lifecycle state with the dispute authority's cases and storefront delivery. With no payment adapter it returns a named rejection and the unchanged delivery view. | A filing's held answer is not substituted for a payment extension record. |
| Fresh selection enforces accepted authority | The [production VM example](../../../domains/vms/buyer/examples/authority_selection.py) runs the real composed policy with two offered authorities. Reversing local authority order reverses the selected option without editing either. Unknown authority, changed origin/key/params, unsupported interface, incompatible advertisement, empty policy and absent compute deadline all refuse selection. | VM and API-credit compose the same neutral helper. Bare metal checks its explicit option ID through it. |
| Core remains neutral | The existing core buyer suite passes with an injected option-preference seam; it imports no lifecycle implementation. Clause/mechanism priority and ordinary option-ID tie-break behavior remain intact. | Buyer lifecycle stage wiring is not enabled by this task. |

## Validation

The client commit is `834b38979`; buyer-half dispatch is `c7b8dcc7a`.
Authority selection is `60c9a57b6`. Existing suites pass:
lifecycle 62, buyer evidence 18, core buyer 159, storefront client 68, VM buyer
213, bare-metal buyer 16 and API-credit buyer 35. Existing fixture setup was
updated to state accepted lifecycle authorities; no test function was added and
no kept behavior assertion was weakened.

`make check-architecture`, `make check-packaging`, `make check-locks`,
`make check-comment-hygiene` and pinned strict OpenSpec validation pass. New
client publication metadata and the mediation dependency are declared once in
the manifest/workflow; affected buyer and dependent storefront/e2e locks were
regenerated through `make lock`, not hand edited. Configuration models are
unchanged, so no Helm schema regeneration is needed.

The complete `make test` aggregate passes in 7m20s with the prescribed environment
and a Docker-compatible runtime; this run opted into the local Podman shim:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make test
```

The initial aggregate found a bare-metal buyer integration fixture without an
accepted dispute authority. The same setup omission was reproduced in the two
API-credit CLI integration files. Commit `2db61c3e5` supplies compatible public
fixture terms and accepted authority configuration without changing assertions.
The bare-metal payment integration file now passes all 16 cases; API-credit
buy/negotiation integration passes all 3 cases. The subsequent complete aggregate
includes those suites, release tooling and Helm structural/render checks.

Commit `7434287e8` retains signed lifecycle acknowledgements by their signed route
resource even when the payload omits `negotiation_id`. A temporary diagnostic
captured such a response before its request and observed the evidence after
reopening the SQLite store; all 18 existing buyer evidence tests pass.
`make -C core typecheck` passes both configured typing targets. The three committed
first-use entry points were rerun successfully after these repairs.

The documentation citation check reports exactly the three known future
lifecycle-specification citations tracked by #325, explicitly waived for this
assignment. No additional unresolved citation was found. Commit `8f0200189`
removes the two inherited duplicate lifecycle rows in the release guide.

## Limits and cleanup

- 7.4–7.5 are intentionally not implemented: section 13 routes, domain lifecycle
  stage wiring, canonical end-delivery, stop outage/retry journal and concrete
  buyer concurrence capture remain their tasks.
- No live hosted authority, browser journey or deployed end-to-end lane is
  claimed. Existing named end-to-end scenarios are not newly qualified here.
- No servers, tunnels, containers, remote deployments or browser pages were
  started by these first-use checks; none is left running.
- Permanent subsystem specification/architecture promotion remains the reviewed
  closeout task, not a second handwritten copy of the change deltas.
