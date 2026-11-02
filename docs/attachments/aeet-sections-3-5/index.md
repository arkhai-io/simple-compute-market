# Authority preferences and role integration — implementation evidence

This packet is an implementer self-check, not independent acceptance. Section 3
(configuration and registry recommendations) and task 5.1 (query projection) are
implemented. Hosted option construction and exact authority admission belong to
section 8; no deployed hosted lifecycle is claimed by this packet.

## Revision and owned target

- Tested runtime revision: `61b39625f`, including role composition `f9c2b3039`,
  TOML unbounded-hold support `78659d4e4`, and startup fixture completion
  `56de14400`. Documentation follows in the same branch's next commit.
- Target: checkout-owned Python 3.13 environments populated from `.dist` wheels;
  real registry application integration against fixture-owned SQLite databases.
  No shared deployment, inherited selector or external seed is used.
- Persona/authentication: a configuration author, plus fixture buyer/seller
  identities through the signed, authority-pinned typed clients. The payment
  smoke uses deterministic development signers and the kit's fake payments
  client; none is for use on a public network. No external account, service
  credential or secret is needed.
- State: temporary databases created by the existing suites and smoke example.
  Every run owns its state; the smoke deletes its temporary directory on exit.
- Readiness: rebuilt wheels, role reinitialization, configuration example,
  signed registry application integration and the payment smoke all completed.

## Reproduce first use

Run from the checkout root. These entry points were personally run; they use
committed files rather than copied ignored state:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C kit/deal-lifecycle reinit
(cd kit/deal-lifecycle && uv run --find-links ../../.dist python examples/dispute_configuration.py)
make -C core/registry reinit
(cd core/registry && uv run --find-links ../../.dist pytest tests/integration/test_registry_descriptor.py -q)
make -C domains/vms/storefront reinit
(cd domains/vms/storefront && uv run --find-links ../../../.dist python examples/payment_smoke.py)
```

The [configuration example](../../../kit/deal-lifecycle/examples/dispute_configuration.py)
prints successful per-registry resolution and empty-list diagnostics, buyer
opt-in, seller defaults, local vetoes, exact credential identity and secret
isolation. Its resolver injects an obviously public example secret; it does not
read a real environment credential. Omitting the advertisement's minimum case
hold expresses an unbounded minimum in TOML, which has no null literal.

The [payment smoke](../../../domains/vms/storefront/examples/payment_smoke.py)
uses a selected lifecycle-bearing fixture option with no retired config key.
Observed output: before approval, pending with zero deliveries; after approval,
provisioning; retry, ready with one delivery; zero payment escrow rows. Payment
HTTP and VM delivery are controlled at their existing seams, not live services.

## Claims and observations

| Claim | Observed evidence | Limit |
|---|---|---|
| Roles obtain registry-specific recommendations without sharing trust or defaults | Buyer bootstrap and all three storefront startups use signed, URL-pinned descriptor clients; the existing registry application test resolves a returned recommendation with buyer opt-in and refuses it under the buyer default. The example keeps two registries independent. | No live registry or dispute authority was contacted. |
| Local policy wins by full identity | Configuration example resolves local entries before registry copies and preserves local vetoes and parameters. | Interface-owned acceptance and hosted option ordering remain section 8. |
| Empty policy is visible | Registry application integration and the example observe the diagnostic naming both root `[[Dispute]]` and `use_registry_dispute_authorities`. Role composition logs it for an empty resolved list. | An empty-list message is not end-to-end hosted admission evidence. |
| Credentials stay out of public projections | The example checks full-identity lookup, a changed key mismatch and secret wrappers. Buyer public context contains resolved authority entries only. | Credential-consuming lifecycle adapters are outside this assignment. |
| The payments config key is retired | Existing payments configuration assertions reject a set value and explicit null with a `[[Dispute]]` diagnostic. Mandate derivation reads the selected lifecycle authority; stored mandates remain bound to that authority and acceptance-time fees. | Missing lifecycle terms fail closed; no legacy accepted-work fallback is supplied. |
| Templates ship no authority | Existing VM template assertions check explicit recommendation consent, no `[[Dispute]]`, no retired key and no record key. Role settings and Helm fixture carry no authority. | No new template writer or permanent test function was added. |
| Configuration is usable from documentation | The three TOML snippets under the deployment guide's dispute-preference heading parse and compose a preference plus its exact credential binding. | Example identities and origins are reserved demonstration values. |

The registry's optional public descriptor key remains
`recommendedDisputeAuthorities`; absent/empty configuration omits it. The option
envelope and option-ID algorithm are unchanged by this section. Fixture options
now carry their authority in the designed lifecycle slot. Query projections
remain codec-owned and asset-correlated; the generic core query parser is
unchanged.

## Validation

Focused existing suites pass: lifecycle (62), storefront kit (131), core buyer
(159), core storefront (225), registry unit/integration (129 + 128), payments
(92, including typing and generated-contract checks), VM/API-credit/bare-metal
buyers (213 + 35 + 16), VM storefront unit/integration (1,189 + 501, one unit
skip), bare-metal storefront (522), API-credit storefront (248), and e2e unit
(315). Both storefront schema suites pass (33 + 11), and the full Helm rendering
and structural identity assertions pass. Existing fixtures/assertions were
adapted without weakening assertions or adding test functions.

`make lock` regenerated the affected dependency records. `make check-locks`,
`make check-packaging`, `make check-architecture`, `make check-comment-hygiene`
and pinned strict OpenSpec validation pass. The payments fixture uses neutral
example dispute vocabulary so the mechanism kit does not depend on a particular
dispute interface.

The final full `make test` invocation passed on 2026-11-02 in 7m 2s, including
all unit/application-integration suites, 1,843 release-tooling tests, and Helm
rendering/structural assertions. The shell unset both proxy variables, set both
no-proxy variables to loopback, and opted into a local Docker-compatible Podman
shim for the deployment-packaging tools. A normal reproduction needs the Docker
CLI and Compose prerequisites documented by the repository.

Earlier attempts identified stale generated payment configuration schemas, a
startup fixture missing the registry auth default, and five release-guide cells
missing the new direct lifecycle dependency. All were repaired, their focused
suites rerun, and the complete aggregate then passed in one invocation. The
publication manifest and workflow were not duplicated or changed.

`make check-doc-citations CHANGE=agreed-evidence-and-early-termination` reports
only the three already-tracked future lifecycle spec/architecture destinations
in [#325](https://github.com/arkhai-io/simple-compute-market/issues/325).
No placeholder permanent spec or weakened checker was introduced. The new role
configuration documentation adds no unresolved citation. Normative spec and
architecture promotion remain reviewed closeout work.

## Limits and cleanup

- Independent fresh-user acceptance and the deployed `e2e_deal`,
  `e2e_bare_metal_mock_deal` and `e2e_credits_payment_deal` scenarios are unrun by
  this worker. The aggregate is unit/application integration, not those lanes.
- Hosted lifecycle-bearing publication, buyer exact-interface admission and
  preference ordering remain section 8, which consumes the resolved role lists.
- Only Python 3.13 was exercised; this run establishes no 3.10–3.12 result.
- No resident servers, tunnels, containers, browser pages or remote resources
  were created or left running. No canonical checkout or shared state was changed.
