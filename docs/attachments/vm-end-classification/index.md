# VM end-source classification checkpoint

Nonvisual implementer self-check, not independent acceptance. This packet covers
the VM classification and direct failure-release continuation, not the deployed
end/report qualification.

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

## Remaining acceptance boundary

No deployed lifecycle scenario has run in this continuation. Extend
`e2e_deal` and `e2e_deal_buyer_cli` with buyer-end/report observations and
callback-proven capacity return; run both on a fresh branch-built stack through
the shell-local Podman shim with real local payments and mediation, including
dispute-bearing hosted terms and a real buyer CLI subprocess. Follow
[the local authority recipe](../aeet-s8-integration/index.md). Keep 14.5 and
parent-owned 7.4 unchecked until their respective acceptance boundaries pass.

Permanent promotion remains reviewed closeout to the lifecycle spec and
architecture, VM fulfillment contract, and repository release-flow architecture.
No container, server, browser, tunnel or external deployment was started by these
first-use encounters; none is left running.
