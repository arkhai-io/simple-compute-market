# Instrument services with timing spans

## Why

No service in this repository can report where its own time goes, and no caller
can reconstruct the path a single deal took across services.

The provisioning service is the clearest case. A fulfillment request enters,
waits to be scheduled, is worked, and reports back. From outside, all of that is
one interval between the request and the callback. Queue time and service time
are different problems with different remedies — one is capacity, the other is
the provider path — and nothing this repository exposes distinguishes them. The
same is true of settlement, where waiting for a transaction receipt and
constructing the transaction are indistinguishable from the caller's side, and
of negotiation, where a feasibility probe against site capacity is invisible in
the request duration it contributes to.

The gap is not only about performance. When a deal is slow or stalls, the
question asked first is *which service is holding it*, and answering that today
means correlating log lines by timestamp across services that share no request
identifier. `monotonic-listing-reconciliation` reconstructs a 321-millisecond
ordering defect that way, and it was only tractable because the storefront
happens to carry a monotonic capacity version. Most of the flow carries no such
handle.

There is also a small piece of evidence that this was once intended and never
completed: `domains/vms/storefront` declares `opentelemetry-exporter-gcp-trace`
as a dependency, and nothing in the repository imports it.

## What Changes

- Emits OpenTelemetry spans from the storefront, registry, provisioning, and
  settlement paths, naming the intervals each service can distinguish internally
  and a caller cannot — queue wait against service time, transaction
  construction against receipt wait, feasibility probe against negotiation
  response.
- Propagates trace context through this repository's own clients and CLI, so a
  caller using the published client libraries gets end-to-end correlation
  without doing anything. A caller constructing requests by hand does not, and
  that is out of scope rather than a defect.
- Carries the deal stage as a span attribute where a span falls inside one, so
  timing is attributable in the vocabulary the lifecycle contract publishes
  rather than in service-internal terms.
- Records what a span does **not** promise: span names and attributes are a
  documented surface, and an incidental attribute is not a contract.
- Removes the unused exporter dependency from `domains/vms/storefront`, or puts
  it to use, rather than leaving a declared dependency nothing imports.

## Permanent documentation impact

- [x] Existing subsystem specification
- [x] New subsystem specification — extends observation surfaces

### Knowledge to promote

- That emitted spans are an observation surface and therefore a public contract,
  under the same rule as every other observation surface: changing one is a spec
  change rather than an implementation detail.
- The span vocabulary each service owns, and the intervals it distinguishes.
- The propagation boundary: context travels through this repository's clients
  and CLI, and no further.

## Effect boundary

This change makes span emission possible. It deploys no collector, provisions no
tracing backend, and configures no exporter endpoint. Where spans are sent, and
what stores them, is deployment configuration owned elsewhere.

## Non-Goals

- Not a metrics or alerting system. Spans carry timing and attribution; they do
  not define thresholds, and nothing here pages anyone.
- Not a replacement for the deal lifecycle contract. A span reports what
  happened and how long it took; which stages exist remains that contract's
  statement.
- Not an expectation surface. A span is the product's own report of its own
  behaviour, and a consumer deriving what *should* be true from what the product
  reported has learned only that the product agrees with itself.
- Not instrumentation of every function. The unit is an interval a service can
  distinguish and a caller cannot.

## Dependencies and Related Changes

- Depends on `declare-deal-lifecycle-contract` for the stage vocabulary a span
  attribute reports in.
- Extends `expose-product-observation-surfaces`, which establishes that an
  observation surface is a documented, versioned public contract. Spans are one,
  and inherit that rule rather than restating it.

## Impact

- Affected specs: observation surfaces, plus the settlement, fulfillment, and
  negotiation contracts where a span boundary is named
- Affected code: `core/registry`, `core/storefront`, `provisioning/compute`,
  `kit/alkahest`, `kit/site`, the domain storefronts, and the client packages
  that would propagate context
- Affected deployment: an exporter endpoint becomes a configuration value each
  service reads; absent configuration, emission is inert
