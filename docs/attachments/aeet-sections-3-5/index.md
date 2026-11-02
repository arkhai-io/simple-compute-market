# Authority preferences and lifecycle-query implementation checkpoint

This packet records an implementer self-check, not independent acceptance.
Sections 3 and 5 of `agreed-evidence-and-early-termination` are **partially
implemented**: tasks 3.1, 3.3 and 5.1 are complete; 3.2, 3.4 and 3.5 remain open.
Section 4 is outside this assignment.

## Revision and target

- Tested code: `5c3f17b47` on branch `s3-5`, based on `ad4792f13`.
- Required environment: library and real-registry application integration for
  these tasks; the change also requires compute end-to-end coverage at closeout.
- Actually prepared target: checkout-owned Python environments populated from
  the repository's `.dist` wheelhouse, Python 3.13; no shared deployment.
- Persona/authentication: a configuration author using the library; registry
  integration uses deterministic fixture signers and the authority-pinned typed
  client against the in-process registry app. No external accounts or secrets.
- State: library example data and fixture-owned temporary SQLite databases.
  No inherited deployment selector, destructive shared seed, or resident server.
- Readiness observed: package reinitialization succeeded, the example completed,
  and 12 selected registry integration tests passed on 2026-11-02.

## First-use reproduction

Run from the checkout root. The build and reinitialization use the project's
existing tooling and do not depend on ignored state copied from this worktree.

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C kit/deal-lifecycle reinit
(cd kit/deal-lifecycle && uv run --find-links ../../.dist python examples/dispute_configuration.py)
make -C core/registry reinit
(cd core/registry && uv run pytest tests/integration/test_registry_descriptor.py tests/integration/test_asking_rate_filter.py -q)
```

No secret environment variable is needed for this example. It injects an
obviously public example value for `EXAMPLE_DISPUTE_API_KEY` into its credential
resolver. A real role would supply the identity-bound environment reference;
role integration is not yet implemented.

## Claims and observations

| Claim | Action and observation | Limit |
|---|---|---|
| A role can resolve ordered preferences and registry recommendations | The public [configuration example](../../../kit/deal-lifecycle/examples/dispute_configuration.py) reports the buyer's empty default, seller registry default, buyer opt-in and local veto. | Library surface only; running roles do not yet fetch or compose these lists. |
| Credentials bind to the full authority identity without disclosure | The example resolves the exact identity, refuses a different record key, and checks secret isolation from public serialization and printable wrappers. | No live dispute authority was contacted. |
| An operator's descriptor can recommend authorities | Existing descriptor unit/integration checks pass for omission and configured data through the signed typed client; Helm renders both configurations. | Recommendations are available but not consumed at role startup. |
| Queries project common lifecycle fields with option-correlated assets | Existing settlement clause and registry filter checks pass for requested rights, absent defaults, asset-required penalties and no cross-option currency match. | Positive lifecycle cases seed the query boundary directly. Public lifecycle-bearing option publication waits on 2.5b. |
| Shipped buyer configurations explicitly consent without shipping an authority | Existing VM template checks pass (2 tests); three committed development profiles parse with explicit opt-in and no `Dispute` entry. | Other role wiring remains task 3.4. |

No option wire bytes or option-ID inputs were changed. The generic core query
parser remains unchanged; the lifecycle codec owns the projection vocabulary.
The registry's optional descriptor field is `recommendedDisputeAuthorities` and
is omitted when unconfigured or empty.

## Validation

Focused existing suites passed: lifecycle-contracts (37), lifecycle (62),
settlement-runtime (175), core query DSL (24), registry unit (129), registry
integration (128), and payments (92, plus typing/generated-contract checks).
The first-use rerun above passed 12 selected registry integration tests. Core
typing, `make check-architecture`, `make check-packaging`,
`make check-comment-hygiene`, and pinned strict OpenSpec validation passed.
Existing test bodies and fixtures were updated; no permanent test functions were
added. Fresh verification still owns acceptance.

The full `make test` attempt was not one all-green run. Repairs and reruns:

1. The introduction profile's exact field-name assertion rejected the deliberately
   expanded common query vocabulary. Updating its expected set preserved the
   assertion; both complete registry suites then passed.
2. API-credit isolated installation failed because its temporary wheel set omitted
   the newly transitive lifecycle packages. Commit `f91f1166e` adds them; all
   three isolated distribution-install tests pass. The remaining API-credit and
   e2e-unit aggregate targets then passed before release tooling.
3. Release-tooling dependency checks rejected omitted lifecycle distributions in
   the publication manifest/workflow/guide. Commit `5c3f17b47` repairs these
   records; the focused publication suite passed 272 tests.
4. The host lacks Docker CLI, reproducing tracked
   [issue #324](https://github.com/arkhai-io/simple-compute-market/issues/324).
   A temporary Docker 28.3.3 / Compose 2.39.4 tool directory enabled daemon-free
   `make test-deployment-packaging`: 1,838 script tests and all Helm
   structural/render assertions passed. The directory was removed after use;
   no daemon or container was started. Without that prerequisite the same
   aggregate target will still fail on this host.

The lifecycle packages' declared Python range was aligned to their identity
provider and settlement-runtime consumer (3.10 through 3.13); otherwise uv could
not resolve the new dependency for settlement-runtime's supported range.
Regenerated downstream locks are necessary transitive dependency records.
Only Python 3.13 was exercised here; 3.10–3.12 behavior is not established by
this run.

## Remaining work

- **3.2:** reject the retired payments authority key and remove its template line.
  This depends on the option wire flip (2.5b): current mandate construction and
  `PaymentApproval` still require that authority input, while the pre-flip
  accessor exposes no lifecycle terms. Removing it now would break existing
  hosted commitments or invent a competing temporary wire format.
- **3.4:** add signed descriptor reads and per-registry recommendation lists to
  buyer/bootstrap and storefront/publication; compose role preferences and
  report when the resolved list is empty. These paths currently read filter
  specs or configured trust pins, not descriptors as the task assumed.
- **3.5:** document the role-integrated configuration once it works, including
  the retired key. Durable spec promotion remains the change's closeout work;
  destinations are recorded in its tasks/design.
- **Unobserved:** independent fresh-user acceptance, compute end-to-end
  scenarios, and hosted lifecycle-bearing option publication. No browser or
  container deployment was prepared for this library checkpoint.

No servers, tunnels, browser pages, containers or remote resources were left
running by this work.
