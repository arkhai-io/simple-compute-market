# VM lifecycle classification and fresh-stack qualification

Nonvisual implementer self-check, not independent acceptance. This packet records
the in-process classification/failure-release encounters and the deployed VM
end/report qualification. No screenshots apply.

## Prepared target and first use

The prepared target is this checkout's VM storefront over fresh internal wheels,
invocation-owned SQLite and signed in-process HTTP. Payment readiness comes from
the kit-owned vector-derived fixture. Buyer, seller and site are deterministic
public development identities, never public-network credentials. No inherited
deployment selector, external account, secret or resident service is required.

From repository root:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C domains/vms/storefront reinit
(cd domains/vms/storefront && PYTHONPATH=. uv run --locked \
  --find-links ../../../.dist python ../../../docs/attachments/vm-end-classification/first_use.py)
```

The command opens three invocation-local encounters:

- A verified report arrives before its controlling lawful evidence. The same
  source's pending slot resolves through the existing revisioned journal, with
  no seller-failure filing. Replaying its original signed report preserves the
  original request, bytes and initially absent controlling-source field.
- A verified site withdrawal has no entitled controlling command. Its final
  request and fixed-basis payee filing are journaled atomically.
- The failure policy's release action runs without a preceding site report.
  The committed deal receives a provisioning-failure source and filing in the
  same journal; physical work is driven by end service.

All three use the actual VM physical-end port with an injected site transport.
A delivered lease never invokes direct capacity release: it sends lease
termination with the journal's stable operation key, stays tearing down, and
reaches released only when the capacity-return callback's local effect runs.
This is not provider execution or callback HTTP evidence; the existing callback
application regressions and [site/buyer packet](../vm-site-report/index.md) cover
that HTTP binding.

## Implementation boundary

The domain interprets original verified site bytes, accepted term deadlines,
reservation deadline/availability facts and recorded physical commands. An
exact command-key/caller match or a matching requested lease deadline correlates
the report with its controlling request; a cause label alone cannot grant a
payment entitlement. Proven lawful correlation retains both evidence sources
without inventing a seller fault. Established earlier non-delivery stays
independently correctable.

The lifecycle cycle establishes a missed delivery deadline even when no further
fulfillment attempt occurs. After observing new authority evidence it revisits
pending site corrections through the same journal and fixed basis. Unknown
causes or deadlines without sufficient controlling evidence remain pending,
without blocking physical teardown. Renewal/funding-timer interpretation and
rate stop execution are not implemented here.

The failure policy releases an accepted committed deal through end service,
not directly through the capacity client. It keeps first failure attribution,
journals required correction, suppresses a new failure from an already-due
lawful refusal, and preserves retry keys. Holds outside committed delivery keep
their existing guarded capacity-release path. Undispatched release echoes its
journal key for site-report correlation. Delivered leases always use lease
lifecycle, never a direct release that could bypass callback-proven progress.

No shared kit, provisioning source or sibling-domain source is changed.
Dependencies and configuration models are unchanged: no lock refresh,
publication-row addition or Helm-schema regeneration is required.

## Validation and corrections

- Fresh wheels, architecture, packaging, lock currency, comment hygiene and
  pinned strict OpenSpec validation pass.
- VM storefront: 1,189 existing unit cases and 501 existing application
  integration cases pass; the existing optional Torch collection skip remains.
- Both this first-use command and the previous signed site/buyer first-use
  command pass.
- The initial VM aggregate found the kept undelivered-release assertion still
  expecting the former generic reason. It now checks the exact journal key
  carried for correlation; release and no-truncation assertions remain intact.
  No permanent test function was added or existing safety assertion weakened.
- The first actual-physical-port diagnostic reached listing validation: the
  reused payment harness intentionally omitted SLA/region. The committed example
  supplies those public fixture fields before opening that surface; no production
  validation was relaxed.
- Full **`make test` passes in 7m41s** on the final production source, with both
  all-proxy variables unset, loopback no-proxy exclusions and the shell-local
  Podman shim. Package, application, e2e-harness unit, release-tooling and Helm
  structural/render suites pass. An earlier aggregate was deliberately stopped
  before the final callback-only physical guard; it is not counted as passing.
- Scoped citation checking reports exactly the three known future lifecycle
  spec/architecture references tracked in
  [#325](https://github.com/arkhai-io/simple-compute-market/issues/325).
  Final comment hygiene and pinned strict validation pass after the packet and
  task checkpoint updates as well.

## Fresh-stack end/report qualification

Tested revision: **`5874088d1`**. The target was an invocation-owned disposable
clone of this branch: fresh rootless Podman VM-lane images, empty named volumes,
isolated networks and remapped loopback host ports. No inherited deployment was
selected or seeded. Provisioning used the committed mock profile, not real KVM;
the development chain was real local Anvil. Buyer, seller, administrator and
site used the lane's deterministic public development personas and signed
role-bound requests, never public-network credentials.

Real local payment and mediation HTTP authorities ran with Formance/Postgres,
funded disposable development accounts and exact pinned authority descriptions.
Namespace-local loopback forwarders preserved development-auth guards. Both
seller and buyer namespaces and the host reached payment health; mediation
health and its description passed too. The registry recommended that exact
mediation authority and the seller opted into its recommendations. Before
pytest, the committed [readiness gate](readiness.py) seeded its own public
fixture capacity and read an authenticated registry publication showing:

- `option["settlement"]["schema"] == "arkhai.payments.v1"`;
- the served mediation authority in accepted adjudication terms;
- a 300-second delivery deadline, 1,296,000-second dispute window and unbounded
  case hold, distinct from the payment `window=P7D`.

The explicit readiness listing is hosted-only. The two complete-deal journeys
retain their canonical Alkahest settlement, as the bare-metal mock deal does;
this packet does not claim VM hosted payment replay/refund, rate-stop or case
ruling qualification. The authority setup follows the
[local-authority recipe](../aeet-s8-integration/index.md#live-local-payment-replay-requirements)
and the envelope read follows [#327](https://github.com/arkhai-io/simple-compute-market/issues/327).

### Reproduction boundary

Use the shell-local Podman shim and the prescribed proxy exclusions, then build
this checkout's images with `make build-e2e-vm`. Render the committed VM Compose
lane into a new owned project with fresh volumes and unused loopback ports; do
not run a fleet-wide reset against another deployment. Configure actual local
payments and mediation, exact registry recommendations, seller recommendation
consent and the named `PAYMENTS` profile from
[the shared payment setup](../../../e2e-tests/README.md#shared-payment-scenario-configuration).
`PAYMENTS.MEDIATION_URL` names the role-local mediation origin. Both development
authorities must be healthy before the gate runs. Keep source checkouts supplying
those services read-only.

Mount `docs/attachments/vm-end-classification/readiness.py` at
`/runtime/readiness.py` in the branch-built buyer runner, with the lane settings
and `ACTIVE_PROFILES=docker,payments`, `CONFIG_DIRECTORY=/app/config` and
`PYTHONPATH=/app`. From its `/app` working directory, these exact commands were
personally run after Compose health succeeded:

```sh
.venv/bin/python /runtime/readiness.py
.venv/bin/pytest -p no:cacheprovider -q --tb=short \
  tests/e2e/roles/scenarios/vms/test_full_deal.py
