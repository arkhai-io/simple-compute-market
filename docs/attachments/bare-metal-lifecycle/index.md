# Bare-metal lifecycle composition checkpoint

This is an **in-progress implementation checkpoint**, not acceptance or completed
domain qualification. Sections 15.1, 15.2 and the bare-metal half of 7.4 remain
open. The starting revision is 458610d22. The surface is nonvisual; no screenshots
apply.

## Prepared setup

The prepared target is this checkout's bare-metal storefront app with real SQLite
persistence and the production lifecycle router. Site and payment boundaries use
the existing kit-backed regression setup; no external runtime is required.
Buyer, seller and administrator are explicitly deterministic public development
identities from that setup and must never be used on a public network.

The invocation owns its temporary database and in-process ASGI transport. It
starts and stops the application's lifespan and leaves no server or other
outside resource behind. It does not consume ignored configuration, inherited
deployment selectors or external credentials.

From the repository root:

~~~sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C domains/bare_metal/storefront reinit
(cd domains/bare_metal/storefront &&
  PYTHONPATH=tests uv run --find-links ../../../.dist python examples/lifecycle_first_use.py)
~~~

The [entry point](../../../domains/bare_metal/storefront/examples/lifecycle_first_use.py)
uses the existing checkout regression setup, not an installed standalone service.
That setup has no registry publication configuration; its unrelated publication
timer may log that omission. No deployed-stack readiness is claimed.

## Observed first use

- The canonical signed lifecycle client sends hosted commit twice, and the
  seller starts exactly one fulfillment after verifying the payment receipt.
- The seller's bounded list includes the negotiation and the evidence store
  retains the exact acceptance transport envelope.
- Signed end-delivery and same-key retry preserve receipt time and one physical
  termination. The receipt carries the owning mediation contract's reusable
  signed claim.
- Delivery reads report tearing down, not released capacity.
- A different authenticated principal is refused as the buyer.

This does not qualify an actual mediation service, respondent case execution,
early surrender, concurrent create cancellation or real hardware teardown.

## Regression and checks

- Existing bare-metal storefront suite: **522 passed**.
- Fresh wheel builds and affected generated locks: passed.
- Architecture, packaging, lock currency, comment hygiene and pinned strict
  OpenSpec validation: passed.
- The mounted first-use invocation above: passed.
- Full aggregate, fresh-stack domain scenarios and real payments/mediation
  qualification: **not yet run**.

The initial regression run failed because registration did not begin the caller's
SQLite transaction. That is fixed. Availability now records the seller's own
observation instead of treating a site's fixture timestamp as its observation.
A locking approach which could wait on an in-flight create was removed: the end
remains pending until create adoption re-drives the effect. The first route drive
also caught the required delivery-end claim kind; the owning model now receives
it explicitly. Original kept assertions were not weakened, and no permanent
test function was added.

## Remaining implementation

Before completing 15.1:

- Persist bounded cycle pagination and schedule physical recovery without
  requiring hosted payment publication.
- Correlate/classify site end reports against known controlling ends.
- Prove surrender before dispatch and during an in-flight create.
- Reconcile actual commitment timing with the delivery record's current
  acceptance-time initialization.
- Re-run focused checks after those repairs.

Before completing 15.2 and the bare-metal half of 7.4:

- Mount authenticated site-report receipt and recover exact reports from lease
  reads; update neutral delivery progress only on proven release.
- Remove the unbegun teardown refusal and use the buyer half's canonical
  end-delivery method, durable end journal and evidence store.
- Compose hosted buyer commit instead of the settlement transport, leaving
  Alkahest and introduction paths unchanged.
- Extend the existing domain end/report stages and qualify the fresh
  mock-provisioned lane against ready local payment and mediation authorities
  with dispute-bearing options.

The real-host lane remains unavailable without an operator-owned host. Pending
work is not counted as passing. Permanent documentation promotion remains
reviewed closeout, with destinations recorded in the change's task checkpoint.

## Cleanup

No container, HTTP server, browser page, tunnel, remote deployment or external
runtime was created. Only checkout-owned package environments and managed
build/test commands were used.
