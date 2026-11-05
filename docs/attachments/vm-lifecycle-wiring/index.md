# VM lifecycle composition checkpoint

Implementer self-check, nonvisual (no screenshots), not independent acceptance.

## Prepared target and first use

The target is this checkout's VM storefront installed over fresh internal wheels,
with an invocation-owned SQLite database and in-process ASGI transport. Payment
HTTP uses the kit-owned receipt/vector fixture; VM delivery is controlled.
Buyer, seller and administrator are deterministic public development identities
in the example, never public-network credentials. No secret, inherited deployment
selector, remote account, resident server or container is required.

From repository root:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C domains/vms/storefront reinit
uv run --project domains/vms/storefront --locked --find-links .dist \
  python domains/vms/storefront/examples/payment_smoke.py
```

This entry point was opened successfully: before approval it reports pending and
zero deliveries; after verified approval it reports provisioning, then ready on
retry with exactly one delivery and zero escrow rows. Its signed administrator
lifecycle list contains the payment deal and exact transaction reference.

The existing VM payment application-integration harness now mounts the production
lifecycle router and registers verified commitments. The kept settlement/replay
test reads that signed list through the typed storefront client. The existing
negotiation harness composes the evidence store; its kept exact-offer acceptance
test observes the original buyer request and signed seller acceptance retained
with proof headers. No new permanent test function was added.

## Implemented boundary

- VM settlement composition owns the servicing store, seller half, once-payment
  adapter and mediation adapter. Bindings read exact retained Agreement bytes,
  not a model reserialization. Payment reads receive their durable sequence floor.
- A verified receipt registers immutable buyer/seller, commitment and timing.
  Revalidated stored receipts register identically after restart.
- The existing servicing cycle runs authority/account respondent discovery before
  deal watch; both use the kit's case-keyed append journal. Bounded deal pages
  rotate; respondent resolution checks the exact retained Agreement digest.
- Credentials are resolved from identity-bound environment references, not copied
  into Agreements or runtime reports. Missing mediation credentials remain a
  named repair state. Lifespan shutdown closes clients.
- The signed negotiation response boundary retains exact incoming/outgoing bodies
  and proof headers with method, operation, resource, role and principal context.
  Transport replay and lifecycle/evidence tables remain distinct.
- Static administrator loop-control routes precede the lifecycle router's dynamic
  negotiation segment, so pause/resume are not mistaken for deal IDs.
- Lease truncation and administrator interruption preserve seconds and continue to
  accept historical minute-format inputs.

## Verification and repairs

The precision change is committed as `e3a142381`.
Its 28 existing focused VM cases pass. Fresh wheels, architecture, packaging,
lock currency, comment hygiene and pinned strict OpenSpec validation pass.

The composition first-use example passes. The combined payment/negotiation
application integration run passes 57 existing cases. Broader VM runs exposed
composition test doubles without the optional lifecycle service, then the static
pause-route collision; both are repaired. A new evidence assertion initially
assumed canonical response formatting and lowercase headers, while FastAPI keeps
its own JSON formatting and signed-header casing; it now inspects the unchanged
retained payload and proof without inventing an alternate wire serialization.

`90de651de` repairs an inherited publication omission: the manifest and
PyPI workflow now include servicing once instead of a duplicate mediation entry,
and the release table states the servicing kit and VM dependency closure.

## Aggregate result

The full `make test` aggregate passes in 8m36s with both all-proxy
variables unset, loopback no-proxy exclusions, and the shell-local Podman shim.
It includes 1,189 VM unit cases (one optional Torch collection skip), 501 VM
application-integration cases, release tooling and Helm render/structural checks.
The final envelope-context refinement separately passes all 57 existing payment
and negotiation cases again. Final packaging, architecture, lock currency,
comment hygiene and pinned strict OpenSpec validation pass after that refinement.

The package/deployment configuration models did not change, so no Helm schema
regeneration is needed. The VM storefront and end-to-end consumer were relocked
through `make lock`, not hand-edited. Publication lists contain one row each
for mediation and servicing. No sibling-domain code or shared lifecycle kit was
modified.

## Remaining assignment

This checkpoint does not claim completed VM lifecycle behavior. End service is
not yet connected to physical VM delivery: terminal/refund ends, admission,
administrator entitlement dispatch, immediate termination, site-report ingress
and buyer CLI/stages remain the following tasks. The mounted router deliberately
has no delivery-ingress/end port yet. VM buyer-half composition remains unstarted;
leave the shared buyer-composition task unchecked.

A fresh branch-built domain end-to-end stack, real local payment/mediation
qualification, buyer-end/report e2e stages and independent verification are
unrun. No scenario was added. No running server, browser, tunnel or external
resource remains. Permanent promotion remains the change's reviewed closeout.