.venv/bin/pytest -p no:cacheprovider -q --tb=short \
  tests/e2e/roles/scenarios/vms/test_full_deal_buyer_cli.py
```

The real installed buyer subprocesses use the hermetic profiled buyer fixture;
no injected run context or in-process CLI substitute is used. Required launch
environment for builds, regression and qualification:

```sh
eval "$(~/.local/share/simple-compute-market/podman-shim/setup)"
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
```

### Observed claims and counts

| Journey or claim | Observed result |
|---|---|
| `e2e_deal` | **38 passed in 17.18s**, zero skips |
| `e2e_deal_buyer_cli` | **30 passed in 26.07s**, zero skips |
| Existing canonical lifecycle | Negotiation, settlement, active delivery, controlled lease expiry, gated teardown, callback release and capacity reuse remain covered |
| Second deal | Freed capacity is republished and delivers another VM; the CLI negotiates and settles it through real subprocesses |
| Buyer end | Canonical `LifecycleClient.end_delivery` and real `market end --from` each retain the same operation key, receipt time and selected end across surrender retries |
| Signed site report | Exactly one immutable report verifies against the configured site and reservation, with termination cause and the seller as caller, while capacity is still releasing |
| Intended versus proven end | Delivery stays `tearing_down` before provider completion and even after `torn_down`, until the separate lease cycle delivers the capacity-return callback |
| Proven release | Exactly one reservation-scoped release event, one teardown handle and one site report; final delivery is `released` without replacing the original selected end or site bytes |

### Repairs and preparation corrections

Qualification found one production defect: with payments enabled, a listing
selecting only Alkahest reached the payment option builder without a payment
publication clause and failed validation. **`d2c71b365`** makes an absent clause
publish no payment option, matching explicit selection semantics. The existing
builder regression now checks that boundary; no existing assertion was removed
or weakened. Its **97 tests**, typing, vectors and generated-model checks pass,
and the fresh-stack re-drive above exercises the joined mechanisms.

Earlier attempts are not counted as passing. The first readiness gate wrongly
expected an Alkahest option alongside an explicitly hosted-only clause; that
expectation was corrected without relaxing hosted adjudication validation.
Scenario setup then needed the same explicit controls as its first deal:
advance republication, await the new negotiation's dispatch and use canonical
settlement wait. VM release events are reservation-scoped, not negotiation-
scoped. Finally, CLI observation uses a small positive `--wait-timeout` to read
current delivery: timeout exit 1 means accepted surrender but unproven release;
exit 0 means proven release. A zero-wait call intentionally returns the durable
acknowledgement instead, which need not yet contain the later site report.

### Final checks and cleanup

- Full **`make test` passes in 7m19s** with the shim and proxy exclusions,
  including VM storefront **1,189 unit and 501 application integration cases**,
  buyer **213 cases**, harness **316 cases**, release-tooling **1,858 cases**,
  and Helm structural/render checks. The existing optional Torch-dependent
  collection skip remains; the two required deployed journeys have zero skips.
- Final focused harness regression, architecture, packaging, lock currency,
  comment hygiene and pinned strict OpenSpec validation pass. Scoped citation
  checking still reports exactly the three future lifecycle destinations in
  [#325](https://github.com/arkhai-io/simple-compute-market/issues/325).
- Every attempted deployment was torn down. Forwarders were removed before
  their namespace owners; final owned container, volume and network inventories
  are empty. Source checkouts supplying external services are unchanged. No
  browser, tunnel, remote deployment or resident development server remains.
  No private runtime artifact or raw operator log is published here.

14.5 and 14.5c are qualified. **7.4 remains parent-owned and unchecked.**
Permanent promotion remains reviewed closeout to the lifecycle spec and
architecture, VM fulfillment contract and repository release-flow architecture;
renewable/funding-timer interpretation and rate-stop execution are outside this
foundation.
